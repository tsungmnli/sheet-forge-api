"""문제 검색(문제 담기 패널)과 문제지 점검 (웹 REST API 설계 5.6·5.7)."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import worksheet_tools as svc
from ..deps import current_user, get_session

router = APIRouter(prefix="/v1")


class SearchExam(BaseModel):
    id: str
    title: str
    student: str


class SearchItem(BaseModel):
    id: str
    exam: SearchExam
    number: str | None
    status: str
    preview: str
    crop_url: str | None
    in_worksheet: bool


class SearchOut(BaseModel):
    items: list[SearchItem]
    next_cursor: str | None


class CheckItem(BaseModel):
    code: str
    severity: Literal["info", "warn", "error"]
    message: str
    problem_id: str | None = None
    problem_ids: list[str] | None = None


class CheckOut(BaseModel):
    ready: bool
    items: list[CheckItem]


@router.get("/problems", response_model=SearchOut)
def search_problems(status: Literal["recognizing", "needs_review", "confirmed", "failed"] | None = Query("confirmed"),
                    student: str | None = Query(None, max_length=100), exam_id: str | None = Query(None, max_length=40),
                    q: str | None = Query(None, max_length=100), worksheet_id: str | None = Query(None, max_length=40),
                    limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=200),
                    owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """'문제 담기' 패널. 기본은 확인 완료 문제. worksheet_id를 주면 이미 담긴 문제를 표시한다."""
    return svc.search_problems(session, owner, status, student, exam_id, q, worksheet_id, limit, cursor)


@router.get("/worksheets/{worksheet_id}/check", response_model=CheckOut)
def check_worksheet(worksheet_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """만들기 전 점검. 파일은 만들지 않는다. ready=false는 내보낼 수 없는 경우다."""
    return svc.check_worksheet(session, owner, worksheet_id)
