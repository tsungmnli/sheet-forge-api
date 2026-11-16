"""DB 연결 (웹 REST API 설계 D1). 쓰기 세션과 내보내기용 읽기 전용 세션을 나눈다."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def normalize_url(url: str) -> str:
    """postgresql:// 형태를 psycopg(3) 드라이버 URL로 바꾼다."""
    for plain in ("postgresql://", "postgres://"):
        if url.startswith(plain):
            return "postgresql+psycopg://" + url[len(plain):]
    return url


def _engine(url: str, pool_size: int, connect_timeout_s: int) -> Engine:
    return create_engine(normalize_url(url), pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True,
                         pool_timeout=10, connect_args={"connect_timeout": max(1, int(connect_timeout_s))})


class Database:
    def __init__(self, url: str, url_ro: str = "", pool_size: int = 5, connect_timeout_s: int = 3):
        self.rw_engine = _engine(url, pool_size, connect_timeout_s)
        # 읽기 계정이 따로 있으면 그 계정으로, 없으면 같은 엔진(세션 수준에서 읽기 전용으로 둔다)
        self.ro_engine = _engine(url_ro, pool_size, connect_timeout_s) if url_ro and url_ro != url else self.rw_engine
        self._rw = sessionmaker(bind=self.rw_engine, expire_on_commit=False)
        self._ro = sessionmaker(bind=self.ro_engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._rw()

    def ro_session(self) -> Session:
        s = self._ro()
        try:
            s.execute(text("SET TRANSACTION READ ONLY"))  # 트랜잭션의 첫 문장이어야 한다
        except Exception:
            s.close()
            raise
        return s

    def check(self) -> None:
        """readiness용. 연결이 안 되면 예외."""
        engines = {id(e): e for e in (self.rw_engine, self.ro_engine)}
        for engine in engines.values():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

    def dispose(self) -> None:
        for engine in {id(e): e for e in (self.rw_engine, self.ro_engine)}.values():
            engine.dispose()
