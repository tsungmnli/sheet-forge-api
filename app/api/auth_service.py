"""로그인·초대·비밀번호 재설정 (인증 API). 커밋은 이 함수들이 직접 한다."""
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.email_tokens import consume_email_token, issue_email_token, peek_email_token
from ..auth.mail import Mailer, MailError
from ..auth.passwords import hash_password, needs_rehash, verify_password
from ..auth.sessions import create_session, revoke_session, revoke_user_sessions
from ..auth.tokens import hash_token
from ..db.ids import new_id
from ..db.models import User
from .errors import ApiError
from .settings import Settings

log = logging.getLogger("sheet_forge.api")
SERVICE_NAME = "시험지 서비스"   # 메일에 쓰는 서비스 이름


def _find_user(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def send_invite(session: Session, mailer: Mailer, settings: Settings, email: str, *, now: datetime) -> None:
    """초대 메일을 보낸다. 이미 가입한 이메일이면 409. 링크는 DB에 저장한 뒤에 보내서, 메일이 가면 링크가 항상 유효하다."""
    email = email.strip().lower()   # DB에는 소문자만 저장한다. 호출하는 쪽이 정규화하지 않았어도 안전하게
    if _find_user(session, email):
        raise ApiError(409, "ALREADY_REGISTERED")
    token = issue_email_token(session, email, "invite", now=now)
    session.commit()
    link = f"{settings.web_base_url}/signup?token={token}"
    try:
        mailer.send(email, f"[{SERVICE_NAME}] 초대장이 도착했어요",
                    f"안녕하세요.\n\n{SERVICE_NAME}에 초대되었어요. 아래 링크에서 비밀번호를 정하면 바로 시작할 수 있어요.\n\n"
                    f"{link}\n\n링크는 7일 동안 쓸 수 있어요. 초대받은 적이 없다면 이 메일은 무시해 주세요.")
    except MailError as exc:
        log.error("초대 메일 실패 %s", exc)
        raise ApiError(503, "MAIL_FAILED", retryable=True) from exc


def peek_invite(session: Session, token: str, *, now: datetime) -> str:
    """가입 화면에 보여 줄 이메일. 링크는 소비하지 않는다."""
    email = peek_email_token(session, token, "invite", now=now)
    if email is None:
        raise ApiError(400, "INVITE_INVALID")
    return email


def accept_invite(session: Session, settings: Settings, token: str, password: str, *, now: datetime,
                  user_agent: str | None) -> tuple[User, str]:
    """초대 링크로 가입하고 바로 로그인한다. 첫 가입자는 기존 데이터(default_owner_id)를 이어받는다."""
    email = consume_email_token(session, token, "invite", now=now)
    if email is None:
        raise ApiError(400, "INVITE_INVALID")
    if _find_user(session, email):
        raise ApiError(409, "ALREADY_REGISTERED")   # 반환 전에 끝내므로 소비한 토큰도 되돌아간다
    first = session.scalar(select(func.count()).select_from(User)) == 0
    user = User(id=settings.default_owner_id if first else new_id("user"), email=email,
                password_hash=hash_password(password), created_at=now)
    session.add(user)
    try:
        session.flush()
    except IntegrityError:   # 같은 순간에 같은 이메일(또는 첫 가입)이 먼저 들어간 경우
        session.rollback()
        raise ApiError(409, "ALREADY_REGISTERED") from None
    sid = create_session(session, user.id, now=now, ttl_days=settings.session_ttl_days, user_agent=user_agent)
    session.commit()
    return user, sid


def login(session: Session, settings: Settings, email: str, password: str, *, now: datetime,
          user_agent: str | None) -> tuple[User, str]:
    user = _find_user(session, email)
    if not verify_password(user.password_hash if user else None, password):
        raise ApiError(401, "INVALID_CREDENTIALS")   # 없는 이메일과 틀린 비밀번호를 구분하지 않는다
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    sid = create_session(session, user.id, now=now, ttl_days=settings.session_ttl_days, user_agent=user_agent)
    session.commit()
    return user, sid


def logout(session: Session, token: str | None) -> None:
    if token:
        revoke_session(session, hash_token(token))
        session.commit()


def forgot_password(session: Session, mailer: Mailer, settings: Settings, email: str, *, now: datetime) -> None:
    """재설정 메일을 보낸다. 가입한 이메일인지는 응답으로 알려 주지 않는다(없으면 조용히 끝)."""
    if _find_user(session, email) is None:
        return
    token = issue_email_token(session, email, "reset", now=now)
    session.commit()
    link = f"{settings.web_base_url}/reset-password?token={token}"
    try:
        mailer.send(email, f"[{SERVICE_NAME}] 비밀번호를 다시 정해 주세요",
                    f"비밀번호를 다시 정하려면 아래 링크를 눌러 주세요.\n\n{link}\n\n링크는 1시간 동안 쓸 수 있어요. "
                    "요청한 적이 없다면 이 메일은 무시해 주세요. 비밀번호는 바뀌지 않아요.")
    except MailError as exc:
        log.error("재설정 메일 실패 %s", exc)   # 가입 여부가 드러나지 않도록 호출한 쪽에는 알리지 않는다


def reset_password(session: Session, token: str, password: str, *, now: datetime) -> None:
    """새 비밀번호로 바꾸고 모든 기기에서 로그아웃시킨다."""
    email = consume_email_token(session, token, "reset", now=now)
    user = _find_user(session, email) if email else None
    if user is None:
        raise ApiError(400, "RESET_INVALID")
    user.password_hash = hash_password(password)
    revoke_user_sessions(session, user.id)
    session.commit()
