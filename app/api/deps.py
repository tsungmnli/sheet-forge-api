from datetime import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from ..db.database import Database
from ..auth.mail import Mailer
from ..auth.sessions import resolve_session
from .errors import ApiError
from .settings import Settings

SESSION_COOKIE = "sid"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer   # 테스트에서는 보낸 메일을 기록하는 가짜로 바꾼다


def get_now(request: Request) -> datetime:
    return request.app.state.clock()  # 테스트에서 고정할 수 있게 앱에 주입한다(결정적 출력)


def read_session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or None


def current_user(request: Request) -> str:
    """선생님 식별자(owner_id). auth_required가 꺼져 있으면 설정의 단일 값(D3), 켜져 있으면 로그인 세션의 사용자 id.
    세션이 없거나 만료됐으면 401. 만료 연장은 여기서 따로 짧은 세션으로 기록한다(엔드포인트 세션과 섞지 않는다)."""
    settings: Settings = request.app.state.settings
    if not settings.auth_required:
        return settings.default_owner_id
    token = read_session_token(request)
    if token is None:
        raise ApiError(401, "NOT_AUTHENTICATED")
    session: Session = get_db(request).session()
    try:
        found = resolve_session(session, token, now=request.app.state.clock(), ttl_days=settings.session_ttl_days)
        if found is None:
            raise ApiError(401, "NOT_AUTHENTICATED")
        session.commit()  # 만료 연장이 있었다면 저장
        return found[0].id
    finally:
        session.close()


def get_db(request: Request) -> Database:
    db = getattr(request.app.state, "db", None)
    if db is None:  # DB 주소를 설정하지 않은 개발·테스트 구성
        raise ApiError(503, "DB_UNAVAILABLE")
    return db


def get_session(request: Request):
    """쓰기 세션. 커밋은 서비스 함수가 session.commit()으로 직접 한다(자동 커밋 없음). 끝나면 닫고 미커밋은 되돌린다."""
    session: Session = get_db(request).session()
    try:
        yield session
    finally:
        session.close()


def get_store(request: Request):
    """이미지 저장소. MinIO 주소를 설정하지 않았으면 503."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise ApiError(503, "STORAGE_UNAVAILABLE")
    return store


def get_ro_session(request: Request):
    """읽기 전용 세션(내보내기 경로, D1). 항상 SET TRANSACTION READ ONLY로 시작한다."""
    session: Session = get_db(request).ro_session()
    try:
        yield session
    finally:
        session.close()
