"""문제지 → 내보내기 입력 (REST 설계 5.7, export 설계 A5의 problem_ids 경로).

문제지에 담긴 문제를 담은 순서대로 읽어 라이브러리가 받는 dict 목록으로 만든다. 읽기만 한다(읽기 전용 세션 가능).
삭제된 문제는 뺀다. 확인 안 된 문제의 제외·번호는 라이브러리가 preset.on_unconfirmed에 따라 처리한다.
"""
from sqlalchemy import select

from ..db.models import Problem, Segment, Worksheet, WorksheetItem
from .errors import ApiError
from .repo import alive


def load_worksheet(session, owner: str, wid: str) -> Worksheet:
    ws = session.execute(select(Worksheet).where(Worksheet.id == wid, *alive(Worksheet, owner))).scalar_one_or_none()
    if ws is None:
        raise ApiError(404, "NOT_FOUND")
    return ws


def load_problems(session, ws: Worksheet) -> list:
    """담은 순서대로 [{id, status, content, exam_id, source_number}]. 삭제된 문제는 빠진다."""
    rows = session.execute(select(Problem, Segment.number)
                           .join(WorksheetItem, WorksheetItem.problem_id == Problem.id)
                           .outerjoin(Segment, Segment.id == Problem.segment_id)
                           .where(WorksheetItem.worksheet_id == ws.id, Problem.deleted_at.is_(None))
                           .order_by(WorksheetItem.position)).all()
    return [{"id": p.id, "status": p.status, "content": p.content or {}, "exam_id": p.exam_id,
             "source_number": number} for p, number in rows]
