"""내 정보·설정 (REST 설계 5.9)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import me_service as svc
from ...db.models import User
from ..deps import current_user, get_db, get_session, get_settings
from ..schemas_home import MeOut, SettingsOut

router = APIRouter()


@router.get("/me", response_model=MeOut, response_model_exclude_none=True,
            responses={401: {"description": "로그인 필요 (NOT_AUTHENTICATED)"}})
def get_me(request: Request, owner: str = Depends(current_user), settings=Depends(get_settings)):
    email = None
    if settings.auth_required:   # 로그인을 끈 개발·테스트에서는 DB 없이 동작한다
        s = get_db(request).session()
        try:
            user = s.get(User, owner)
            email = user.email if user else None
        finally:
            s.close()
    return svc.me(owner, email)


@router.get("/me/settings", response_model=SettingsOut)
def get_my_settings(owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.get_settings(session, owner)


@router.post("/me/default-preset", response_model=SettingsOut,
             responses={404: {"description": "문제지를 찾을 수 없음 (NOT_FOUND)"}})
def save_my_default_preset(body: svc.DefaultPresetIn, owner: str = Depends(current_user),
                           session: Session = Depends(get_session)):
    """이 문제지의 지금 모양을 내 기본 모양으로 저장한다. 앞으로 만드는 새 문제지가 이 모양으로 시작하고,
    이미 만든 문제지는 바뀌지 않는다. 응답은 바뀐 뒤의 전체 설정."""
    return svc.save_default_preset(session, owner, body)


@router.patch("/me/settings", response_model=SettingsOut,
              responses={422: {"description": "잘못된 설정 값 (REQUEST_INVALID)"}})
def patch_my_settings(body: svc.SettingsPatch, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """바꿀 값만 보낸다(부분 수정). 잘못된 값은 422. 응답은 바뀐 뒤의 전체 설정."""
    return svc.patch_settings(session, owner, body)
