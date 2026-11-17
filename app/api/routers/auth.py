"""로그인·초대·비밀번호 재설정. 로그인하면 httpOnly 쿠키 sid에 세션 토큰을 담는다."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .. import auth_service as svc
from ..deps import SESSION_COOKIE, get_mailer, get_now, get_session, get_settings, read_session_token
from ..schemas_auth import AcceptInviteIn, ForgotIn, InvitePeekOut, LoginIn, ResetIn
from ..schemas_home import MeOut
from ..settings import Settings

router = APIRouter(prefix="/auth")

# 쿠키 수명은 길게 둔다. 로그인이 실제로 언제 끝나는지는 서버 세션의 만료(쓸수록 늘어남)가 정하고,
# 쿠키가 먼저 사라지면 매일 쓰는 사람도 30일째에 갑자기 로그아웃되기 때문이다.
COOKIE_MAX_AGE = 400 * 24 * 3600


def _cookie_args(settings: Settings) -> dict:
    # SameSite=Lax: 다른 사이트에서 보낸 POST에는 쿠키가 실리지 않는다(CSRF 방어)
    return {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}


def _me(user) -> dict:
    return {"id": user.id, "display_name": "선생님", "email": user.email}


@router.get("/invite", response_model=InvitePeekOut, responses={400: {"description": "만료됐거나 쓴 링크 (INVITE_INVALID)"}})
def peek_invite(token: str = Query(min_length=1, max_length=200), session: Session = Depends(get_session),
                now: datetime = Depends(get_now)):
    """가입 화면에 '이 이메일로 가입해요'를 보여 주기 위한 조회. 링크를 쓴 것으로 치지 않는다."""
    return {"email": svc.peek_invite(session, token, now=now)}


@router.post("/invite/accept", response_model=MeOut,
             responses={400: {"description": "만료됐거나 쓴 링크 (INVITE_INVALID)"},
                        409: {"description": "이미 가입한 이메일 (ALREADY_REGISTERED)"}})
def accept_invite(body: AcceptInviteIn, request: Request, response: Response, session: Session = Depends(get_session),
                  settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)):
    """초대 링크로 가입하고 바로 로그인한다."""
    user, sid = svc.accept_invite(session, settings, body.token, body.password, now=now,
                                  user_agent=request.headers.get("user-agent"))
    response.set_cookie(SESSION_COOKIE, sid, max_age=COOKIE_MAX_AGE, **_cookie_args(settings))
    return _me(user)


@router.post("/login", response_model=MeOut, responses={401: {"description": "이메일 또는 비밀번호가 다름 (INVALID_CREDENTIALS)"}})
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session),
          settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)):
    user, sid = svc.login(session, settings, body.email, body.password, now=now,
                          user_agent=request.headers.get("user-agent"))
    response.set_cookie(SESSION_COOKIE, sid, max_age=COOKIE_MAX_AGE, **_cookie_args(settings))
    return _me(user)


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    """로그인 상태가 아니어도 204. 쿠키는 항상 지운다."""
    svc.logout(session, read_session_token(request))
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, **_cookie_args(settings))
    return resp


@router.post("/password/forgot", status_code=204, response_class=Response)
def forgot_password(body: ForgotIn, session: Session = Depends(get_session), settings: Settings = Depends(get_settings),
                    mailer=Depends(get_mailer), now: datetime = Depends(get_now)):
    """재설정 메일 요청. 가입한 이메일인지와 상관없이 항상 204."""
    svc.forgot_password(session, mailer, settings, body.email, now=now)
    return Response(status_code=204)


@router.post("/password/reset", status_code=204, response_class=Response,
             responses={400: {"description": "만료됐거나 쓴 링크 (RESET_INVALID)"}})
def reset_password(body: ResetIn, session: Session = Depends(get_session), now: datetime = Depends(get_now)):
    """새 비밀번호로 바꾼다. 모든 기기에서 로그아웃되므로 웹은 로그인 화면으로 보낸다."""
    svc.reset_password(session, body.token, body.password, now=now)
    return Response(status_code=204)
