"""서버 쪽 세션. 브라우저는 무작위 토큰을, DB는 그 해시만 가진다.

만료는 쓸수록 늘어난다(sliding). 다만 기록은 하루에 한 번만 해서, 요청마다 UPDATE가 나가지 않게 한다.
호출하는 쪽이 commit한다.
"""
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import AuthSession, User
from .tokens import hash_token, new_token

TOUCH_INTERVAL = timedelta(days=1)
_UA_MAX = 200


def summarize_user_agent(user_agent: str | None) -> str | None:
    """기기 목록에 보여 줄 짧은 글자(원본 헤더 그대로가 아니라)."""
    if not user_agent:
        return None
    cleaned = "".join(ch for ch in user_agent if ch.isprintable()).strip()
    return cleaned[:_UA_MAX] or None


def create_session(db: Session, user_id: str, *, now: datetime, ttl_days: int, user_agent: str | None = None) -> str:
    """새 세션을 저장하고 원문 토큰을 돌려준다(원문은 이때뿐이다)."""
    token = new_token()
    db.add(AuthSession(token_hash=hash_token(token), user_id=user_id, created_at=now, last_used_at=now,
                       expires_at=now + timedelta(days=ttl_days), user_agent=summarize_user_agent(user_agent)))
    db.flush()
    return token


def resolve_session(db: Session, token: str, *, now: datetime, ttl_days: int) -> tuple[User, AuthSession] | None:
    """토큰의 사용자와 세션. 모르는 토큰이거나 만료됐으면 None. 만료를 늘려야 하면 늘린다."""
    row = db.execute(
        select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.expires_at > now)
    ).first()
    if row is None:
        return None
    user, sess = row
    if now - sess.last_used_at >= TOUCH_INTERVAL:
        sess.last_used_at = now
        sess.expires_at = now + timedelta(days=ttl_days)
        db.flush()
    return user, sess


def revoke_session(db: Session, token_hash: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))


def revoke_user_sessions(db: Session, user_id: str, *, except_hash: str | None = None) -> int:
    """그 사용자를 모든 기기에서 로그아웃시킨다(지금 세션만 남길 수도 있다). 지운 수를 돌려준다."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if except_hash is not None:
        stmt = stmt.where(AuthSession.token_hash != except_hash)
    return db.execute(stmt).rowcount
