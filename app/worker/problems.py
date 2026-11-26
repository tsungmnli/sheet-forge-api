"""문제 관련 작업 핸들러 (웹 REST API 설계 6장). 로그에는 종류·대상 id·예외 종류만 남기고 문제 내용·이미지는 남기지 않는다.

모든 핸들러는 다시 실행해도 안전하다(멱등): 상태·행이 이미 바뀌어 있으면 아무것도 하지 않는다.
"""
import copy
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..api.problem_logic import MAX_FIGURES, normalize_read_content, search_text
from ..api.problem_service import refund_reads
from ..db.ids import new_id
from ..db.models import Page, Problem, Segment
from ..jobs import enqueue
from ..recognition import imaging
from ..recognition.llm.read import ReadParseError
from ..recognition.llm.recognizer import ReadEmptyError
from ..recognition.ports import LlmError
from ..recognition.usage import record_job_usage
from ..storage.images import StorageError

log = logging.getLogger("sheet_forge.worker")
KINDS = ("problem_read", "problem_reread", "figure_clean")
CROP_MARGIN = 0.01          # 문제 칸 크롭에 둘러 주는 여백(사진 폭·높이 비율)
MAX_REGION_REDO = 3         # 정리 중 그림 범위가 바뀌어 다시 하는 최대 횟수

CLEAN_LEVELS = (1, 2, 3, 4)   # 그림 정리 세기. 모두 미리 만들어 두고 사용자가 고른다(0 = 원본)
DEFAULT_CLEAN_LEVEL = 2
# 색 처리: erase = 색 필기를 지움(예전 방식), keep = 색을 두고 밝기로만 정리. 정리본은 두 방식을 모두 만들어 두고,
# 색 유지본의 키는 'k1'~'k4'다(levels 안에 함께 둔다). 새 그림의 처음 값은 DEFAULT_CLEAN_COLOR.
DEFAULT_CLEAN_COLOR = "keep"   # 기본은 색 유지: 인쇄된 색 그림이 낙서로 오해돼 지워지는 것보다 낙서가 남는 편이 안전하다(지우개로 지운다)


def level_key(level: int, color: str) -> str:
    return f"k{level}" if color == "keep" else str(level)
FIGURE_WIDTH_MM = 60.0      # 읽기에서 만든 그림의 기본 폭(add_figure 기본값과 같다)


