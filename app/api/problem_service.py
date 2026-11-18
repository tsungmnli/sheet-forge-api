"""문제(Problem) 서비스: 읽기 시작, 조회, 자동 저장, 상태 전이, 그림 (웹 REST API 설계 4·5.4·5.5). 커밋은 여기서 한다.

상태를 바꾸는 함수는 행을 FOR UPDATE로 잠근 채 version·status를 확인하고 바꾼다(작업자·다른 탭과 겹쳐도 안전).
"""
import copy
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy import func, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..db.ids import new_id
from ..db.models import Page, Problem, ReadUsage, Segment
from ..jobs import enqueue
from .edit_stats import count_edits
from .errors import ApiError
from .figure_erase import prepare_erased
from .messages import friendly
from .problem_logic import (MAX_FIGURES, analyze, empty_content, normalize_content, preview, preview_tex, search_text)
from .repo import alive, soft_delete
from .segment_service import check_bbox, has_problem
from .serialize import POLL_MS, image_url
from .web_service import _require_exam, touch_exam
from ..storage.images import StorageError

EDITABLE = ("needs_review", "failed")


def _load(session, owner: str, pid: str, lock: bool = False) -> Problem:
    stmt = select(Problem).where(Problem.id == pid, *alive(Problem, owner))
    if lock:
        stmt = stmt.with_for_update()
    p = session.execute(stmt).scalar_one_or_none()
    if p is None:
        raise ApiError(404, "NOT_FOUND")
    return p


def _bump(p: Problem) -> None:
    """행을 잠근 상태에서만 부른다."""
    p.version = p.version + 1
    p.updated_at = func.now()


def _check_version(p: Problem, version: int) -> None:
    if p.version != version:
        raise ApiError(412, "VERSION_CONFLICT")


def _require_editable(p: Problem) -> None:
    if p.status == "recognizing":
        raise ApiError(409, "PROBLEM_BUSY")
    if p.status == "confirmed":
        raise ApiError(409, "PROBLEM_CONFIRMED")


def _fail_reason(p: Problem) -> str | None:
    """읽기에 실패한 문제는 왜 실패했는지, 다시 읽기만 실패해 이전 결과를 남긴 문제는 그 사유를 쉬운 문장으로 알려 준다."""
    key = {"failed": "fail", "needs_review": "reread_fail"}.get(p.status)
    return ((p.ocr_meta or {}).get(key) or {}).get("message") or None if key else None


def _clear_fail(p: Problem) -> None:
    meta = p.ocr_meta or {}
    if "fail" in meta or "reread_fail" in meta:
        p.ocr_meta = {k: v for k, v in meta.items() if k not in ("fail", "reread_fail")}


def problem_view(session, p: Problem) -> dict:
    seg = session.get(Segment, p.segment_id)
    hints, blockers, has = analyze(p.content)
    if not has:
        blockers = [{"path": "", "code": "EMPTY_PROBLEM", "message": friendly("EMPTY_PROBLEM")}] + blockers
    return {"id": p.id, "exam_id": p.exam_id, "status": p.status, "version": p.version,
            "source": {"page_id": seg.page_id, "segment_id": seg.id, "bbox": list(seg.bbox), "number": seg.number,
                       "crop_url": image_url(p.crop_ref)},
            "content": p.content, "points": p.points, "ocr": {"has_recognized": p.recognized is not None},
            "hints": hints,
            "removed_figures": (p.ocr_meta or {}).get("removed_figures") or [],
            "fail_reason": _fail_reason(p),
            "checks": {"can_confirm": p.status in EDITABLE and not blockers, "blockers": blockers},
            "poll_after_ms": POLL_MS if p.status == "recognizing" else None}


def get_problem(session, owner: str, pid: str) -> dict:
    return problem_view(session, _load(session, owner, pid))


# ---------- 읽기 ----------
def _today(now):
    """읽기 한도의 '하루'는 한국 시간 기준(선생님의 하루)."""
    return now.astimezone(timezone(timedelta(hours=9))).date()


