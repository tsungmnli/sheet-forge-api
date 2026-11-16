"""내 정보·설정 (REST 설계 5.9)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import me_service as svc
from ..deps import current_user, get_session

router = APIRouter(prefix="/v1")


@router.get("/me")
def get_me(owner: str = Depends(current_user)):
    return svc.me(owner)


@router.get("/me/settings")
def get_my_settings(owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.get_settings(session, owner)


@router.patch("/me/settings")
def patch_my_settings(body: svc.SettingsPatch, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """바꿀 값만 보낸다(부분 수정). 잘못된 값은 422. 응답은 바뀐 뒤의 전체 설정."""
    return svc.patch_settings(session, owner, body)
