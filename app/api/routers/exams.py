"""시험지와 사진 (웹 REST API 설계 5.2·5.3)."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import problem_service, segment_service, web_service as svc
from ...db.models import Exam
from ..concurrency import etag, etag_json, require_if_match
from ..deps import current_user, get_now, get_session, get_settings, get_store
from ..errors import ApiError
from ..photos import sniff_image
from ..repo import update_versioned
from ..schemas_problem import ERR_COMMON, ERR_MARK, ERR_READ, ListState, MarkOut, ProblemListOut, ReadOut
from ..schemas_web import (ExamCreateIn, ExamListOut, ExamOut, ExamPatchIn, PageListOut, PageOrderIn,
                           ReadIn, SegmentsMarkIn)
from ..serialize import POLL_MS, page_out
from ..settings import Settings
from ...db.ids import new_id

router = APIRouter()


@router.post("/exams", status_code=201, response_model=ExamOut)
def create_exam(response: Response, body: ExamCreateIn | None = None, owner: str = Depends(current_user),
                session: Session = Depends(get_session)):
    body = body or ExamCreateIn()
    exam = Exam(id=new_id("exam"), owner_id=owner, title=body.title, student=body.student, memo=body.memo,
                source_label=body.source_label)
    session.add(exam)
    session.commit()
    out = svc.get_exam_view(session, owner, exam.id)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.get("/exams", response_model=ExamListOut)
def list_exams(student: str | None = Query(None, max_length=100), q: str | None = Query(None, max_length=100),
               limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=200),
               owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.list_exams(session, owner, student, q, limit, cursor)


@router.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: str, response: Response, owner: str = Depends(current_user),
             session: Session = Depends(get_session)):
    out = svc.get_exam_view(session, owner, exam_id)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.patch("/exams/{exam_id}", response_model=ExamOut)
def patch_exam(exam_id: str, body: ExamPatchIn, response: Response, version: int = Depends(require_if_match),
               owner: str = Depends(current_user), session: Session = Depends(get_session)):
    values = body.model_dump(exclude_none=True)
    if not values:
        raise ApiError(422, "REQUEST_INVALID", "바꿀 내용이 없어요.")
    update_versioned(session, Exam, exam_id, owner, version, values)
    session.commit()
    out = svc.get_exam_view(session, owner, exam_id)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.delete("/exams/{exam_id}", status_code=204, response_class=Response)
def delete_exam(exam_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_exam(session, owner, exam_id)
    return Response(status_code=204)


@router.post("/exams/{exam_id}/pages", status_code=202, response_model=PageListOut)
async def upload_pages(exam_id: str, files: list[UploadFile] = File(...), owner: str = Depends(current_user),
                       store=Depends(get_store), session: Session = Depends(get_session),
                       settings: Settings = Depends(get_settings)):
    """사진 올리기(multipart, 필드 이름 `files`, 여러 장). 보정·문제 칸 나누기는 작업자가 이어서 한다."""
    if len(files) > settings.max_pages_per_exam:
        raise ApiError(422, "TOO_MANY_PAGES")
    prepared = []
    for f in files:
        data = await f.read(settings.max_photo_bytes + 1)
        if len(data) > settings.max_photo_bytes:
            raise ApiError(413, "PHOTO_TOO_LARGE")
        content_type = sniff_image(data)
        if content_type is None:
            raise ApiError(415, "PHOTO_UNSUPPORTED")
        prepared.append((data, content_type))
    pages = await run_in_threadpool(svc.create_pages, session, store, settings, owner, exam_id, prepared)
    return {"items": [page_out(p, 0) for p in pages], "poll_after_ms": POLL_MS}


@router.get("/exams/{exam_id}/pages", response_model=PageListOut)
def list_pages(exam_id: str, request: Request, owner: str = Depends(current_user),
               session: Session = Depends(get_session)):
    payload = PageListOut.model_validate(svc.list_pages(session, owner, exam_id)).model_dump(mode="json")
    return etag_json(request, payload)


@router.put("/exams/{exam_id}/pages/order", response_model=PageListOut)
def reorder_pages(exam_id: str, body: PageOrderIn, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    return svc.reorder_pages(session, owner, exam_id, body.page_ids)


@router.post("/exams/{exam_id}/segments/mark", response_model=MarkOut, responses=ERR_MARK)
def mark_segments(exam_id: str, body: SegmentsMarkIn, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    """한꺼번에 고르기/해제. 범위: segment_ids → 그 칸들, page_id → 그 사진 전부, 둘 다 없으면 시험지 전부."""
    if body.segment_ids is not None and body.page_id is not None:
        raise ApiError(422, "REQUEST_INVALID", "칸 목록과 사진 중 하나만 지정해 주세요.")
    return segment_service.mark_many(session, owner, exam_id, body.marked, body.segment_ids, body.page_id)


@router.post("/exams/{exam_id}/read", status_code=202, response_model=ReadOut, responses=ERR_READ)
def read_problems(exam_id: str, body: ReadIn | None = None, owner: str = Depends(current_user),
                  session: Session = Depends(get_session), settings: Settings = Depends(get_settings),
                  now: datetime = Depends(get_now)):
    """고른 문제 읽기. 본문이 없으면 읽지 않은 고른 칸 전부. 이미 문제가 있는 칸은 건너뛴다."""
    ids = body.segment_ids if body is not None else None
    return problem_service.read_segments(session, owner, exam_id, ids, settings, now)


@router.get("/exams/{exam_id}/problems", response_model=ProblemListOut, responses=ERR_COMMON)
def list_problems(exam_id: str, state: ListState | None = Query(None), owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """시험지 '문제' 탭. 항목은 고른 칸이고 읽기 전 칸도 not_read로 나온다."""
    return problem_service.list_exam_problems(session, owner, exam_id, state)