def consume_reads(session, owner: str, units: int, limit: int, now) -> None:
    """하루 읽기 한도에서 units만큼 쓴다(다시 읽기는 2배 가중). 넘으면 429 READ_LIMIT. 커밋은 호출자."""
    if units <= 0:
        return
    if units > limit:
        raise ApiError(429, "READ_LIMIT")
    stmt = (pg_insert(ReadUsage).values(owner_id=owner, day=_today(now), units=units)
            .on_conflict_do_update(index_elements=["owner_id", "day"], set_={"units": ReadUsage.units + units},
                                   where=(ReadUsage.units + units <= limit))
            .returning(ReadUsage.units))
    if session.execute(stmt).first() is None:
        raise ApiError(429, "READ_LIMIT")


def refund_reads(session, owner: str, units: int, now) -> None:
    """읽기에 끝내 실패했을 때 미리 차감한 한도를 돌려준다(0 밑으로는 내리지 않는다). 커밋은 호출자."""
    if units <= 0:
        return
    session.execute(update(ReadUsage).where(ReadUsage.owner_id == owner, ReadUsage.day == _today(now))
                    .values(units=func.greatest(ReadUsage.units - units, 0)))


def read_segments(session, owner: str, exam_id: str, segment_ids, settings, now) -> dict:
    """고른(또는 지정한) 칸을 읽는다. 이미 문제가 있는 칸은 건너뛴다(중복 비용 방지)."""
    _require_exam(session, owner, exam_id)
    base = (select(Segment).join(Page, Page.id == Segment.page_id)
            .where(Segment.exam_id == exam_id, *alive(Segment, owner), Page.deleted_at.is_(None))
            .order_by(Page.position, Segment.position, Segment.id))
    skipped, targets = [], []
    if segment_ids is None:
        targets = list(session.execute(base.where(Segment.marked.is_(True), ~has_problem(Segment.id))).scalars())
    else:
        by_id = {s.id: s for s in session.execute(base.where(Segment.id.in_(segment_ids))).scalars()}
        read_ids = set(session.execute(select(Problem.segment_id).where(
            Problem.segment_id.in_(list(by_id)), Problem.deleted_at.is_(None))).scalars())
        for sid in dict.fromkeys(segment_ids):  # 중복 제거, 요청 순서 유지
            seg = by_id.get(sid)
            if seg is None:
                skipped.append({"segment_id": sid, "reason": "not_found"})
            elif sid in read_ids:
                skipped.append({"segment_id": sid, "reason": "already_read"})
            elif not seg.marked:
                skipped.append({"segment_id": sid, "reason": "not_picked"})
            else:
                targets.append(seg)
    if len(targets) > settings.max_read_batch:
        raise ApiError(422, "TOO_MANY_SEGMENTS")
    consume_reads(session, owner, len(targets), settings.daily_read_limit, now)
    created = []
    for seg in targets:
        pid = new_id("prob")
        stmt = (pg_insert(Problem)
                .values(id=pid, owner_id=owner, exam_id=exam_id, segment_id=seg.id, status="recognizing",
                        content=empty_content(), search_text="")
                .on_conflict_do_nothing(index_elements=["segment_id"], index_where=text("deleted_at IS NULL"))
                .returning(Problem.id))
        if session.execute(stmt).first() is None:  # 그 사이 다른 요청이 먼저 읽기 시작함
            skipped.append({"segment_id": seg.id, "reason": "already_read"})
            continue
        enqueue(session, owner, "problem_read", "problem", pid)
        created.append({"id": pid, "segment_id": seg.id, "status": "recognizing"})
    if created:
        touch_exam(session, exam_id)
    session.commit()
    return {"requested": len(created), "skipped": skipped, "problems": created,
            "poll_after_ms": POLL_MS if created else None}


def list_exam_problems(session, owner: str, exam_id: str, state) -> dict:
    """시험지 '문제' 탭. 항목은 고른 칸이고, 읽기 전 칸도 not_read로 나온다."""
    _require_exam(session, owner, exam_id)
    rows = session.execute(
        select(Segment, Problem).select_from(Segment).join(Page, Page.id == Segment.page_id)
        .outerjoin(Problem, and_(Problem.segment_id == Segment.id, Problem.deleted_at.is_(None)))
        .where(Segment.exam_id == exam_id, *alive(Segment, owner), Segment.marked.is_(True), Page.deleted_at.is_(None))
        .order_by(Page.position, Segment.position, Segment.id)).all()
    items, active = [], False
    for seg, prob in rows:
        st = prob.status if prob is not None else "not_read"
        if state and st != state:
            continue
        badges, text_preview, text_preview_tex = [], "", ""
        if prob is not None:
            _, blockers, _ = analyze(prob.content)
            if blockers:
                badges.append("수식 변환 안 됨")
            if prob.status == "failed":
                badges.append("읽지 못했어요")
            text_preview = preview(prob.content)
            text_preview_tex = preview_tex(prob.content)
        active = active or st == "recognizing"
        items.append({"segment_id": seg.id, "page_id": seg.page_id, "number": seg.number, "bbox": list(seg.bbox),
                      "crop_url": image_url(prob.crop_ref) if prob is not None else None, "state": st,
                      "problem_id": prob.id if prob is not None else None, "preview": text_preview,
                      "preview_tex": text_preview_tex, "badges": badges,
                      "fail_reason": _fail_reason(prob) if prob is not None else None})
    return {"items": items, "poll_after_ms": POLL_MS if active else None}


