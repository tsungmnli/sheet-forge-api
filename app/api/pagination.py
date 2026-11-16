"""커서 방식 목록 (웹 REST API 설계 3장): 최근 수정 순, (updated_at, id) 키셋."""
import base64
import json
from datetime import datetime

from .errors import ApiError


def encode_cursor(updated_at: datetime, id_: str) -> str:
    raw = json.dumps([updated_at.isoformat(), id_]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        ts, id_ = json.loads(raw)
        return datetime.fromisoformat(ts), str(id_)
    except Exception as e:  # noqa: BLE001
        raise ApiError(400, "REQUEST_INVALID", "목록 위치 값이 올바르지 않아요. 처음부터 다시 불러와 주세요.") from e
