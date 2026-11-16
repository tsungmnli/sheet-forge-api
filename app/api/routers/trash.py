"""휴지통 (REST 설계 5.9). 목록과 복구."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import trash_service as svc
from ..deps import current_user, get_session, get_settings
from ..settings import Settings

router = APIRouter(prefix="/v1")


@router.get("/trash")
def list_trash(type_: str | None = Query(None, alias="type", pattern="^(exam|page|problem|worksheet)$"),
               limit: int = Query(100, ge=1, le=200), owner: str = Depends(current_user),
               session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    """삭제한 항목: type, id, label, deleted_at, purge_at(보관 기간이 끝나 영구 삭제되는 시각). 최근에 지운 것이 먼저."""
    return svc.list_trash(session, owner, type_, limit, settings.trash_retention_days)


@router.post("/trash/{type_}/{obj_id}/restore")
def restore(type_: str, obj_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """복구. 같이 지운 것만 함께 되살린다. 부모가 휴지통에 있으면 409 PARENT_IN_TRASH."""
    return svc.restore(session, owner, type_, obj_id)