def neighbors(session, owner: str, pid: str, exam_id, state) -> dict:
    p = _load(session, owner, pid)
    if exam_id is not None and exam_id != p.exam_id:
        raise ApiError(404, "NOT_FOUND")
    rows = session.execute(
        select(Problem.id, Problem.status).join(Segment, Segment.id == Problem.segment_id)
        .join(Page, Page.id == Segment.page_id)
        .where(Problem.exam_id == p.exam_id, *alive(Problem, owner))
        .order_by(Page.position, Segment.position, Segment.id)).all()
    ids = [i for i, st in rows if state is None or st == state or i == pid]  # 방금 확인한 문제 자신은 목록에 남긴다
    idx = ids.index(pid)
    return {"index": idx + 1, "total": len(ids), "prev_id": ids[idx - 1] if idx > 0 else None,
            "next_id": ids[idx + 1] if idx + 1 < len(ids) else None}


# ---------- 내용 저장과 상태 전이 ----------
def put_content(session, owner: str, pid: str, version: int, content_in, points) -> dict:
    p = _load(session, owner, pid, lock=True)
    _check_version(p, version)
    _require_editable(p)
    content = normalize_content(content_in, (p.content or {}).get("figures") or [])
    p.content, p.points, p.search_text = content, points, search_text(content)
    _bump(p)
    session.commit()
    return problem_view(session, p)


def confirm(session, owner: str, pid: str, version: int) -> dict:
    p = _load(session, owner, pid, lock=True)
    _check_version(p, version)
    if p.status == "confirmed":  # 두 번 눌러도 같은 결과
        return problem_view(session, p)
    if p.status == "recognizing":
        raise ApiError(409, "PROBLEM_BUSY")
    _, blockers, has = analyze(p.content)
    if not has:
        raise ApiError(422, "EMPTY_PROBLEM")
    if blockers:
        raise ApiError(409, "MATH_UNSUPPORTED", details=[{"path": b["path"], "message": b["message"]} for b in blockers])
    if p.recognized is not None:  # B5-4a: 고친 조각 수(숫자만). 직접 입력한 문제는 기준이 없어 건너뜀
        p.ocr_meta = {**(p.ocr_meta or {}), "edits": count_edits(p.recognized, p.content)}
    _clear_fail(p)
    p.status = "confirmed"
    _bump(p)
    touch_exam(session, p.exam_id)
    session.commit()
    return problem_view(session, p)


def reopen(session, owner: str, pid: str) -> dict:
    p = _load(session, owner, pid, lock=True)
    if p.status == "recognizing":
        raise ApiError(409, "PROBLEM_BUSY")
    if p.status != "confirmed":
        raise ApiError(409, "PROBLEM_STATE")
    p.status = "needs_review"
    _bump(p)
    touch_exam(session, p.exam_id)
    session.commit()
    return problem_view(session, p)


