"""라이브러리 예외 → HTTP 오류 매핑 (설계 5장). 본문: {"error": {code, message, details, retryable, request_id}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..export.hwpx import (EmptyExportError, ExportError, MissingNumberError, PresetError,
                           UnconfirmedProblemError)
from ..storage.images import StorageError
from .messages import friendly

log = logging.getLogger("sheet_forge.api")
_RETRYABLE_STATUS = (502, 503, 504)


class ApiError(Exception):
    """message를 생략하면 messages.py의 쉬운 문장을 쓴다. retryable을 생략하면 502·503·504만 True."""

    def __init__(self, status: int, code: str, message: str | None = None, details=None, retryable: bool | None = None):
        message = message or friendly(code)
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []
        self.retryable = (status in _RETRYABLE_STATUS) if retryable is None else retryable


def error_response(request: Request, status: int, code: str, message: str, details=None,
                   retryable: bool | None = None) -> JSONResponse:
    if retryable is None:
        retryable = status in _RETRYABLE_STATUS
    body = {"error": {"code": code, "message": message, "details": details or [], "retryable": retryable,
                      "request_id": getattr(request.state, "request_id", None)}}
    return JSONResponse(body, status_code=status)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.details, exc.retryable)

    async def _db_down(request: Request, exc: Exception):
        # 쿼리·파라미터에는 문제 내용이 들어 있을 수 있으므로 예외 종류만 로그에 남긴다.
        log.error("DB 오류 request_id=%s %s", getattr(request.state, "request_id", None), type(exc).__name__)
        return error_response(request, 503, "DB_UNAVAILABLE", friendly("DB_UNAVAILABLE"), retryable=True)

    for exc_type in (OperationalError, InterfaceError, PoolTimeoutError):
        app.add_exception_handler(exc_type, _db_down)

    @app.exception_handler(StorageError)
    async def _storage_down(request: Request, exc: StorageError):
        log.error("저장소 오류 request_id=%s %s", getattr(request.state, "request_id", None), exc)
        return error_response(request, 503, "STORAGE_UNAVAILABLE", friendly("STORAGE_UNAVAILABLE"), retryable=True)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                   for e in exc.errors()]
        return error_response(request, 422, "REQUEST_INVALID", "요청 형식이 올바르지 않음", details)

    @app.exception_handler(PresetError)
    async def _preset(request: Request, exc: PresetError):
        return error_response(request, 422, "PRESET_INVALID", "preset이 올바르지 않음",
                              [{"code": c, "message": m} for c, m in exc.errors])

    @app.exception_handler(EmptyExportError)
    async def _empty(request: Request, exc: EmptyExportError):
        return error_response(request, 422, "EMPTY_EXPORT", str(exc))

    @app.exception_handler(MissingNumberError)
    async def _missing_number(request: Request, exc: MissingNumberError):
        return error_response(request, 422, "SOURCE_NUMBER_MISSING", friendly("SOURCE_NUMBER_MISSING"))

    @app.exception_handler(UnconfirmedProblemError)
    async def _unconfirmed(request: Request, exc: UnconfirmedProblemError):
        return error_response(request, 409, "NOT_CONFIRMED", str(exc))

    @app.exception_handler(ExportError)
    async def _internal(request: Request, exc: ExportError):  # TemplateError, InternalValidationError
        # 상세(내부 검증 실패 목록 등)는 로그에만 남기고 응답에는 일반 메시지만 낸다. 파일은 돌려주지 않는다.
        log.error("내부 오류 request_id=%s %s: %s", getattr(request.state, "request_id", None), type(exc).__name__, exc)
        return error_response(request, 500, "INTERNAL_ERROR", "내보내기 중 내부 오류가 발생함")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return error_response(request, exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))
