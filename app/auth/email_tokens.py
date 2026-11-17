"""메일로 보내는 1회용 링크: 초대(invite)와 비밀번호 재설정(reset). 이메일 주소에 묶는다."""
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import EmailToken
from .tokens import hash_token, new_token

TTL = {"invite": timedelta(days=7), "reset": timedelta(hours=1)}


def issue_email_token(db: Session, email: str, purpose: str, *, now: datetime) -> str:
    """(이메일, 목적)의 새 토큰. 아직 안 쓴 이전 토큰은 먼저 못 쓰게 해서, 새 링크를 받으면 옛 링크가 죽는다.
    원문 토큰을 돌려주고 commit은 호출하는 쪽이 한다."""
    db.execute(update(EmailToken).where(EmailToken.email == email, EmailToken.purpose == purpose,
                                        EmailToken.used_at.is_(None)).values(used_at=now))
    token = new_token()
    db.add(EmailToken(token_hash=hash_token(token), purpose=purpose, email=email, created_at=now,
                      expires_at=now + TTL[purpose]))
    db.flush()
    return token


def peek_email_token(db: Session, token: str, purpose: str, *, now: datetime) -> str | None:
    """consume과 같은 조건으로 이메일만 본다(쓴 것으로 치지 않는다). 가입 화면에서 이메일을 보여 줄 때 쓴다."""
    return db.scalar(select(EmailToken.email).where(
        EmailToken.token_hash == hash_token(token), EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None), EmailToken.expires_at > now))


def consume_email_token(db: Session, token: str, purpose: str, *, now: datetime) -> str | None:
    """토큰을 한 번 쓴다. 이메일을 돌려주고, 모르는·이미 쓴·만료된·목적이 다른 토큰이면 None.
    UPDATE 한 문장으로 정하므로 동시에 두 번 써도 한쪽만 성공한다."""
    return db.scalar(
        update(EmailToken)
        .where(EmailToken.token_hash == hash_token(token), EmailToken.purpose == purpose,
               EmailToken.used_at.is_(None), EmailToken.expires_at > now)
        .values(used_at=now).returning(EmailToken.email))
