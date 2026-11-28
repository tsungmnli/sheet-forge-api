"""문제 담기 패널의 검색과 만들기 전 점검 (웹 REST API 설계 5.6·5.7). 파일을 만들거나 이미지를 열지 않는다."""
from collections import Counter

from sqlalchemy import select, tuple_

from ..db.models import Exam, Problem, Segment, WorksheetItem
from ..export.hwpx import ExportPreset, PresetError, plan_layout
from .errors import ApiError
from .pagination import decode_cursor, encode_cursor
from .problem_logic import preview
from .repo import alive
from .serialize import image_url
from .web_service import _like
from .worksheet_service import _load


def figure_missing(content: dict) -> bool:
    """쓰기로 한 그림 파일(정리본/원본)이 비어 있는 그림이 있는가."""
    for f in (content or {}).get("figures") or []:
        ref = f.get("clean_ref") if f.get("use", "clean") == "clean" else f.get("raw_ref")
        if not ref:
            return True
    return False


def search_problems(session, owner: str, status, student, exam_id, q, worksheet_id, limit: int, cursor) -> dict:
    in_ws = set()
    if worksheet_id is not None:
        ws = _load(session, owner, worksheet_id)
        in_ws = set(session.scalars(select(WorksheetItem.problem_id).where(WorksheetItem.worksheet_id == ws.id)))
    stmt = (select(Problem, Exam.id, Exam.title, Exam.student, Segment.number)
            .join(Exam, Exam.id == Problem.exam_id).join(Segment, Segment.id == Problem.segment_id)
            .where(*alive(Problem, owner), Exam.deleted_at.is_(None)))
    if status:
        stmt = stmt.where(Problem.status == status)
    if student:
        stmt = stmt.where(Exam.student == student)
    if exam_id:
        stmt = stmt.where(Problem.exam_id == exam_id)
    if q:
        stmt = stmt.where(Problem.search_text.ilike(f"%{_like(q)}%", escape="\\"))
    if cursor:
        ts, id_ = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Problem.updated_at, Problem.id) < tuple_(ts, id_))
    rows = session.execute(stmt.order_by(Problem.updated_at.desc(), Problem.id.desc()).limit(limit + 1)).all()
    page_rows, more = rows[:limit], len(rows) > limit
    items = [{"id": p.id, "exam": {"id": eid, "title": etitle or "", "student": estudent or ""}, "number": num,
              "status": p.status, "preview": preview(p.content or {}), "crop_url": image_url(p.crop_ref),
              "in_worksheet": p.id in in_ws} for p, eid, etitle, estudent, num in page_rows]
    next_cursor = encode_cursor(page_rows[-1][0].updated_at, page_rows[-1][0].id) if more and page_rows else None
    return {"items": items, "next_cursor": next_cursor}


def check_worksheet(session, owner: str, wid: str) -> dict:
    ws = _load(session, owner, wid)
    items = []

    def add(code, severity, message, **extra):
        items.append({"code": code, "severity": severity, "message": message, **extra})

    try:
        plan_layout(ExportPreset.from_dict(ws.preset))
    except PresetError:
        add("PRESET_INVALID", "error", "모양 값이 올바르지 않아요. 모양을 다시 정해 주세요.")
    pairs = session.execute(select(Problem, Segment.number)
                            .join(WorksheetItem, WorksheetItem.problem_id == Problem.id)
                            .outerjoin(Segment, Segment.id == Problem.segment_id)
                            .where(WorksheetItem.worksheet_id == ws.id).order_by(WorksheetItem.position)).all()
    rows = [p for p, _ in pairs]
    source_numbers = {p.id: (number or "").strip() for p, number in pairs}
    deleted = [p for p in rows if p.deleted_at is not None]
    live = [p for p in rows if p.deleted_at is None]
    unconfirmed = [p for p in live if p.status != "confirmed"]
    exportable = live if ws.unconfirmed_policy == "fail" else [p for p in live if p.status == "confirmed"]
    if not exportable and not unconfirmed:
        add("EMPTY_EXPORT", "error", "문제지에 담긴 문제가 없어요. 문제를 먼저 담아 주세요.")
    elif not exportable:
        add("EMPTY_EXPORT", "error", "만들 수 있는 문제가 없어요. 문제 확인을 먼저 끝내 주세요.")
    if unconfirmed:
        ids = [p.id for p in unconfirmed]
        if ws.unconfirmed_policy == "fail":
            add("UNCONFIRMED_BLOCKS", "error",
                f"확인이 안 끝난 문제가 {len(ids)}개 있어요. '멈추기'로 되어 있어서 만들 수 없어요.", problem_ids=ids)
        else:
            add("UNCONFIRMED", "warn", f"확인이 안 끝난 문제가 {len(ids)}개 있어요. 지금은 빼고 만들어요.",
                problem_ids=ids)
    if deleted:
        add("DELETED", "warn", f"지운 문제가 {len(deleted)}개 있어요. 파일에는 들어가지 않아요.",
            problem_ids=[p.id for p in deleted])
    if ((ws.preset or {}).get("numbering") or {}).get("mode") == "source":
        no_number = [p.id for p in exportable if not source_numbers[p.id]]
        if no_number:
            add("SOURCE_NUMBER_MISSING", "error",
                f"원래 번호가 없는 문제가 {len(no_number)}개 있어요. 문항 번호를 '순서대로'로 바꾸거나 그 문제를 빼 주세요.",
                problem_ids=no_number)
        counts = Counter(source_numbers[p.id] for p in exportable if source_numbers[p.id])
        repeated = [p.id for p in exportable if counts[source_numbers[p.id]] > 1]
        if repeated:
            add("SOURCE_NUMBER_DUPLICATE", "warn",
                f"원래 번호가 겹치는 문제가 {len(repeated)}개 있어요. 파일에도 같은 번호로 들어가요.",
                problem_ids=repeated)
    if ((ws.preset or {}).get("source") or {}).get("mode") in ("exam", "problem") and exportable:
        exam_ids = {p.exam_id for p in exportable}
        labels = dict(session.execute(select(Exam.id, Exam.source_label).where(Exam.id.in_(exam_ids))).all())
        no_label = [p.id for p in exportable if not (labels.get(p.exam_id) or "").strip()]
        if no_label:
            n_exams = len({p.exam_id for p in exportable if p.id in set(no_label)})
            add("SOURCE_LABEL_MISSING", "warn",
                f"출처를 적지 않은 시험지가 {n_exams}개 있어요. 그 시험지의 문제에는 출처가 찍히지 않아요.",
                problem_ids=no_label)
    for p in exportable:
        if figure_missing(p.content):
            add("FIGURE_MISSING", "warn", "그림이 없는 문제가 있어요", problem_id=p.id)
    return {"ready": not any(i["severity"] == "error" for i in items), "items": items}
