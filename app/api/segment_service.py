"""문제 칸(segments) 서비스: 고르기·한꺼번에 고르기·칸 고치기 (웹 REST API 설계 5.3). 커밋은 여기서 한다."""
from sqlalchemy import func, select, update

from ..db.ids import new_id
from ..db.models import Page, Problem, Segment
from .errors import ApiError
from .repo import alive
from .web_service import _require_exam, touch_exam


def check_bbox(b) -> list:
    """[x0,y0,x1,y1] 비율(0~1). 너무 작거나 뒤집힌 상자는 거절한다."""
    if len(b) != 4 or any(not (0.0 <= v <= 1.0) for v in b) or b[2] - b[0] < 0.01 or b[3] - b[1] < 0.01:
        raise ApiError(422, "REQUEST_INVALID", "칸 범위가 올바르지 않아요.")
    return [float(v) for v in b]


def has_problem(segment_id):
    """이 칸에 살아 있는 문제가 있는가(조건식)."""
    return select(Problem.id).where(Problem.segment_id == segment_id, Problem.deleted_at.is_(None)).exists()


def seg_out(s) -> dict:
    return {"id": s.id, "bbox": list(s.bbox), "number": s.number, "marked": s.marked}


def _page(session, owner: str, page_id: str) -> Page:
    page = session.execute(select(Page).where(Page.id == page_id, *alive(Page, owner))).scalar_one_or_none()
    if page is None:
        raise ApiError(404, "NOT_FOUND")
    return page


def picked_in_page(session, page_id: str) -> int:
    return session.execute(select(func.count(Segment.id)).where(
        Segment.page_id == page_id, Segment.deleted_at.is_(None), Segment.marked.is_(True))).scalar_one()


def picked_in_exam(session, exam_id: str) -> int:
    return session.execute(select(func.count(Segment.id)).where(
        Segment.exam_id == exam_id, Segment.deleted_at.is_(None), Segment.marked.is_(True))).scalar_one()


def set_marked(session, owner: str, page_id: str, segment_id: str, marked: bool) -> dict:
    page = _page(session, owner, page_id)
    seg = session.execute(select(Segment).where(Segment.id == segment_id, Segment.page_id == page_id,
                                                *alive(Segment, owner))).scalar_one_or_none()
    if seg is None:
        raise ApiError(404, "NOT_FOUND")
    if seg.marked and not marked and session.execute(select(has_problem(seg.id))).scalar():
        raise ApiError(409, "SEGMENT_HAS_PROBLEM")
    if seg.marked != marked:
        seg.marked = marked
        seg.updated_at = func.now()
        touch_exam(session, page.exam_id)
        session.commit()
    return {"segment": seg_out(seg), "picked_count": picked_in_page(session, page_id),
            "exam_picked_count": picked_in_exam(session, page.exam_id)}


def mark_many(session, owner: str, exam_id: str, marked: bool, segment_ids, page_id) -> dict:
    """범위: segment_ids → 그 칸들, page_id → 그 사진 전부, 둘 다 없으면 시험지 전부. 읽은 문제가 있는 칸은 해제하지 않고 skipped로 센다."""
    _require_exam(session, owner, exam_id)
    if page_id is not None:
        page = _page(session, owner, page_id)
        if page.exam_id != exam_id:
            raise ApiError(404, "NOT_FOUND")
    conds = [Segment.exam_id == exam_id, *alive(Segment, owner)]
    if segment_ids is not None:
        conds.append(Segment.id.in_(segment_ids))
    if page_id is not None:
        conds.append(Segment.page_id == page_id)
    skipped = 0
    if marked:
        stmt = update(Segment).where(*conds, Segment.marked.is_(False)).values(marked=True, updated_at=func.now())
    else:
        skipped = session.execute(select(func.count(Segment.id)).where(
            *conds, Segment.marked.is_(True), has_problem(Segment.id))).scalar_one()
        stmt = (update(Segment).where(*conds, Segment.marked.is_(True), ~has_problem(Segment.id))
                .values(marked=False, updated_at=func.now()))
    changed = len(session.execute(stmt.returning(Segment.id).execution_options(synchronize_session=False)).all())
    if changed:
        touch_exam(session, exam_id)
    session.commit()
    return {"changed": changed, "skipped": int(skipped), "picked_count": picked_in_exam(session, exam_id)}


def replace_segments(session, owner: str, page_id: str, items: list) -> dict:
    """칸 전체 목록으로 교체. id가 있는 칸은 유지(marked·문제 보존), 없는 칸은 추가, 빠진 칸은 삭제(읽은 문제가 있으면 409)."""
    page = _page(session, owner, page_id)
    existing = {s.id: s for s in session.execute(select(Segment).where(
        Segment.page_id == page_id, *alive(Segment, owner))).scalars()}
    kept = [i.id for i in items if i.id]
    if len(set(kept)) != len(kept) or any(k not in existing for k in kept):
        raise ApiError(422, "REQUEST_INVALID", "칸 목록이 달라졌어요. 화면을 새로 불러와 주세요.")
    boxes = [check_bbox(i.bbox) for i in items]
    removed = [sid for sid in existing if sid not in set(kept)]
    if removed and session.execute(select(func.count(Problem.id)).where(
            Problem.segment_id.in_(removed), Problem.deleted_at.is_(None))).scalar_one():
        raise ApiError(409, "SEGMENT_HAS_PROBLEM")
    for sid in removed:
        s = existing[sid]
        s.marked, s.deleted_at, s.deleted_with = False, func.now(), "edit"  # 페이지 복구 때 되살아나지 않게 "edit"
    for pos, (item, box) in enumerate(zip(items, boxes)):
        if item.id:
            s = existing[item.id]
            s.bbox, s.number, s.position = box, item.number, pos
        else:
            session.add(Segment(id=new_id("seg"), owner_id=owner, page_id=page_id, exam_id=page.exam_id,
                                position=pos, bbox=box, number=item.number))
    touch_exam(session, page.exam_id)
    session.commit()
    segs = session.execute(select(Segment).where(Segment.page_id == page_id, Segment.deleted_at.is_(None))
                           .order_by(Segment.position, Segment.id)).scalars().all()
    return {"segments": [seg_out(s) for s in segs], "picked_count": picked_in_page(session, page_id)}
