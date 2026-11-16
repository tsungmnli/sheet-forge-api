"""이미지 서빙 (웹 REST API 설계 3장). 소유자의 살아 있는 사진에 딸린 ref만 열린다."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...db.ids import is_valid_id
from ...db.models import Page
from ..deps import current_user, get_session, get_store
from ..errors import ApiError
from ..repo import alive

router = APIRouter(prefix="/v1")
_CACHE = "private, max-age=86400, immutable"  # ref는 한 번 만들면 바뀌지 않는다


@router.get("/images/{ref}")
def get_image(ref: str, request: Request, owner: str = Depends(current_user),
              session: Session = Depends(get_session), store=Depends(get_store)):
    if not is_valid_id(ref, "img"):
        raise ApiError(404, "NOT_FOUND")
    owned = session.execute(select(Page.id).where(*alive(Page, owner),
                                                  or_(Page.original_ref == ref, Page.corrected_ref == ref)).limit(1)).first()
    if owned is None:
        raise ApiError(404, "NOT_FOUND")
    tag = f'"{ref}"'
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": _CACHE})
    obj = store.get(ref)
    if obj is None:
        raise ApiError(404, "NOT_FOUND")
    return Response(obj[0], media_type=obj[1], headers={"ETag": tag, "Cache-Control": _CACHE})