def figures_from_read(raw_figures) -> list:
    """읽기 결과의 그림 상자(box_2d=[ymin,xmin,ymax,xmax], 0~1000)를 그림 항목(bbox=[x0,y0,x1,y1], 0~1)으로 바꾼다.

    크롭 이미지 전체 기준이라 변환만 하면 된다. 너무 작거나 뒤집힌 상자는 건너뛴다(check_bbox와 같은 기준).
    """
    out = []
    for f in raw_figures or []:
        box = f.get("box_2d") if isinstance(f, dict) else None
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        y0, x0, y1, x1 = (min(1.0, max(0.0, float(v) / 1000.0)) for v in box)
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            continue
        out.append({"id": new_id("fig"), "kind": "crop", "bbox": [x0, y0, x1, y1], "raw_ref": None,
                    "clean_ref": None, "use": "clean", "placement": f.get("placement") or "after_stem",
                    "width_mm": FIGURE_WIDTH_MM, "state": "processing"})
    return out[:MAX_FIGURES]


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
        kept = (p.content or {}).get("figures") or []
        # 그림은 서버가 관리: 이미 있으면 다시 읽어도 유지(고친 범위 보호), 없을 때만 읽기 결과로 만든다
        new_figs = [] if kept else figures_from_read(result.figures)
        content["figures"] = kept or new_figs
        log.info("읽기 그림 반영 problem=%s kept=%d read=%d new=%d", job.target_id, len(kept),
                 len(result.figures or []), len(new_figs))
        p.content, p.search_text = content, search_text(content)
        if result.points is not None:   # 못 읽었으면 기존 배점(선생님이 직접 넣은 값 포함)을 그대로 둔다
            p.points = result.points
        # 되돌리기 기준은 가장 최근의 기계 읽기 결과(다시 읽기를 요청했다면 그 결과가 새 기준)
        p.recognized = {k: copy.deepcopy(v) for k, v in content.items() if k != "figures"}
        # 지운 그림 보관 목록은 다시 읽어도 남긴다
        removed = (p.ocr_meta or {}).get("removed_figures")
        p.ocr_meta = {**dict(result.meta or {}), **({"removed_figures": removed} if removed else {})}
        p.crop_ref, p.status = crop_ref, "needs_review"
        _bump(p)
        for f in new_figs:
            enqueue(s, job.owner_id, "figure_clean", "figure", f["id"])
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
            f0 = _find_figure(p, fid)
            pid, crop_ref, bbox = p.id, p.crop_ref, list(f0["bbox"])
            prev_level = f0.get("clean_level")
            # 이미 정리해 본 그림은 그때 고른 색 처리를 이어 가고(옛 그림은 erase), 처음이면 기본값을 쓴다
            prev_color = (f0.get("clean_color") or "erase") if prev_level is not None else DEFAULT_CLEAN_COLOR
            if prev_color == "pick":   # 범위가 바뀌면 색 견본도 달라지므로 고른 색은 풀고 색 유지로 돌아간다
                prev_color = "keep"
        obj = store.get(crop_ref)
        if obj is None:
            raise StorageError("MISSING_CROP")
        raw, _, _ = imaging.crop_region(obj[0], bbox, 0.0, "PNG")
        raw_ref, levels = new_id("img"), {}
        store.put(raw_ref, raw, "image/png")
        try:
            palette = cleaner.palette(raw)   # 지울 색을 고르는 색 견본
        except Exception as exc:  # noqa: BLE001 — 색 견본은 없어도 된다
            log.warning("그림 색 견본 실패 figure=%s %s", fid, type(exc).__name__)
            palette = []
        for color in ("erase", "keep"):
            for lv in CLEAN_LEVELS:
                try:
                    res = cleaner.clean(raw, lv, keep_color=(color == "keep"))
                    if res.clean is not None:
                        ref = new_id("img")
                        store.put(ref, res.clean, res.content_type or "image/png")
                        levels[level_key(lv, color)] = ref
                except Exception as exc:  # noqa: BLE001 — 정리 실패는 치명적이지 않다(원본 사용)
                    log.warning("그림 정리 실패 figure=%s level=%s color=%s %s", fid, lv, color, type(exc).__name__)
        with db.session() as s:
            p = s.execute(select(Problem).where(Problem.id == pid).with_for_update()).scalar_one_or_none()
            fig = _find_figure(p, fid) if p is not None and p.deleted_at is None else None
            if fig is None:
                _drop(store, raw_ref, *levels.values())
                return
            if list(fig["bbox"]) != bbox:   # 정리하는 사이 범위가 바뀜 → 새 범위로 다시
                _drop(store, raw_ref, *levels.values())
                continue
            old = {fig.get("raw_ref"), fig.get("clean_ref"), fig.get("pick_ref"), *(fig.get("levels") or {}).values()}
            # 사용자가 고른 단계를 이어 간다(범위를 고쳐 다시 정리해도 같은 세기). 없는 단계면 원본(0)
            want = prev_level if prev_level in (0, *CLEAN_LEVELS) else DEFAULT_CLEAN_LEVEL
            level = want if want == 0 or level_key(want, prev_color) in levels else 0
            clean_ref = levels.get(level_key(level, prev_color)) if level else None
            p.content = {**p.content, "figures": [
                dict(f, raw_ref=raw_ref, clean_ref=clean_ref, levels=levels, clean_level=level, clean_color=prev_color,
                     palette=palette, pick_ref=None, clean_hues=None,
                     state="ready", erased=False,
                     use="clean" if clean_ref else "raw")
                if f.get("id") == fid else f for f in p.content["figures"]]}
            _bump(p)
            s.commit()
        _drop(store, *old)
        return
    raise RuntimeError("FIGURE_REGION_CHANGING")


