"""문제지 (웹 REST API 설계 5.7): 만들기·조회·수정·담기·순서·복제·삭제, 번호 계산.

번호는 내보내기(exporter)와 같은 규칙이다: 삭제된 문제는 번호가 없고, unconfirmed_policy="skip"이면
확인 완료가 아닌 문제도 번호가 없다(내보내기에서 빠지므로 세지 않는다).
numbering.mode="source"면 새로 매기지 않고 원래 번호를 그대로 쓴다(원래 번호가 없으면 번호 없음).
커밋은 이 모듈의 공개 함수가 한다.
"""
import copy

from sqlalchemy import delete, func, select, tuple_, update

from ..db.ids import new_id
from ..db.models import Exam, Page, Problem, Segment, Worksheet, WorksheetItem
from ..export.hwpx import ExportPreset, PresetError, plan_layout
from .errors import ApiError
from .me_service import default_preset_value
from .pagination import decode_cursor, encode_cursor
from .preset_service import get_preset_value
from .problem_logic import preview, preview_tex
from .repo import alive, soft_delete, update_versioned
from .serialize import image_url, iso

def assign_numbers(flags: list, preset: dict, policy: str, sources: list | None = None) -> list:
    """flags = [(삭제됨, 상태), ...] 순서대로 번호(문자열) 또는 None을 돌려준다.
    sources는 flags와 같은 순서의 원래 번호 목록이며 mode="source"일 때만 쓴다."""
    numbering = (preset or {}).get("numbering") or {}
    if numbering.get("mode") == "source":
        sources = sources or [None] * len(flags)
        return [None if deleted or (policy != "fail" and status != "confirmed") else ((src or "").strip() or None)
                for (deleted, status), src in zip(flags, sources)]
    fmt = numbering.get("format") or "{n:02d}"
    n = numbering.get("start", 1)
    out = []
    for deleted, status in flags:
        if deleted or (policy != "fail" and status != "confirmed"):
            out.append(None)
            continue
        try:
            out.append(fmt.format(n=n))
        except (KeyError, IndexError, ValueError):
            out.append(str(n))
        n += 1
    return out


def _dedupe(ids: list) -> list:
    return list(dict.fromkeys(ids))


def _load(session, owner: str, wid: str, lock: bool = False) -> Worksheet:
    stmt = select(Worksheet).where(Worksheet.id == wid, *alive(Worksheet, owner))
    if lock:
        stmt = stmt.with_for_update()
    ws = session.execute(stmt).scalar_one_or_none()
    if ws is None:
        raise ApiError(404, "NOT_FOUND")
    return ws


def _require_problems(session, owner: str, ids: list) -> None:
    """새로 담을 문제는 내 것이고 휴지통에 없어야 한다."""
    if not ids:
        return
    found = set(session.scalars(select(Problem.id).where(Problem.id.in_(ids), *alive(Problem, owner))))
    if set(ids) - found:
        raise ApiError(404, "NOT_FOUND")


def _check_limit(count: int, settings) -> None:
    if count > settings.max_problems:
        raise ApiError(413, "TOO_MANY_PROBLEMS")


def _current_ids(session, wid: str) -> list:
    return list(session.scalars(select(WorksheetItem.problem_id).where(WorksheetItem.worksheet_id == wid)
                                .order_by(WorksheetItem.position)))


def _replace_items(session, wid: str, ids: list) -> None:
    session.execute(delete(WorksheetItem).where(WorksheetItem.worksheet_id == wid))
    session.add_all([WorksheetItem(worksheet_id=wid, problem_id=pid, position=i) for i, pid in enumerate(ids)])


def _exam_confirmed_ids(session, owner: str, exam_id: str) -> list:
    """시험지의 확인 완료 문제를 사진 순서 → 칸 순서로."""
    return list(session.scalars(
        select(Problem.id).join(Segment, Segment.id == Problem.segment_id).join(Page, Page.id == Segment.page_id)
        .where(Problem.exam_id == exam_id, Problem.status == "confirmed", *alive(Problem, owner))
        .order_by(Page.position, Segment.position, Segment.id)))


# ---------- 조회 ----------
def worksheet_view(session, ws: Worksheet) -> dict:
    rows = session.execute(
        select(Problem, Exam.id, Exam.title, Segment.number)
        .join(WorksheetItem, WorksheetItem.problem_id == Problem.id)
        .join(Exam, Exam.id == Problem.exam_id)
        .outerjoin(Segment, Segment.id == Problem.segment_id)
        .where(WorksheetItem.worksheet_id == ws.id)
        .order_by(WorksheetItem.position)).all()
    numbers = assign_numbers([(p.deleted_at is not None, p.status) for p, _, _, _ in rows],
                             ws.preset, ws.unconfirmed_policy, [snum for *_, snum in rows])
    items = [{"problem_id": p.id, "number": num, "status": p.status, "deleted": p.deleted_at is not None,
              "exam": {"id": eid, "title": etitle or ""}, "preview": preview(p.content or {}),
              "preview_tex": preview_tex(p.content or {}),
              "crop_url": image_url(p.crop_ref), "source_number": snum}
             for (p, eid, etitle, snum), num in zip(rows, numbers)]
    try:
        layout = plan_layout(ExportPreset.from_dict(ws.preset)).summary()
    except PresetError:
        layout = None
    return {"id": ws.id, "title": ws.title, "student": ws.student, "version": ws.version, "items": items,
            "preset": ws.preset, "preset_id": None,
            "unconfirmed_policy": ws.unconfirmed_policy, "layout": layout, "last_export": ws.last_export,
            "updated_at": iso(ws.updated_at)}


