"""시험지·사진 서비스 함수 (웹 REST API 설계 5.2·5.3). 커밋은 여기서 한다."""
from sqlalchemy import func, or_, select, tuple_, update

from ..db.ids import new_id
from ..db.models import Exam, Page, Problem, Segment
from ..jobs import enqueue
from .errors import ApiError
from .pagination import decode_cursor, encode_cursor
from .repo import alive, soft_delete
from .serialize import POLL_MS, exam_out, is_active, page_detail, page_out


def _exam_query(owner: str):
    pc = select(func.count(Page.id)).where(Page.exam_id == Exam.id, Page.deleted_at.is_(None)).scalar_subquery()
    pk = select(func.count(Segment.id)).where(Segment.exam_id == Exam.id, Segment.deleted_at.is_(None),
                                              Segment.marked.is_(True)).scalar_subquery()
    ac = select(func.count(Page.id)).where(Page.exam_id == Exam.id, Page.deleted_at.is_(None),
                                           Page.processing["state"].astext.in_(["queued", "running"])).scalar_subquery()
    return select(Exam, pc.label("page_count"), pk.label("picked_count"), ac.label("active_count")).where(*alive(Exam, owner))


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _picked_sq():
    return select(func.count(Segment.id)).where(Segment.page_id == Page.id, Segment.deleted_at.is_(None),
                                                Segment.marked.is_(True)).scalar_subquery()


def _require_exam(session, owner: str, exam_id: str) -> None:
    if session.execute(select(Exam.id).where(Exam.id == exam_id, *alive(Exam, owner))).first() is None:
        raise ApiError(404, "NOT_FOUND")


def touch_exam(session, exam_id: str) -> None:
    session.execute(update(Exam).where(Exam.id == exam_id).values(updated_at=func.now()))


# ---------- 시험지 ----------
def get_exam_view(session, owner: str, exam_id: str) -> dict:
    row = session.execute(_exam_query(owner).where(Exam.id == exam_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND")
    return exam_out(*row)


def list_exams(session, owner: str, student, q, limit: int, cursor) -> dict:
    stmt = _exam_query(owner)
    if student:
        stmt = stmt.where(Exam.student == student)
    if q:
        like = f"%{_like(q)}%"
        stmt = stmt.where(or_(Exam.title.ilike(like, escape="\\"), Exam.student.ilike(like, escape="\\")))
    if cursor:
        ts, id_ = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Exam.updated_at, Exam.id) < tuple_(ts, id_))
    rows = session.execute(stmt.order_by(Exam.updated_at.desc(), Exam.id.desc()).limit(limit + 1)).all()
    page_rows, more = rows[:limit], len(rows) > limit
    items = [exam_out(*r) for r in page_rows]
    next_cursor = encode_cursor(page_rows[-1][0].updated_at, page_rows[-1][0].id) if more and page_rows else None
    return {"items": items, "next_cursor": next_cursor}


def _trash_problems(session, condition, parent_id: str) -> None:
    """살아 있는 문제를 휴지통으로 보내고 deleted_with에 부모 id를 남긴다. 따로 지운 문제(deleted_at이 이미 있음)는 건드리지 않아
    복구 때 같이 지운 것만 되살릴 수 있다."""
    session.execute(update(Problem).where(condition, Problem.deleted_at.is_(None))
                    .values(deleted_at=func.now(), deleted_with=parent_id, version=Problem.version + 1, updated_at=func.now()))


def delete_exam(session, owner: str, exam_id: str) -> None:
    soft_delete(session, Exam, exam_id, owner)
    for model in (Page, Segment):  # 함께 지운 것만 복구할 수 있게 deleted_with에 시험지 id를 남긴다
        session.execute(update(model).where(model.exam_id == exam_id, model.deleted_at.is_(None))
                        .values(deleted_at=func.now(), deleted_with=exam_id))
    _trash_problems(session, Problem.exam_id == exam_id, exam_id)
    session.commit()