def revert(session, owner: str, pid: str) -> dict:
    """처음 읽은 결과로 되돌린다. 그림은 서버가 관리하므로 지금 것을 유지한다."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    if p.recognized is None:
        raise ApiError(409, "PROBLEM_STATE")
    content = copy.deepcopy(p.recognized)
    content["figures"] = (p.content or {}).get("figures") or []
    p.content, p.search_text = content, search_text(content)
    _bump(p)
    session.commit()
    return problem_view(session, p)


def reread(session, owner: str, pid: str, settings, now) -> dict:
    p = _load(session, owner, pid, lock=True)
    if p.status == "recognizing":
        raise ApiError(409, "PROBLEM_BUSY")
    consume_reads(session, owner, 2, settings.daily_read_limit, now)  # 다시 읽기는 2배 가중
    _clear_fail(p)
    p.status = "recognizing"
    _bump(p)
    enqueue(session, owner, "problem_reread", "problem", p.id)
    touch_exam(session, p.exam_id)
    session.commit()
    return problem_view(session, p)


def delete_problem(session, owner: str, pid: str, unpick: bool = False) -> None:
    """문제를 휴지통으로 보낸다. unpick이면 그 칸의 '고름'도 풀어, 목록에서 빠지고 다음 '읽기'에도 다시 읽히지 않게 한다."""
    p = _load(session, owner, pid)
    soft_delete(session, Problem, pid, owner)
    if unpick:
        seg = session.get(Segment, p.segment_id)
        if seg is not None and seg.deleted_at is None and seg.marked:
            seg.marked = False
            seg.updated_at = func.now()
    touch_exam(session, p.exam_id)
    session.commit()


# ---------- 그림 ----------
def _figure(p: Problem, fid: str) -> dict:
    for f in (p.content or {}).get("figures") or []:
        if f.get("id") == fid:
            return f
    raise ApiError(404, "NOT_FOUND")


def add_figure(session, owner: str, pid: str, bbox, placement: str, width_mm: float) -> dict:
    """그림 추가. bbox는 문제 크롭 안 비율 좌표. 크롭·정리는 작업자가 하므로 state=processing으로 돌려준다."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    figures = list((p.content or {}).get("figures") or [])
    if len(figures) >= MAX_FIGURES:
        raise ApiError(422, "REQUEST_INVALID", "한 문제에 넣을 수 있는 그림 수를 넘었어요.")
    fig = {"id": new_id("fig"), "kind": "crop", "bbox": check_bbox(bbox), "raw_ref": None, "clean_ref": None,
           "use": "clean", "placement": placement, "width_mm": width_mm, "state": "processing"}
    p.content = {**p.content, "figures": figures + [fig]}
    _bump(p)
    enqueue(session, owner, "figure_clean", "figure", fig["id"])
    session.commit()
    return problem_view(session, p)


def set_figure_region(session, owner: str, pid: str, fid: str, bbox) -> dict:
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    _figure(p, fid)
    box = check_bbox(bbox)
    figures = [dict(f, bbox=box, state="processing", use="clean") if f.get("id") == fid else f
               for f in p.content["figures"]]
    p.content = {**p.content, "figures": figures}
    _bump(p)
    enqueue(session, owner, "figure_clean", "figure", fid)  # 이미 진행 중이면 작업자가 끝에서 범위 변경을 알아채 다시 한다
    session.commit()
    return problem_view(session, p)


def set_figure_clean_level(session, owner: str, pid: str, fid: str, level: int, store=None) -> dict:
    """그림 정리 세기를 고른다(0 = 정리 안 한 원본). 이미 만들어 둔 단계 중에서 고르므로 작업은 만들지 않는다."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    fig = _figure(p, fid)
    if fig.get("state") != "ready":
        raise ApiError(409, "PROBLEM_BUSY")
    ref = (fig.get("levels") or {}).get(str(level)) if level else None
    if level and not ref:
        raise ApiError(422, "REQUEST_INVALID", "그 정리 세기는 쓸 수 없어요.")
    p.content = {**p.content, "figures": [
        dict(f, clean_level=level, clean_ref=ref, use="clean" if ref else "raw", erased=False)
        if f.get("id") == fid else f for f in p.content["figures"]]}
    _bump(p)
    session.commit()
    if fig.get("erased"):   # 단계를 바꾸면 지운 결과는 버린다(웹이 먼저 확인을 받는다)
        _drop_files(store, fig.get("clean_ref"))
    return problem_view(session, p)


def _drop_files(store, *refs) -> None:
    """저장소에서 파일을 지운다. 실패해도 요청은 성공으로 둔다(작업자의 _drop과 같은 정책)."""
    for ref in refs:
        if ref and store is not None:
            try:
                store.delete(ref)
            except StorageError:
                pass


def set_figure_erased(session, store, settings, owner: str, pid: str, fid: str, data: bytes) -> dict:
    """낙서 지우개로 지운 결과(PNG)를 그림의 정리본으로 저장한다. 원래 정리 단계(levels)는 그대로 남는다."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    fig = _figure(p, fid)
    if fig.get("state") != "ready":
        raise ApiError(409, "PROBLEM_BUSY")
    base_ref = fig.get("clean_ref")
    if not base_ref:
        raise ApiError(409, "FIGURE_NOT_CLEANED")
    base = store.get(base_ref)
    if base is None:
        raise ApiError(404, "NOT_FOUND")
    png = prepare_erased(data, base[0], settings.max_image_bytes)
    new_ref = new_id("img")
    store.put(new_ref, png, "image/png")
    try:
        p.content = {**p.content, "figures": [
            dict(f, clean_ref=new_ref, erased=True, use="clean") if f.get("id") == fid else f
            for f in p.content["figures"]]}
        _bump(p)
        session.commit()
    except Exception:
        session.rollback()
        _drop_files(store, new_ref)   # 저장은 됐는데 기록이 실패하면 방금 올린 파일을 치운다
        raise
    if fig.get("erased"):
        _drop_files(store, base_ref)  # 이전에 지운 결과는 더 쓰지 않는다
    return problem_view(session, p)


