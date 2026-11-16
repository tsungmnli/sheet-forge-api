from datetime import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from ..db.database import Database
from .errors import ApiError
from .settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_now(request: Request) -> datetime:
    return request.app.state.clock()  # 테스트에서 고정할 수 있게 앱에 주입한다(결정적 출력)


def current_user(request: Request) -> str:
    """선생님 식별자(owner_id). 인증 전에는 설정의 단일 값(D3). 앞단 인증이 정해지면 여기서 읽는다."""
    return request.app.state.settings.default_owner_id


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
