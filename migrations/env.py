"""Alembic 환경. 연결 주소는 SHEET_FORGE_DATABASE_URL(쓰기 계정)에서 읽는다."""
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
from app.db.database import normalize_url
from app.envfile import load_env_file

load_env_file()  # 저장소 루트의 .env (이미 설정된 환경 변수가 우선)

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("SHEET_FORGE_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("SHEET_FORGE_DATABASE_URL 환경 변수가 필요해요.")
    return normalize_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = dict(config.get_section(config.config_ini_section, {}) or {})
    section["sqlalchemy.url"] = _url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