FAIL_GENERIC = "읽는 중에 문제가 생겼어요. 다시 읽어 보세요."
FAIL_BY_LLM_KIND = {
    "timeout": "읽는 데 시간이 너무 오래 걸렸어요. 잠시 뒤 다시 읽어 보세요.",
    "network": "읽기 서비스에 연결하지 못했어요. 잠시 뒤 다시 읽어 보세요.",
    "rate_limit": "지금 읽기 요청이 몰려 있어요. 잠시 뒤 다시 읽어 보세요.",
    "server": "읽기 서비스가 잠시 불안정해요. 잠시 뒤 다시 읽어 보세요.",
    "blocked": "이 부분은 AI가 읽기를 거부했어요. 영역을 좁게 다시 고르면 읽힐 수 있어요. 안 되면 직접 입력해 주세요.",
    "empty": "글자와 수식을 찾지 못했어요. 영역을 다시 고른 뒤 읽어 보세요.",
    "bad_response": "읽은 결과를 받지 못했어요. 다시 읽어 보세요.",
    "auth": "읽기 서비스 설정에 문제가 있어요. 관리자에게 알려 주세요.",
    "bad_request": "읽기 서비스 설정에 문제가 있어요. 관리자에게 알려 주세요.",
}


def read_fail_info(exc: BaseException | None) -> dict:
    """읽기 실패 원인을 선생님께 보여 줄 쉬운 문장으로 바꾼다. code는 종류만(내용·키 없음)."""
    if isinstance(exc, LlmError):
        info = {"code": f"llm_{exc.kind}", "message": FAIL_BY_LLM_KIND.get(exc.kind, FAIL_GENERIC)}
        if exc.detail:
            info["detail"] = exc.detail   # 차단 종류 이름만(SAFETY·RECITATION 등). 내용 없음
        return info
    if isinstance(exc, ReadEmptyError):
        return {"code": "empty", "message": "글자와 수식을 찾지 못했어요. 영역을 다시 고른 뒤 읽어 보세요."}
    if isinstance(exc, ReadParseError):
        return {"code": "parse", "message": "읽은 내용을 정리하지 못했어요. 다시 읽어 보세요. 계속 안 되면 직접 입력해 주세요."}
    if isinstance(exc, StorageError):
        return {"code": "storage", "message": "사진을 불러오지 못했어요. 잠시 뒤 다시 읽어 보세요."}
    return {"code": "unknown", "message": FAIL_GENERIC}


def mark_failed(db, job, exc: BaseException | None = None) -> None:
    """마지막 시도까지 실패했을 때 사용자에게 보이는 상태를 정리한다."""
    with db.session() as s:
        if job.kind in ("problem_read", "problem_reread"):
            p = s.execute(select(Problem).where(Problem.id == job.target_id).with_for_update()).scalar_one_or_none()
            if p is not None and p.deleted_at is None and p.status == "recognizing":
                info = read_fail_info(exc)
                # 이미 읽어 둔 결과가 있는데 '다시 읽기'만 실패했다면, 결과를 비운 실패 상태로 두지 않고
                # 이전 내용 그대로 확인 필요로 돌려놓는다(실패 사유만 따로 알려 준다).
                has_prev = (job.kind == "problem_reread" and p.recognized is not None
                            and bool(p.search_text or (p.content or {}).get("figures")))
                # 읽기 한도는 요청할 때 미리 차감했다(읽기 1, 다시 읽기 2). 끝내 실패했으니 그만큼 돌려준다.
                # 이 블록은 상태가 recognizing일 때만 들어오므로 한 번만 돌려준다.
                refund_reads(s, job.owner_id, 2 if job.kind == "problem_reread" else 1, datetime.now(timezone.utc))
                if has_prev:
                    p.status = "needs_review"
                    p.ocr_meta = {**(p.ocr_meta or {}), "reread_fail": info}
                else:
                    p.status = "failed"
                    p.ocr_meta = {**(p.ocr_meta or {}), "fail": info}   # 다시 읽기에 성공하면 ocr_meta가 새로 써져 사라진다
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
