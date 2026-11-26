"""작업자: jobs 테이블에서 작업을 가져와 처리한다 (웹 REST API 설계 6장).

로그에는 작업 종류·대상 id·시도 횟수·예외 종류만 남긴다(문제 내용·이미지 없음).
"""
import logging
import os
import signal
import threading
import time

from sqlalchemy import func, select, update

from .. import jobs
from ..api.settings import Settings
from ..db.database import Database
from ..db.ids import new_id
from ..db.models import Page, Segment
from ..recognition.factory import build_cleaner, build_processor, build_recognizer
from ..recognition.fake import FakeFigureCleaner, FakePageProcessor
from ..recognition.llm.read import ReadParseError
from ..recognition.ports import LlmError
from ..recognition.usage import llm_event, record_job_usage
from ..storage.images import StorageError, build_store
from . import maintenance
from . import problems as problem_jobs

log = logging.getLogger("sheet_forge.worker")
MAX_ATTEMPTS = 3  # 첫 시도 + 지연 재시도 2번
PAGE_FAILED_MESSAGE = "사진을 읽지 못했어요. 다시 올리거나 밝은 곳에서 다시 찍어 주세요."


class UnknownJob(Exception):
    pass


def _set_page_processing(db, page_id: str, processing: dict) -> None:
    with db.session() as s:
        s.execute(update(Page).where(Page.id == page_id, Page.deleted_at.is_(None))
                  .values(processing=processing, updated_at=func.now()))
        s.commit()


def _correction_request(correction: dict | None) -> dict:
    """pages.correction에서 선생님이 고른 설정만 꺼낸다(applied 같은 결과 값은 뺀다). 없으면 자동."""
    c = correction or {}
    return {"mode": c.get("mode") or "auto", "rotation": int(c.get("rotation") or 0),
            "angle": float(c.get("angle") or 0.0), "corners": c.get("corners")}


def handle_page_process(db, store, processor, job: jobs.ClaimedJob) -> None:
    with db.session() as s:
        page = s.get(Page, job.target_id)
        if page is None or page.deleted_at is not None:
            return  # 그 사이 지워짐: 할 일 없음
        original_ref, old_corrected = page.original_ref, page.corrected_ref
        request = _correction_request(page.correction)
        page.processing = {"state": "running", "step": "correcting", "message": None}
        s.commit()
    obj = store.get(original_ref)
    if obj is None:
        raise StorageError("MISSING_ORIGINAL")
    result = processor.process(obj[0], obj[1], correction=request)
    if result.usage is not None:  # B5-3c-2: 분할 LLM 사용량(가짜 처리기는 None)
        record_job_usage(db, job, [llm_event("segment", "", result.usage)])
    if result.fallback_reason:  # 종류만 남긴다(응답·사진 내용 없음)
        log.warning("분할 폴백 page=%s reason=%s", job.target_id, result.fallback_reason)
    corrected_ref = original_ref
    if result.corrected is not None:
        corrected_ref = new_id("img")
        store.put(corrected_ref, result.corrected, result.corrected_content_type or obj[1])
    with db.session() as s:
        page = s.get(Page, job.target_id)
        if page is None or page.deleted_at is not None:
            return
        page.corrected_ref, page.width, page.height = corrected_ref, result.width, result.height
        page.processing = {"state": "done", "step": None, "message": result.message}
        # 처리하는 사이 선생님이 보정 설정을 또 바꿨으면 그 작업이 기록한다(덮어쓰지 않는다)
        if result.applied is not None and _correction_request(page.correction) == request:
            page.correction = {**request, "applied": result.applied}
        page.updated_at = func.now()
        has_segments = s.execute(select(func.count(Segment.id)).where(
            Segment.page_id == page.id, Segment.deleted_at.is_(None))).scalar_one()
        if not has_segments:  # 다시 실행해도 칸이 겹쳐 생기지 않게(멱등)
            for i, d in enumerate(result.segments):
                s.add(Segment(id=new_id("seg"), owner_id=page.owner_id, page_id=page.id, exam_id=page.exam_id,
                              position=i, bbox=[float(v) for v in d.bbox], number=d.number))
        s.commit()
    if old_corrected and old_corrected not in (original_ref, corrected_ref):  # 다시 보정: 예전 보정본 치우기
        try:
            store.delete(old_corrected)
        except Exception:  # noqa: BLE001 — 남아도 정기 정리 대상
            log.warning("예전 보정본 삭제 실패 page=%s", job.target_id)


