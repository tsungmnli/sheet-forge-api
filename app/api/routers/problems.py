"""문제(확인 화면) 라우트 (웹 REST API 설계 5.4~5.6). 로직은 problem_service·problem_logic에 있다."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import problem_service as svc
from ..concurrency import etag, require_if_match
from ..deps import current_user, get_now, get_session, get_settings
from ..problem_logic import check_math
from ..schemas_web import ContentPutIn, FigureAddIn, FigureRegionIn
from ..settings import Settings

router = APIRouter(prefix="/v1")

State = Literal["not_read", "recognizing", "needs_review", "confirmed", "failed"]


def _with_etag(out: dict, response: Response) -> dict:
    response.headers["ETag"] = etag(out["version"])
    return out


@router.get("/problems/{pid}")
def get_problem(pid: str, response: Response, owner: str = Depends(current_user),
                session: Session = Depends(get_session)):
    return _with_etag(svc.get_problem(session, owner, pid), response)


@router.get("/problems/{pid}/neighbors")
def get_neighbors(pid: str, exam_id: str | None = Query(None, max_length=40), state: State | None = Query(None),
                  owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.neighbors(session, owner, pid, exam_id, state)


@router.put("/problems/{pid}/content")
def put_content(pid: str, body: ContentPutIn, response: Response, version: int = Depends(require_if_match),
                owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """자동 저장. If-Match 필수. 상태는 바뀌지 않는다."""
    return _with_etag(svc.put_content(session, owner, pid, version, body.content, body.points), response)


@router.post("/problems/{pid}/confirm")
def confirm(pid: str, response: Response, version: int = Depends(require_if_match),
            owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return _with_etag(svc.confirm(session, owner, pid, version), response)


@router.post("/problems/{pid}/reopen")
def reopen(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session)):
    return _with_etag(svc.reopen(session, owner, pid), response)


@router.post("/problems/{pid}/revert")
def revert(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session)):
    return _with_etag(svc.revert(session, owner, pid), response)


@router.post("/problems/{pid}/reread", status_code=202)
def reread(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session), settings: Settings = Depends(get_settings),
           now: datetime = Depends(get_now)):
    return _with_etag(svc.reread(session, owner, pid, settings, now), response)


@router.delete("/problems/{pid}", status_code=204, response_class=Response)
def delete_problem(pid: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_problem(session, owner, pid)
    return Response(status_code=204)


@router.post("/problems/{pid}/figures", status_code=202)
def add_figure(pid: str, body: FigureAddIn, response: Response, owner: str = Depends(current_user),
               session: Session = Depends(get_session)):
    return _with_etag(svc.add_figure(session, owner, pid, body.bbox, body.placement, body.width_mm), response)


@router.put("/problems/{pid}/figures/{fid}/region", status_code=202)
def set_figure_region(pid: str, fid: str, body: FigureRegionIn, response: Response,
                      owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return _with_etag(svc.set_figure_region(session, owner, pid, fid, body.bbox), response)


@router.delete("/problems/{pid}/figures/{fid}")
def delete_figure(pid: str, fid: str, response: Response, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    return _with_etag(svc.delete_figure(session, owner, pid, fid), response)


# ---- 수식 점검 (5.6): 무상태, DB 없음 ----
class _MathItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latex: str = Field("", max_length=2000)


class MathCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[_MathItem] = Field(max_length=200)


@router.post("/math/check")
def math_check(body: MathCheckIn):
    return {"results": [check_math(i.latex) for i in body.items]}
