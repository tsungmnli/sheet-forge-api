"""홈의 할 일과 학생 목록 (REST 설계 5.1)."""
from sqlalchemy import func, select

from ..db.models import Exam, Page, Problem, Segment, Worksheet


def _problems(owner: str) -> tuple:
    """내 것이고 휴지통에 없는 문제(시험지·사진·칸도 살아 있어야 함)."""
    return (Problem.owner_id == owner, Problem.deleted_at.is_(None), Exam.deleted_at.is_(None),
            Page.deleted_at.is_(None), Segment.deleted_at.is_(None))


def _joined(stmt):
    return (stmt.select_from(Problem).join(Exam, Exam.id == Problem.exam_id)
            .join(Segment, Segment.id == Problem.segment_id).join(Page, Page.id == Segment.page_id))


def home(session, owner: str) -> dict:
    counts = dict(session.execute(_joined(select(Problem.status, func.count(Problem.id)))
                                  .where(*_problems(owner)).group_by(Problem.status)).all())
    nxt = session.execute(_joined(select(Problem.exam_id, Problem.id))
                          .where(*_problems(owner), Problem.status == "needs_review")
                          .order_by(Exam.updated_at.desc(), Exam.id, Page.position, Segment.position, Segment.id)
                          .limit(1)).first()
    return {"todo": {"needs_review": counts.get("needs_review", 0), "recognizing": counts.get("recognizing", 0),
                     "failed": counts.get("failed", 0),
                     "next_problem": {"exam_id": nxt[0], "problem_id": nxt[1]} if nxt else None}}


def students(session, owner: str) -> dict:
    """시험지·문제지에 쓰인 학생 이름(휴지통 제외, 중복 없이 가나다 순). 학생 엔티티는 아직 없다."""
    names: set[str] = set()
    for model in (Exam, Worksheet):
        names.update(session.scalars(select(model.student).where(
            model.owner_id == owner, model.deleted_at.is_(None), model.student.is_not(None), model.student != "").distinct()))
    return {"items": sorted(names)}