def run_once(db, store, processor, max_attempts: int = MAX_ATTEMPTS, retry_delay_s: float = 5,
             stale_s: int = 300, *, recognizer=None, cleaner=None) -> bool:
    """작업 하나를 처리한다. 가져올 작업이 없으면 False."""
    job = jobs.claim(db, stale_s)
    if job is None:
        return False
    try:
        if job.kind == "page_process":
            handle_page_process(db, store, processor, job)
        elif job.kind == "problem_read" and recognizer is not None:
            problem_jobs.handle_problem_read(db, store, recognizer, job)
        elif job.kind == "problem_reread" and recognizer is not None:
            problem_jobs.handle_problem_reread(db, store, recognizer, job)
        elif job.kind == "figure_clean" and cleaner is not None:
            problem_jobs.handle_figure_clean(db, store, cleaner, job)
        else:
            raise UnknownJob(job.kind)
        jobs.complete(db, job.id)
    except Exception as exc:  # noqa: BLE001
        code = type(exc).__name__
        if isinstance(exc, (ReadParseError, LlmError)):
            code = f"{code}({exc})"  # 종류(와 상태 코드·토큰 수)만 담긴 메시지
        log.error("작업 실패 kind=%s target=%s attempts=%d %s", job.kind, job.target_id, job.attempts, code)
        # 안전·저작물 차단은 같은 사진으로 다시 해도 같다(모델 바꿔 읽기는 인식기 안에서 이미 해 봤다).
        final = (job.attempts >= max_attempts or isinstance(exc, UnknownJob)
                 or (isinstance(exc, LlmError) and exc.kind == "blocked"))
        if final:
            jobs.fail(db, job.id, code)
        else:
            jobs.retry_later(db, job.id, retry_delay_s * job.attempts, code)
        if job.kind == "page_process":
            if final:
                _set_page_processing(db, job.target_id, {"state": "failed", "step": None, "message": PAGE_FAILED_MESSAGE})
            else:
                _set_page_processing(db, job.target_id, {"state": "queued", "step": "correcting", "message": None})
        elif final and job.kind in problem_jobs.KINDS:
            problem_jobs.mark_failed(db, job, exc)
    return True


def main(stop: threading.Event | None = None) -> None:
    """stop을 받으면(API 안에서 스레드로 돌 때) 시그널 처리는 하지 않고 그 이벤트로만 멈춘다."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    if not settings.database_url:
        raise SystemExit("SHEET_FORGE_DATABASE_URL이 필요해요.")
    store = build_store(settings)
    if store is None:
        raise SystemExit("MinIO 설정(SHEET_FORGE_MINIO_ENDPOINT 등)이 필요해요.")
    db = Database(settings.database_url, "", 2, settings.db_connect_timeout_s)
    processor = build_processor(settings)
    recognizer, cleaner = build_recognizer(settings), build_cleaner(settings)
    poll_s = float(os.environ.get("SHEET_FORGE_WORKER_POLL_S", "2"))
    maint_s = float(os.environ.get("SHEET_FORGE_MAINTENANCE_INTERVAL_S", "86400"))  # 0이면 정기 정리를 하지 않는다
    next_maint = time.monotonic()  # 시작 직후 한 번, 그 뒤 maint_s마다
    if stop is None:
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        if maint_s > 0 and time.monotonic() >= next_maint:
            next_maint = time.monotonic() + maint_s
            try:
                maintenance.run_maintenance(db, store, settings.trash_retention_days)
            except Exception as exc:  # noqa: BLE001 — 정리가 실패해도 작업 처리는 계속한다
                log.error("정기 정리 오류 %s", type(exc).__name__)
        try:
            did = run_once(db, store, processor, recognizer=recognizer, cleaner=cleaner)
        except Exception as exc:  # noqa: BLE001 — DB·저장소가 잠시 끊겨도 작업자는 계속 돈다
            log.error("작업자 오류 %s", type(exc).__name__)
            did = False
        if not did:
            stop.wait(poll_s)
    db.dispose()


if __name__ == "__main__":
    main()
