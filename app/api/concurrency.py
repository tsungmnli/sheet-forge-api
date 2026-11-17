"""낙관적 잠금 (웹 REST API 설계 3장): version ↔ ETag·If-Match."""
import hashlib
import json
import re

from fastapi import Header, Request, Response

from .errors import ApiError

_IF_MATCH = re.compile(r'(?:W/)?"?(\d{1,9})"?')


def etag(version: int) -> str:
    return f'"{version}"'


def require_if_match(request: Request,
                     if_match: str | None = Header(None, alias="If-Match", description="수정할 리소스의 version(ETag 값)")) -> int:
    """If-Match에서 version을 읽는다. 없으면 428 VERSION_REQUIRED, 형식이 이상하면 400 REQUEST_INVALID.

    쓰는 곳: Depends(require_if_match). 값이 낡았는지는 repo.update_versioned가 412로 판정한다.
    """
    raw = (request.headers.get("if-match") or "").strip()
    if not raw:
        raise ApiError(428, "VERSION_REQUIRED")
    m = _IF_MATCH.fullmatch(raw)
    if m is None:
        raise ApiError(400, "REQUEST_INVALID")
    return int(m.group(1))


def etag_json(request: Request, payload: dict) -> Response:
    """내용 해시로 ETag를 만들고 If-None-Match가 같으면 304(처리 중 폴링의 부하를 줄인다)."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    tag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag})
    return Response(body, media_type="application/json", headers={"ETag": tag})
