"""Argon2id 비밀번호 해시.

해시는 일부러 무겁다(기본 64MiB). 라우트가 동기라 스레드풀에서 동시에 돌 수 있어서, 제한이 없으면 동시 로그인이
몰릴 때 작은 파드가 메모리 부족으로 죽는다. 세마포어로 동시 해시 수를 MAX_CONCURRENT_HASHES로 묶는다.
"""
import threading
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 8
MAX_LENGTH = 128          # 아주 긴 본문으로 CPU를 태우지 못하게 거절한다
MAX_CONCURRENT_HASHES = 4

_hasher = PasswordHasher()  # argon2-cffi 기본값(RFC 9106 저메모리 프로필): Argon2id, t=3, m=64MiB, p=4
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


def hash_password(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def verify_password(stored_hash: str | None, password: str) -> bool:
    """비밀번호가 맞으면 True. 해시가 없거나 깨져 있어도 예외를 내지 않는다.

    저장된 해시가 없으면(없는 이메일) 가짜 해시로 대신 검증해서, 응답 시간으로 가입 여부를 알아내지 못하게 한다.
    """
    target = stored_hash or _dummy_hash()
    with _slots:
        try:
            ok = _hasher.verify(target, password)
        except (VerificationError, InvalidHashError):
            return False
    return ok and stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    """해시가 지금보다 약한 설정으로 만들어졌으면 True. 로그인에 성공했을 때(평문이 있을 때) 확인해서 다시 저장한다."""
    return _hasher.check_needs_rehash(stored_hash)