def get_worksheet_view(session, owner: str, wid: str) -> dict:
    return worksheet_view(session, _load(session, owner, wid))


def list_worksheets(session, owner: str, limit: int, cursor) -> dict:
    stmt = select(Worksheet).where(*alive(Worksheet, owner))
    if cursor:
        ts, id_ = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Worksheet.updated_at, Worksheet.id) < tuple_(ts, id_))
    rows = list(session.scalars(stmt.order_by(Worksheet.updated_at.desc(), Worksheet.id.desc()).limit(limit + 1)))
    page_rows, more = rows[:limit], len(rows) > limit
    ids = [w.id for w in page_rows]
    counts = {}
    if ids:
        counts = dict(session.execute(
            select(WorksheetItem.worksheet_id, func.count())
            .join(Problem, Problem.id == WorksheetItem.problem_id)
            .where(WorksheetItem.worksheet_id.in_(ids), Problem.deleted_at.is_(None))
            .group_by(WorksheetItem.worksheet_id)).all())
    items = [{"id": w.id, "title": w.title, "student": w.student, "problem_count": counts.get(w.id, 0),
              "last_export": w.last_export, "updated_at": iso(w.updated_at)} for w in page_rows]
    next_cursor = encode_cursor(page_rows[-1].updated_at, page_rows[-1].id) if more and page_rows else None
    return {"items": items, "next_cursor": next_cursor}


# ---------- 만들기·수정·삭제 ----------
def create_worksheet(session, owner: str, body, settings) -> str:
    if body.from_exam_id is not None and body.problem_ids is not None:
        raise ApiError(422, "REQUEST_INVALID", "시험지와 문제 목록 중 하나만 지정해 주세요.")
    student, ids = body.student or "", []
    if body.from_exam_id is not None:
        row = session.execute(select(Exam.student).where(Exam.id == body.from_exam_id, *alive(Exam, owner))).first()
        if row is None:
            raise ApiError(404, "NOT_FOUND")
        if body.student is None:
            student = row[0] or ""
        ids = _exam_confirmed_ids(session, owner, body.from_exam_id)
    elif body.problem_ids:
        ids = _dedupe(body.problem_ids)
        _require_problems(session, owner, ids)
    _check_limit(len(ids), settings)
    ws = Worksheet(id=new_id("ws"), owner_id=owner, title=body.title, student=student,
                   preset=default_preset_value(session, owner))   # 내 기본 모양이 있으면 그것으로 시작
    session.add(ws)
    session.flush()
    _replace_items(session, ws.id, ids)
    session.commit()
    return ws.id


def patch_worksheet(session, owner: str, wid: str, version: int, body) -> None:
    values = {}
    if body.title is not None:
        values["title"] = body.title
    if body.student is not None:
        values["student"] = body.student
    if body.unconfirmed_policy is not None:
        values["unconfirmed_policy"] = body.unconfirmed_policy
    if body.preset is not None and body.preset_id is not None:
        raise ApiError(422, "REQUEST_INVALID", "모양 값과 저장된 모양 중 하나만 지정해 주세요.")
    raw = body.preset
    if body.preset_id is not None:
        raw = get_preset_value(session, owner, body.preset_id)   # 선택한 시점의 값을 복사한다
    if raw is not None:
        preset = ExportPreset.from_dict(raw)
        plan_layout(preset)              # 잘못된 모양이면 PresetError → 422 PRESET_INVALID
        values["preset"] = preset.to_dict()
    if not values:
        raise ApiError(422, "REQUEST_INVALID", "바꿀 내용이 없어요.")
    update_versioned(session, Worksheet, wid, owner, version, values)
    session.commit()


def delete_worksheet(session, owner: str, wid: str) -> None:
    soft_delete(session, Worksheet, wid, owner)
    session.commit()


def duplicate_worksheet(session, owner: str, wid: str) -> str:
    src = _load(session, owner, wid)
    title = f"{src.title} 복사본"[:200] if src.title else ""
    ws = Worksheet(id=new_id("ws"), owner_id=owner, title=title, student=src.student,
                   preset=copy.deepcopy(src.preset),
                   unconfirmed_policy=src.unconfirmed_policy)
    ids = _current_ids(session, wid)
    session.add(ws)
    session.flush()
    _replace_items(session, ws.id, ids)
    session.commit()
    return ws.id


# ---------- 담기·순서 ----------
def add_problems(session, owner: str, wid: str, ids: list, settings) -> None:
    """뒤에 추가. 이미 담긴 문제는 무시(중복 담기 방지)."""
    _load(session, owner, wid, lock=True)
    current = _current_ids(session, wid)
    have = set(current)
    new = [i for i in _dedupe(ids) if i not in have]
    _require_problems(session, owner, new)
    _check_limit(len(current) + len(new), settings)
    session.add_all([WorksheetItem(worksheet_id=wid, problem_id=pid, position=len(current) + i)
                     for i, pid in enumerate(new)])
    session.execute(update(Worksheet).where(Worksheet.id == wid)
                    .values(version=Worksheet.version + 1, updated_at=func.now()))
    session.commit()


def replace_problems(session, owner: str, wid: str, version: int, ids: list, settings) -> None:
    """순서 있는 전체 목록으로 교체(순서 변경·빼기). 이미 담긴 문제는 삭제된 것이어도 유지할 수 있다."""
    ids = _dedupe(ids)
    _check_limit(len(ids), settings)
    update_versioned(session, Worksheet, wid, owner, version, {})
    have = set(_current_ids(session, wid))
    _require_problems(session, owner, [i for i in ids if i not in have])
    _replace_items(session, wid, ids)
    session.commit()
