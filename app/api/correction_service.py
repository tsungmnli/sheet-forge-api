"""사진 다시 보정하기 (pages.correction). 커밋은 여기서 한다.

설정을 저장하고 칸을 비운 뒤 page_process를 다시 쌓는다. 작업자가 그 설정으로 보정하고 칸을 새로 나눈다.
옮긴 문제가 있는 사진은 칸 좌표의 뜻이 바뀌므로 막는다(409 PAGE_HAS_PROBLEMS).
"""
from sqlalchemy import func, select

from ..db.models import Problem, Segment
from ..jobs import enqueue
from .errors import ApiError
from .repo import alive
from .segment_service import _page
from .serialize import is_active
from .web_service import get_page_detail, touch_exam

MIN_AREA = 0.05  # 꼭짓점 사각형의 최소 넓이(사진 대비). 너무 작으면 실수로 본다


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def check_corners(corners) -> list:
    """꼭짓점 4개 [[x, y]] 비율(0~1), 순서는 왼위·오른위·오른아래·왼아래. 볼록하고 충분히 커야 한다."""
    bad = ApiError(422, "REQUEST_INVALID", "모서리 위치가 올바르지 않아요.")
    if corners is None or len(corners) != 4 or any(len(p) != 2 for p in corners):
        raise bad
    pts = [(float(x), float(y)) for x, y in corners]
    if any(not (0.0 <= v <= 1.0) for p in pts for v in p):
        raise bad
    turns = [_cross(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4)]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        raise bad  # 꼬였거나 오목한 사각형
    area = abs(sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))) / 2
    if area < MIN_AREA:
        raise bad
    return [[round(x, 5), round(y, 5)] for x, y in pts]


def recorrect(session, owner: str, page_id: str, mode: str, rotation: int, corners, angle: float = 0.0) -> dict:
    page = _page(session, owner, page_id)
    if is_active(page.processing):
        raise ApiError(409, "PAGE_BUSY")
    if page.original_ref is None:
        raise ApiError(409, "ORIGINAL_EXPIRED")
    seg_ids = select(Segment.id).where(Segment.page_id == page.id, Segment.deleted_at.is_(None))
    if session.execute(select(func.count(Problem.id)).where(
            Problem.segment_id.in_(seg_ids), Problem.deleted_at.is_(None))).scalar_one():
        raise ApiError(409, "PAGE_HAS_PROBLEMS")
    used = check_corners(corners) if mode == "manual" else None
    for s in session.execute(select(Segment).where(Segment.page_id == page.id, *alive(Segment, owner))).scalars():
        s.marked, s.deleted_at, s.deleted_with = False, func.now(), "edit"  # 페이지 복구 때 되살아나지 않게
    angle = round(float(angle), 2)
    page.correction = {"mode": mode, "rotation": rotation, "angle": angle, "corners": used, "applied": None}
    page.processing = {"state": "queued", "step": "correcting", "message": None}
    page.updated_at = func.now()
    session.flush()
    enqueue(session, owner, "page_process", "page", page.id)
    touch_exam(session, page.exam_id)
    session.commit()
    return get_page_detail(session, owner, page.id)
