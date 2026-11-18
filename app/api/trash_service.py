"""휴지통 목록 (REST 설계 5.9). 따로 지운 것(deleted_with 없음)만 보여 준다.
시험지를 지울 때 같이 지워진 사진·문제는 시험지와 함께 복구되므로 목록에 따로 나오지 않는다.
"""
from datetime import timedelta

from sqlalchemy import func, select, update

from ..db.models import Exam, Page, Problem, Segment, Worksheet
from .errors import ApiError
from .problem_logic import preview
from .serialize import iso

TYPES = ("exam", "page", "problem", "worksheet")


def _where(model, owner: str) -> tuple:
    return (model.owner_id == owner, model.deleted_at.is_not(None), model.deleted_with.is_(None))


def list_trash(session, owner: str, type_, limit: int, retention_days: int) -> dict:
    found = []   # (deleted_at, type, id, label)
    if type_ in (None, "exam"):
        for e in session.scalars(select(Exam).where(*_where(Exam, owner)).order_by(Exam.deleted_at.desc(), Exam.id).limit(limit)):
            found.append((e.deleted_at, "exam", e.id, e.title or (f"{e.student} 시험지" if e.student else "시험지")))
    if type_ in (None, "page"):
        rows = session.execute(select(Page, Exam.title).join(Exam, Exam.id == Page.exam_id).where(*_where(Page, owner))
                               .order_by(Page.deleted_at.desc(), Page.id).limit(limit)).all()
        for p, title in rows:
            found.append((p.deleted_at, "page", p.id, f"{title or '시험지'}의 사진 {p.position + 1}"))
    if type_ in (None, "problem"):
        for p in session.scalars(select(Problem).where(*_where(Problem, owner)).order_by(Problem.deleted_at.desc(), Problem.id).limit(limit)):
            found.append((p.deleted_at, "problem", p.id, preview(p.content or {}, 40) or "내용 없는 문제"))
    if type_ in (None, "worksheet"):
        for w in session.scalars(select(Worksheet).where(*_where(Worksheet, owner)).order_by(Worksheet.deleted_at.desc(), Worksheet.id).limit(limit)):
            found.append((w.deleted_at, "worksheet", w.id, w.title or "문제지"))
    found.sort(key=lambda r: r[2])                       # 같은 시각이면 id 순
    found.sort(key=lambda r: r[0], reverse=True)         # 최근에 지운 것이 먼저
    return {"items": [{"type": t, "id": i, "label": label, "deleted_at": iso(at),
                       "purge_at": iso(at + timedelta(days=retention_days))} for at, t, i, label in found[:limit]]}


# ---------- 복구 ----------
_MODELS = {"exam": Exam, "page": Page, "problem": Problem, "worksheet": Worksheet}


def _revive(session, model, *conds) -> int:
    """휴지통에 있는 행을 되살린다(deleted_at·deleted_with 비움). 되살린 행 수를 돌려준다."""
    r = session.execute(update(model).where(*conds, model.deleted_at.is_not(None))
                        .values(deleted_at=None, deleted_with=None, version=model.version + 1, updated_at=func.now()))
    return r.rowcount


def _alive(session, model, obj_id) -> bool:
    return session.execute(select(model.id).where(model.id == obj_id, model.deleted_at.is_(None))).first() is not None


def restore(session, owner: str, type_: str, obj_id: str) -> dict:
    """복구한다. 같이 지워진 것(deleted_with가 이 항목 id)만 함께 되살리고, 따로 지운 것은 그대로 둔다.
    부모(시험지·사진·칸)가 휴지통에 있으면 409 PARENT_IN_TRASH. 없거나 남의 것이거나 휴지통에 없으면 404."""
    model = _MODELS.get(type_)
    if model is None:
        raise ApiError(404, "NOT_FOUND")
    obj = session.execute(select(model).where(model.id == obj_id, model.owner_id == owner,
                                              model.deleted_at.is_not(None))).scalar_one_or_none()
    if obj is None:
        raise ApiError(404, "NOT_FOUND")
    restored = {type_: 1}
    exam_id = None
    if type_ == "exam":
        for key, m in (("page", Page), ("segment", Segment), ("problem", Problem)):
            restored[key] = _revive(session, m, m.deleted_with == obj_id)
        exam_id = obj_id
    elif type_ == "page":
        exam_id = obj.exam_id
        if not _alive(session, Exam, exam_id):
            raise ApiError(409, "PARENT_IN_TRASH")
        last = session.execute(select(func.max(Page.position)).where(Page.exam_id == exam_id, Page.deleted_at.is_(None))).scalar_one()
        session.execute(update(Page).where(Page.id == obj_id).values(position=(last if last is not None else -1) + 1))
        for key, m in (("segment", Segment), ("problem", Problem)):
            restored[key] = _revive(session, m, m.deleted_with == obj_id)
    elif type_ == "problem":
        exam_id = obj.exam_id
        seg = session.get(Segment, obj.segment_id)
        if seg is None or seg.deleted_at is not None or not _alive(session, Page, seg.page_id) or not _alive(session, Exam, exam_id):
            raise ApiError(409, "PARENT_IN_TRASH")
        if session.execute(select(Problem.id).where(Problem.segment_id == seg.id, Problem.deleted_at.is_(None))).first():
            raise ApiError(409, "SEGMENT_HAS_PROBLEM", "이 칸은 이미 다시 읽은 문제가 있어요. 그 문제를 지우면 이 문제를 복구할 수 있어요.")
    restored[type_] = _revive(session, model, model.id == obj_id)
    if type_ == "problem" and not seg.marked:
        seg.marked = True
        seg.updated_at = func.now()
    if exam_id and type_ != "exam":
        session.execute(update(Exam).where(Exam.id == exam_id).values(updated_at=func.now()))
    session.commit()
    return {"type": type_, "id": obj_id, "restored": restored}
