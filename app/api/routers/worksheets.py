"""문제지 (웹 REST API 설계 5.7). 점검·내보내기·모양 저장은 이후 단계."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from .. import worksheet_service as svc
from ..concurrency import etag, require_if_match
from ..deps import current_user, get_session, get_settings
from ..schemas_ws import (ProblemIdsIn, WorksheetCreateIn, WorksheetListOut, WorksheetOut, WorksheetPatchIn)
from ..settings import Settings

router = APIRouter()


def _view(response: Response, session: Session, owner: str, wid: str) -> dict:
    out = svc.get_worksheet_view(session, owner, wid)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.post("/worksheets", status_code=201, response_model=WorksheetOut)
def create_worksheet(response: Response, body: WorksheetCreateIn | None = None, owner: str = Depends(current_user),
                     session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    """from_exam_id면 그 시험지의 확인 완료 문제 전부를 순서대로 담고 학생을 이어받는다."""
    wid = svc.create_worksheet(session, owner, body or WorksheetCreateIn(), settings)
    return _view(response, session, owner, wid)


@router.get("/worksheets", response_model=WorksheetListOut)
def list_worksheets(limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=200),
                    owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.list_worksheets(session, owner, limit, cursor)


@router.get("/worksheets/{worksheet_id}", response_model=WorksheetOut)
def get_worksheet(worksheet_id: str, response: Response, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    return _view(response, session, owner, worksheet_id)


@router.patch("/worksheets/{worksheet_id}", response_model=WorksheetOut)
def patch_worksheet(worksheet_id: str, body: WorksheetPatchIn, response: Response,
                    version: int = Depends(require_if_match), owner: str = Depends(current_user),
                    session: Session = Depends(get_session)):
    svc.patch_worksheet(session, owner, worksheet_id, version, body)
    return _view(response, session, owner, worksheet_id)


@router.put("/worksheets/{worksheet_id}/problems", response_model=WorksheetOut)
def put_problems(worksheet_id: str, body: ProblemIdsIn, response: Response, version: int = Depends(require_if_match),
                 owner: str = Depends(current_user), session: Session = Depends(get_session),
                 settings: Settings = Depends(get_settings)):
    svc.replace_problems(session, owner, worksheet_id, version, body.problem_ids, settings)
    return _view(response, session, owner, worksheet_id)


@router.post("/worksheets/{worksheet_id}/problems", response_model=WorksheetOut)
def add_problems(worksheet_id: str, body: ProblemIdsIn, response: Response, owner: str = Depends(current_user),
                 session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    svc.add_problems(session, owner, worksheet_id, body.problem_ids, settings)
    return _view(response, session, owner, worksheet_id)


@router.post("/worksheets/{worksheet_id}/duplicate", status_code=201, response_model=WorksheetOut,
             operation_id="duplicate_worksheet")
def duplicate_worksheet(worksheet_id: str, response: Response, owner: str = Depends(current_user),
                        session: Session = Depends(get_session)):
    new_id = svc.duplicate_worksheet(session, owner, worksheet_id)
    return _view(response, session, owner, new_id)


@router.delete("/worksheets/{worksheet_id}", status_code=204, response_class=Response)
def delete_worksheet(worksheet_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_worksheet(session, owner, worksheet_id)
    return Response(status_code=204)