def reset_figure_erased(session, store, owner: str, pid: str, fid: str) -> dict:
    """지운 결과를 버리고 고른 정리 단계의 그림으로 되돌린다(지운 적이 없으면 아무것도 안 한다)."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    fig = _figure(p, fid)
    if fig.get("state") != "ready":
        raise ApiError(409, "PROBLEM_BUSY")
    if not fig.get("erased"):
        return problem_view(session, p)
    level = fig.get("clean_level") or 0
    ref = (fig.get("levels") or {}).get(str(level)) if level else None
    p.content = {**p.content, "figures": [
        dict(f, clean_ref=ref, use="clean" if ref else "raw", erased=False) if f.get("id") == fid else f
        for f in p.content["figures"]]}
    _bump(p)
    session.commit()
    _drop_files(store, fig.get("clean_ref"))
    return problem_view(session, p)


MAX_REMOVED_FIGURES = 10   # 되살릴 수 있게 보관하는 지운 그림 수(문제당)


def delete_figure(session, owner: str, pid: str, fid: str) -> dict:
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    fig = _figure(p, fid)
    # 파일은 지우지 않고 그림 정보만 보관해 두면 언제든 되살릴 수 있다.
    # content 안에 두면 자동 저장이 content를 새로 만들 때 사라지므로 ocr_meta에 둔다.
    meta = dict(p.ocr_meta or {})
    removed = [dict(fig, removed_at=datetime.now(timezone.utc).isoformat())] + [
        r for r in meta.get("removed_figures") or [] if r.get("id") != fid]
    p.ocr_meta = {**meta, "removed_figures": removed[:MAX_REMOVED_FIGURES]}
    p.content = {**p.content, "figures": [f for f in p.content["figures"] if f.get("id") != fid]}
    p.search_text = search_text(p.content)
    _bump(p)
    session.commit()
    return problem_view(session, p)


def restore_figure(session, owner: str, pid: str, fid: str) -> dict:
    """지운 그림을 되살린다(보관 중인 것만). 한 문제의 그림 수 한도는 그대로 지킨다."""
    p = _load(session, owner, pid, lock=True)
    _require_editable(p)
    meta = dict(p.ocr_meta or {})
    removed = list(meta.get("removed_figures") or [])
    fig = next((r for r in removed if r.get("id") == fid), None)
    if fig is None:
        raise ApiError(404, "NOT_FOUND")
    figures = list((p.content or {}).get("figures") or [])
    if len(figures) >= MAX_FIGURES:
        raise ApiError(422, "REQUEST_INVALID", "한 문제에 넣을 수 있는 그림 수를 넘었어요.")
    fig = {k: v for k, v in fig.items() if k != "removed_at"}
    p.ocr_meta = {**meta, "removed_figures": [r for r in removed if r.get("id") != fid]}
    p.content = {**p.content, "figures": figures + [fig]}
    p.search_text = search_text(p.content)
    _bump(p)
    if fig.get("state") == "processing":  # 정리 도중 지웠다면 그 작업은 버려졌으므로 다시 시킨다
        enqueue(session, owner, "figure_clean", "figure", fid)
    session.commit()
    return problem_view(session, p)
