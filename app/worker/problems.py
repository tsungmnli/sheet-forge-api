"""문제 관련 작업 핸들러 (웹 REST API 설계 6장). 로그에는 종류·대상 id·예외 종류만 남기고 문제 내용·이미지는 남기지 않는다.

모든 핸들러는 다시 실행해도 안전하다(멱등): 상태·행이 이미 바뀌어 있으면 아무것도 하지 않는다.
"""
import copy
import logging

from sqlalchemy import func, select

from ..api.problem_logic import MAX_FIGURES, normalize_read_content, search_text
from ..db.ids import new_id
from ..db.models import Page, Problem, Segment
from ..jobs import enqueue
from ..recognition import imaging
from ..recognition.usage import record_job_usage
from ..storage.images import StorageError

log = logging.getLogger("sheet_forge.worker")
KINDS = ("problem_read", "problem_reread", "figure_clean")
CROP_MARGIN = 0.01          # 문제 칸 크롭에 둘러 주는 여백(사진 폭·높이 비율)
MAX_REGION_REDO = 3         # 정리 중 그림 범위가 바뀌어 다시 하는 최대 횟수

CLEAN_LEVELS = (1, 2, 3, 4)   # 그림 정리 세기. 모두 미리 만들어 두고 사용자가 고른다(0 = 원본)
DEFAULT_CLEAN_LEVEL = 2
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
        obj = store.get(crop_ref)
        if obj is None:
            raise StorageError("MISSING_CROP")
        raw, _, _ = imaging.crop_region(obj[0], bbox, 0.0, "PNG")
        raw_ref, levels = new_id("img"), {}
        store.put(raw_ref, raw, "image/png")
        for lv in CLEAN_LEVELS:
            try:
                res = cleaner.clean(raw, lv)
                if res.clean is not None:
                    ref = new_id("img")
                    store.put(ref, res.clean, res.content_type or "image/png")
                    levels[str(lv)] = ref
            except Exception as exc:  # noqa: BLE001 — 정리 실패는 치명적이지 않다(원본 사용)
                log.warning("그림 정리 실패 figure=%s level=%s %s", fid, lv, type(exc).__name__)
        with db.session() as s:
            p = s.execute(select(Problem).where(Problem.id == pid).with_for_update()).scalar_one_or_none()
            fig = _find_figure(p, fid) if p is not None and p.deleted_at is None else None
            if fig is None:
                _drop(store, raw_ref, *levels.values())
                return
            if list(fig["bbox"]) != bbox:   # 정리하는 사이 범위가 바뀜 → 새 범위로 다시
                _drop(store, raw_ref, *levels.values())
                continue
            old = {fig.get("raw_ref"), fig.get("clean_ref"), *(fig.get("levels") or {}).values()}
            # 사용자가 고른 단계를 이어 간다(범위를 고쳐 다시 정리해도 같은 세기). 없는 단계면 원본(0)
            want = prev_level if prev_level in (0, *CLEAN_LEVELS) else DEFAULT_CLEAN_LEVEL
            level = want if want == 0 or str(want) in levels else 0
            clean_ref = levels.get(str(level))
            p.content = {**p.content, "figures": [
                dict(f, raw_ref=raw_ref, clean_ref=clean_ref, levels=levels, clean_level=level, state="ready", erased=False,
                     use="clean" if clean_ref else "raw")
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
