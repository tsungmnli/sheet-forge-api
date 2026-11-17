"""무작위 비밀값(세션 ID, 메일 링크). DB에는 SHA-256 해시만 저장한다."""
import hashlib
import secrets


def new_token() -> str:
    """256비트 난수, URL에 쓸 수 있는 43자."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """hex SHA-256. 입력이 이미 256비트 난수라 빠른 해시로 충분하고, DB가 새어도 쓸 수 있는 토큰이 남지 않는다."""
    return hashlib.sha256(token.encode()).hexdigest()
