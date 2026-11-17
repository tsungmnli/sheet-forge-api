"""리소스 ID = 접두사 + ULID (웹 REST API 설계 3장). 클라이언트는 불투명 문자열로 다룬다."""
import os
import re
import time

PREFIXES = frozenset({"exam", "page", "seg", "prob", "ws", "preset", "fig", "job", "img", "user"})
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_ULID = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"


def new_ulid(now_ms: int | None = None) -> str:
    """48비트 시각(ms) + 80비트 난수 = 26자. 시각 순으로 정렬된다."""
    t = int(time.time() * 1000) if now_ms is None else now_ms
    value = (t << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str, now_ms: int | None = None) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"알 수 없는 ID 접두사: {prefix}")
    return f"{prefix}_{new_ulid(now_ms)}"


def is_valid_id(value: str, prefix: str) -> bool:
    return prefix in PREFIXES and re.fullmatch(rf"{prefix}_{_ULID}", value or "") is not None
