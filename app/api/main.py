"""FastAPI 앱 팩토리 (설계 2장). 실행: uvicorn app.api.main:app"""
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..db.database import Database
from ..storage.images import build_store
from ..export.hwpx.template import Template
from .errors import register_error_handlers
from .routers import exams, exports, health, home, images, me, pages, presets, problems, trash, worksheet_export, worksheet_tools, worksheets
from .settings import Settings

log = logging.getLogger("sheet_forge.api")
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    db = getattr(app.state, "db", None)
    if db is not None:
        db.dispose()


def create_app(settings: Settings | None = None, clock=None, store=None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="sheet-forge-api", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    # 연결은 처음 쓸 때 맺는다(엔진은 느슨). DB 주소가 없으면 DB 없이 동작한다.
    db = (Database(settings.database_url, settings.database_url_ro, settings.db_pool_size,
                   settings.db_connect_timeout_s) if settings.database_url else None)
    app.state.db = db
    store = store if store is not None else build_store(settings)  # MinIO 주소가 없으면 None
    app.state.store = store
    app.state.readiness_checks = {"template": lambda: Template.load()}
    if db is not None:
        app.state.readiness_checks["db"] = db.check
    if store is not None:
        app.state.readiness_checks["storage"] = store.check
    register_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                           allow_headers=["*"], expose_headers=["X-Request-Id", "Content-Disposition", "X-Export-Status",
                                                                 "X-Export-Warnings", "X-Export-Errors"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if _RID_OK.match(rid) else uuid.uuid4().hex
        request.state.request_id = rid
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > settings.max_body_bytes:
            resp = JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE", "message": "요청 본문이 너무 큼",
                                           "details": [], "retryable": False, "request_id": rid}}, status_code=413)
        else:
            t0 = time.perf_counter()
            resp = await call_next(request)
            log.info("%s %s %s %dms request_id=%s", request.method, request.url.path, resp.status_code,
                     round((time.perf_counter() - t0) * 1000), rid)
        resp.headers["X-Request-Id"] = rid
        return resp

    app.include_router(health.router)
    app.include_router(exports.router)
    app.include_router(exams.router)
    app.include_router(pages.router)
    app.include_router(problems.router)
    app.include_router(worksheets.router)
    app.include_router(presets.router)
    app.include_router(worksheet_tools.router)
    app.include_router(worksheet_export.router)
    app.include_router(trash.router)
    app.include_router(me.router)
    app.include_router(home.router)
    app.include_router(images.router)
    return app


app = create_app()
