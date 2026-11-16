"""선언적 기반과 모든 리소스 테이블의 공통 열 (웹 REST API 설계 11장)."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class CommonColumns:
    """id(접두사+ULID), owner_id(D3), version(낙관적 잠금), 시각, 소프트 삭제(deleted_at·deleted_with).

    version은 직접 올리지 말고 app.api.repo.update_versioned로만 바꾼다.
    """

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_with: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 함께 지운 부모 id(복구 범위)
