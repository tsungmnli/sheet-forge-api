"""로그인 요청·응답 본문 (인증 API)."""
import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from ..auth.passwords import MAX_LENGTH, MIN_LENGTH

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    """앞뒤 공백을 지우고 소문자로 바꾼다(DB에는 소문자만 저장·비교한다)."""
    value = value.strip().lower()
    if len(value) > 320 or not _EMAIL.fullmatch(value):
        raise ValueError("올바른 이메일 주소가 아니에요")
    return value


Email = Annotated[str, AfterValidator(normalize_email)]
NewPassword = Annotated[str, Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)]
Token = Annotated[str, Field(min_length=1, max_length=200)]


class LoginIn(BaseModel):
    email: Email
    password: Annotated[str, Field(max_length=1024)]   # 길이는 검사하지 않는다. 길이가 틀린 비밀번호도 그냥 틀린 비밀번호다


class AcceptInviteIn(BaseModel):
    token: Token
    password: NewPassword


class ForgotIn(BaseModel):
    email: Email


class ResetIn(BaseModel):
    token: Token
    password: NewPassword


class InvitePeekOut(BaseModel):
    email: str
