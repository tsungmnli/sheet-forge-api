"""문제(확인 화면) 라우트 (웹 REST API 설계 5.4~5.6). 로직은 problem_service·problem_logic에 있다."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import problem_service as svc
from ..concurrency import etag, require_if_match
from ..deps import current_user, get_now, get_session, get_settings, get_store
from ..errors import ApiError
from ...recognition.factory import build_cleaner
from ..problem_logic import check_math
from ..schemas_misc import MathCheckOut
from ..schemas_problem import (ERR_COMMON, ERR_LOCKED, ERR_WRITE, NeighborsOut, ProblemOut, ok)
from ..schemas_web import ContentPutIn, FigureAddIn, FigureCleanLevelIn, FigureEraseColorsIn, FigureRegionIn
from ..settings import Settings

router = APIRouter()

State = Literal["not_read", "recognizing", "needs_review", "confirmed", "failed"]


def _with_etag(out: dict, response: Response) -> dict:
    response.headers["ETag"] = etag(out["version"])
    return out


@router.get("/problems/{pid}", response_model=ProblemOut, responses={**ok(), **ERR_COMMON})
def get_problem(pid: str, response: Response, owner: str = Depends(current_user),
                session: Session = Depends(get_session)):
    return _with_etag(svc.get_problem(session, owner, pid), response)


@router.get("/problems/{pid}/neighbors", response_model=NeighborsOut, responses=ERR_COMMON)
def get_neighbors(pid: str, exam_id: str | None = Query(None, max_length=40), state: State | None = Query(None),
                  owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.neighbors(session, owner, pid, exam_id, state)


@router.put("/problems/{pid}/content", response_model=ProblemOut, responses={**ok(), **ERR_LOCKED})
def put_content(pid: str, body: ContentPutIn, response: Response, version: int = Depends(require_if_match),
                owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """자동 저장. If-Match 필수. 상태는 바뀌지 않는다."""
    return _with_etag(svc.put_content(session, owner, pid, version, body.content, body.points), response)


@router.post("/problems/{pid}/confirm", response_model=ProblemOut, responses={**ok(), **ERR_LOCKED})
def confirm(pid: str, response: Response, version: int = Depends(require_if_match),
            owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return _with_etag(svc.confirm(session, owner, pid, version), response)


@router.post("/problems/{pid}/reopen", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def reopen(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session)):
    return _with_etag(svc.reopen(session, owner, pid), response)


@router.post("/problems/{pid}/revert", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def revert(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session)):
    return _with_etag(svc.revert(session, owner, pid), response)


@router.post("/problems/{pid}/reread", status_code=202, response_model=ProblemOut,
             responses={**ok(202), **ERR_WRITE, 429: {"description": "하루 읽기 한도 (READ_LIMIT)"}})
def reread(pid: str, response: Response, owner: str = Depends(current_user),
           session: Session = Depends(get_session), settings: Settings = Depends(get_settings),
           now: datetime = Depends(get_now)):
    return _with_etag(svc.reread(session, owner, pid, settings, now), response)


@router.delete("/problems/{pid}", status_code=204, response_class=Response)
def delete_problem(pid: str, unpick: bool = False, owner: str = Depends(current_user),
                   session: Session = Depends(get_session)):
    """unpick=true면 칸의 '고름'도 함께 푼다(읽기 실패한 문제를 목록에서 빼는 용도)."""
    svc.delete_problem(session, owner, pid, unpick)
    return Response(status_code=204)


@router.post("/problems/{pid}/figures", status_code=202, response_model=ProblemOut, responses={**ok(202), **ERR_WRITE})
def add_figure(pid: str, body: FigureAddIn, response: Response, owner: str = Depends(current_user),
               session: Session = Depends(get_session)):
    return _with_etag(svc.add_figure(session, owner, pid, body.bbox, body.placement, body.width_mm), response)


@router.put("/problems/{pid}/figures/{fid}/region", status_code=202, response_model=ProblemOut,
            responses={**ok(202), **ERR_WRITE})
def set_figure_region(pid: str, fid: str, body: FigureRegionIn, response: Response,
                      owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return _with_etag(svc.set_figure_region(session, owner, pid, fid, body.bbox), response)


def get_cleaner(request: Request, settings: Settings = Depends(get_settings)):
    """그림 정리기(색 고르기 미리보기용). 처음 쓸 때 한 번 만들어 둔다(테스트는 app.state.cleaner를 바꿔 끼운다)."""
    cleaner = getattr(request.app.state, "cleaner", None)
    if cleaner is None:
        cleaner = request.app.state.cleaner = build_cleaner(settings)
    return cleaner


@router.put("/problems/{pid}/figures/{fid}/clean-level", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def set_figure_clean_level(pid: str, fid: str, body: FigureCleanLevelIn, response: Response,
                           owner: str = Depends(current_user), session: Session = Depends(get_session),
                           store=Depends(get_store), cleaner=Depends(get_cleaner)):
    return _with_etag(svc.set_figure_clean_level(session, owner, pid, fid, body.level, store, body.color, cleaner), response)


@router.put("/problems/{pid}/figures/{fid}/erase-colors", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def set_figure_erase_colors(pid: str, fid: str, body: FigureEraseColorsIn, response: Response,
                            owner: str = Depends(current_user), session: Session = Depends(get_session),
                            store=Depends(get_store), cleaner=Depends(get_cleaner)):
    """지울 색을 골라(palette의 hue 목록) 그 색만 지운 정리본으로 바꾼다. 다른 색은 남는다."""
    return _with_etag(svc.set_figure_erase_colors(session, store, cleaner, owner, pid, fid, body.level, body.hues), response)


@router.put("/problems/{pid}/figures/{fid}/erased", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
async def set_figure_erased(pid: str, fid: str, response: Response, image: UploadFile = File(...),
                            owner: str = Depends(current_user), session: Session = Depends(get_session),
                            store=Depends(get_store), settings: Settings = Depends(get_settings)):
    """낙서 지우개 결과 저장(multipart, 필드 이름 `image`, PNG). 지운 결과가 이 그림의 정리본이 된다."""
    data = await image.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise ApiError(413, "FIGURE_IMAGE_TOO_LARGE")
    out = await run_in_threadpool(svc.set_figure_erased, session, store, settings, owner, pid, fid, data)
    return _with_etag(out, response)


@router.delete("/problems/{pid}/figures/{fid}/erased", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def reset_figure_erased(pid: str, fid: str, response: Response, owner: str = Depends(current_user),
                        session: Session = Depends(get_session), store=Depends(get_store)):
    """지운 결과를 버리고 고른 정리 단계로 되돌린다."""
    return _with_etag(svc.reset_figure_erased(session, store, owner, pid, fid), response)


@router.delete("/problems/{pid}/figures/{fid}", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def delete_figure(pid: str, fid: str, response: Response, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    return _with_etag(svc.delete_figure(session, owner, pid, fid), response)


@router.delete("/problems/{pid}/removed-figures/{fid}", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def discard_removed_figure(pid: str, fid: str, response: Response, owner: str = Depends(current_user),
                           session: Session = Depends(get_session), store=Depends(get_store)):
    """지운 그림을 보관 목록에서 완전히 없앤다(되살릴 수 없음)."""
    return _with_etag(svc.discard_removed_figure(session, store, owner, pid, fid), response)


@router.post("/problems/{pid}/figures/{fid}/restore", response_model=ProblemOut, responses={**ok(), **ERR_WRITE})
def restore_figure(pid: str, fid: str, response: Response, owner: str = Depends(current_user),
                   session: Session = Depends(get_session)):
    """지운 그림 되살리기(문제당 최근 10개까지 보관)."""
    return _with_etag(svc.restore_figure(session, owner, pid, fid), response)


# ---- 수식 점검 (5.6): 무상태, DB 없음 ----
class _MathItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latex: str = Field("", max_length=2000)


class MathCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[_MathItem] = Field(max_length=200)


@router.post("/math/check", response_model=MathCheckOut)
def math_check(body: MathCheckIn):
    return {"results": [check_math(i.latex) for i in body.items]}
