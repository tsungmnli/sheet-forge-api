"""문제 관련 작업 핸들러 (웹 REST API 설계 6장). 로그에는 종류·대상 id·예외 종류만 남기고 문제 내용·이미지는 남기지 않는다.

모든 핸들러는 다시 실행해도 안전하다(멱등): 상태·행이 이미 바뀌어 있으면 아무것도 하지 않는다.
"""
import copy
import logging

from sqlalchemy import func, select

from ..api.problem_logic import normalize_read_content, search_text
from ..db.ids import new_id
from ..db.models import Page, Problem, Segment
from ..recognition import imaging
from ..recognition.usage import record_job_usage
from ..storage.images import StorageError

log = logging.getLogger("sheet_forge.worker")
KINDS = ("problem_read", "problem_reread", "figure_clean")
CROP_MARGIN = 0.01          # 문제 칸 크롭에 둘러 주는 여백(사진 폭·높이 비율)
MAX_REGION_REDO = 3         # 정리 중 그림 범위가 바뀌어 다시 하는 최대 횟수


def _drop(store, *refs) -> None:
    for ref in refs:
        if ref:
            try:
                store.delete(ref)
            except StorageError:
                log.warning("이미지 정리 실패(무시)")


def _bump(p: Problem) -> None:
    p.version = p.version + 1
    p.updated_at = func.now()


def handle_problem_read(db, store, recognizer, job, tier: str = "default") -> None:
    """칸 이미지를 잘라 읽고 needs_review로 바꾼다. 읽는 동안 사용자가 지웠거나 상태가 바뀌었으면 결과를 버린다."""
    with db.session() as s:
        p = s.get(Problem, job.target_id)
        if p is None or p.deleted_at is not None or p.status != "recognizing":
            return
        seg = s.get(Segment, p.segment_id)
        page = s.get(Page, seg.page_id)
        page_ref, bbox, old_crop = page.corrected_ref or page.original_ref, list(seg.bbox), p.crop_ref
    obj = store.get(page_ref)
    if obj is None:
        raise StorageError("MISSING_PAGE_IMAGE")
    crop, content_type, _ = imaging.crop_region(obj[0], bbox, CROP_MARGIN)
    crop_ref = new_id("img")
    store.put(crop_ref, crop, content_type)
    result = recognizer.read(crop, tier)
    record_job_usage(db, job, (result.meta or {}).get("usage"))   # B5-3c-2: 결과를 버리게 돼도 호출 비용은 남긴다
    content = normalize_read_content(result.content)
    with db.session() as s:
        p = s.execute(select(Problem).where(Problem.id == job.target_id).with_for_update()).scalar_one_or_none()
        if p is None or p.deleted_at is not None or p.status != "recognizing":
            _drop(store, crop_ref)
            return
        content["figures"] = (p.content or {}).get("figures") or []   # 그림은 서버가 관리: 다시 읽어도 유지
        p.content, p.search_text = content, search_text(content)
        # 되돌리기 기준은 가장 최근의 기계 읽기 결과(다시 읽기를 요청했다면 그 결과가 새 기준)
        p.recognized = {k: copy.deepcopy(v) for k, v in content.items() if k != "figures"}
        p.ocr_meta = dict(result.meta or {})
        p.crop_ref, p.status = crop_ref, "needs_review"
        _bump(p)
        s.commit()
    _drop(store, old_crop)


def handle_problem_reread(db, store, recognizer, job) -> None:
    handle_problem_read(db, store, recognizer, job, tier="high")


def _find_figure(p: Problem, fid: str):
    for f in (p.content or {}).get("figures") or []:
        if f.get("id") == fid:
            return f
    return None


def handle_figure_clean(db, store, cleaner, job) -> None:
    """그림 범위를 문제 크롭에서 잘라(raw) 정리(clean)한다. 정리에 실패하면 원본 그림을 쓴다."""
    fid = job.target_id
    for _ in range(MAX_REGION_REDO):
        with db.session() as s:
            p = s.execute(select(Problem).where(Problem.deleted_at.is_(None),
                                                Problem.content.contains({"figures": [{"id": fid}]}))).scalar_one_or_none()
            if p is None or p.crop_ref is None:
                return  # 문제나 그림이 그 사이 지워짐
            pid, crop_ref, bbox = p.id, p.crop_ref, list(_find_figure(p, fid)["bbox"])
        obj = store.get(crop_ref)
        if obj is None:
            raise StorageError("MISSING_CROP")
        raw, _, _ = imaging.crop_region(obj[0], bbox, 0.0, "PNG")
        raw_ref, clean_ref = new_id("img"), None
        store.put(raw_ref, raw, "image/png")
        try:
            res = cleaner.clean(raw)
            if res.clean is not None:
                clean_ref = new_id("img")
                store.put(clean_ref, res.clean, res.content_type or "image/png")
        except Exception as exc:  # noqa: BLE001 — 정리 실패는 치명적이지 않다(원본 사용)
            log.warning("그림 정리 실패 figure=%s %s", fid, type(exc).__name__)
        with db.session() as s:
            p = s.execute(select(Problem).where(Problem.id == pid).with_for_update()).scalar_one_or_none()
            fig = _find_figure(p, fid) if p is not None and p.deleted_at is None else None
            if fig is None:
                _drop(store, raw_ref, clean_ref)
                return
            if list(fig["bbox"]) != bbox:   # 정리하는 사이 범위가 바뀜 → 새 범위로 다시
                _drop(store, raw_ref, clean_ref)
                continue
            old = (fig.get("raw_ref"), fig.get("clean_ref"))
            p.content = {**p.content, "figures": [
                dict(f, raw_ref=raw_ref, clean_ref=clean_ref, state="ready", use="clean" if clean_ref else "raw")
                if f.get("id") == fid else f for f in p.content["figures"]]}
            _bump(p)
            s.commit()
        _drop(store, *old)
        return
    raise RuntimeError("FIGURE_REGION_CHANGING")


def mark_failed(db, job) -> None:
    """마지막 시도까지 실패했을 때 사용자에게 보이는 상태를 정리한다."""
    with db.session() as s:
        if job.kind in ("problem_read", "problem_reread"):
            p = s.execute(select(Problem).where(Problem.id == job.target_id).with_for_update()).scalar_one_or_none()
            if p is not None and p.deleted_at is None and p.status == "recognizing":
                p.status = "failed"
                _bump(p)
        elif job.kind == "figure_clean":
            p = s.execute(select(Problem).where(Problem.deleted_at.is_(None), Problem.content.contains(
                {"figures": [{"id": job.target_id}]})).with_for_update()).scalar_one_or_none()
            if p is not None:
                p.content = {**p.content, "figures": [dict(f, state="failed") if f.get("id") == job.target_id else f
                                                      for f in p.content["figures"]]}
                _bump(p)
        s.commit()


def requeue_state(db, job) -> None:
    """재시도 대기 중에는 상태를 그대로 둔다(문제는 recognizing, 그림은 processing)."""
    return None