# ---------- 사진 ----------
def create_pages(session, store, settings, owner: str, exam_id: str, prepared: list) -> list:
    """prepared: [(bytes, content_type)]. 저장소에 먼저 올리고, DB 행·작업을 한 트랜잭션으로 만든다."""
    _require_exam(session, owner, exam_id)
    count, maxpos = session.execute(select(func.count(Page.id), func.max(Page.position)).where(
        Page.exam_id == exam_id, Page.deleted_at.is_(None))).one()
    if count + len(prepared) > settings.max_pages_per_exam:
        raise ApiError(422, "TOO_MANY_PAGES")
    pos = (maxpos if maxpos is not None else -1) + 1
    refs, pages = [], []
    try:
        for data, content_type in prepared:
            ref = new_id("img")
            store.put(ref, data, content_type)
            refs.append(ref)
            page = Page(id=new_id("page"), owner_id=owner, exam_id=exam_id, position=pos, original_ref=ref,
                        byte_size=len(data), processing={"state": "queued", "step": "correcting", "message": None})
            pos += 1
            session.add(page)
            pages.append(page)
        session.flush()
        for page in pages:
            enqueue(session, owner, "page_process", "page", page.id)
        touch_exam(session, exam_id)
        session.commit()
    except Exception:
        session.rollback()
        for ref in refs:  # 올라간 객체는 최대한 치운다(남아도 정기 정리 대상)
            try:
                store.delete(ref)
            except Exception:  # noqa: BLE001
                pass
        raise
    return pages


def list_pages(session, owner: str, exam_id: str) -> dict:
    _require_exam(session, owner, exam_id)
    rows = session.execute(select(Page, _picked_sq().label("picked")).where(
        Page.exam_id == exam_id, *alive(Page, owner)).order_by(Page.position, Page.id)).all()
    return {"items": [page_out(p, k) for p, k in rows],
            "poll_after_ms": POLL_MS if any(is_active(p.processing) for p, _ in rows) else None}


def get_page_detail(session, owner: str, page_id: str) -> dict:
    row = session.execute(select(Page, _picked_sq().label("picked")).where(
        Page.id == page_id, *alive(Page, owner))).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND")
    page, picked = row
    segs = session.execute(select(Segment).where(Segment.page_id == page_id, Segment.deleted_at.is_(None))
                           .order_by(Segment.position, Segment.id)).scalars().all()
    return page_detail(page, picked, segs)


def reorder_pages(session, owner: str, exam_id: str, page_ids: list) -> dict:
    _require_exam(session, owner, exam_id)
    pages = session.execute(select(Page).where(Page.exam_id == exam_id, *alive(Page, owner))).scalars().all()
    by_id = {p.id: p for p in pages}
    if len(set(page_ids)) != len(page_ids) or set(page_ids) != set(by_id):
        raise ApiError(422, "REQUEST_INVALID", "사진 목록이 달라졌어요. 화면을 새로 불러와 주세요.")
    for i, pid in enumerate(page_ids):
        by_id[pid].position = i
    touch_exam(session, exam_id)
    session.commit()
    return list_pages(session, owner, exam_id)


def delete_page(session, owner: str, page_id: str) -> None:
    exam_id = session.execute(select(Page.exam_id).where(Page.id == page_id, *alive(Page, owner))).scalar_one_or_none()
    if exam_id is None:
        raise ApiError(404, "NOT_FOUND")
    soft_delete(session, Page, page_id, owner)
    session.execute(update(Segment).where(Segment.page_id == page_id, Segment.deleted_at.is_(None))
                    .values(deleted_at=func.now(), deleted_with=page_id))
    _trash_problems(session, Problem.segment_id.in_(select(Segment.id).where(Segment.page_id == page_id)), page_id)
    remaining = session.execute(select(Page).where(Page.exam_id == exam_id, *alive(Page, owner))
                                .order_by(Page.position, Page.id)).scalars().all()
    for i, p in enumerate(remaining):  # 순서를 0부터 다시 이어 붙인다
        p.position = i
    touch_exam(session, exam_id)
    session.commit()
