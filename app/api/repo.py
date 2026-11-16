"""저장소 공통 도우미: 소유자·소프트 삭제 조건, 버전 확인 수정, 소프트 삭제 (웹 REST API 설계 3장·4장).

커밋은 하지 않는다. 호출하는 서비스 함수가 session.commit()을 한다.
"""
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .errors import ApiError


def alive(model, owner_id: str) -> tuple:
    """내 것이고 휴지통에 없는 행 조건. 남의 것은 존재하지 않는 것처럼 다룬다(404)."""
    return (model.owner_id == owner_id, model.deleted_at.is_(None))


def update_versioned(session: Session, model, obj_id: str, owner_id: str, expected_version: int, values: dict) -> int:
    """version이 expected_version일 때만 values로 수정하고 version을 1 올린다. 새 version을 돌려준다.

    없거나 남의 것·휴지통이면 404 NOT_FOUND, version이 낡았으면 412 VERSION_CONFLICT.
    """
    if {"id", "owner_id", "version", "created_at", "updated_at", "deleted_at", "deleted_with"} & set(values):
        raise ValueError("공통 열은 update_versioned의 values로 바꿀 수 없다")
    stmt = (update(model)
            .where(model.id == obj_id, *alive(model, owner_id), model.version == expected_version)
            .values(**values, version=model.version + 1, updated_at=func.now())
            .returning(model.version))
    row = session.execute(stmt).first()
    if row is not None:
        return int(row[0])
    exists = session.execute(select(model.id).where(model.id == obj_id, *alive(model, owner_id))).first()
    if exists is None:
        raise ApiError(404, "NOT_FOUND")
    raise ApiError(412, "VERSION_CONFLICT")


def soft_delete(session: Session, model, obj_id: str, owner_id: str, deleted_with: str | None = None) -> None:
    """휴지통으로 보낸다. deleted_with는 함께 지운 부모 id(복구 범위 표시). 없거나 이미 지웠으면 404."""
    stmt = (update(model)
            .where(model.id == obj_id, *alive(model, owner_id))
            .values(deleted_at=func.now(), deleted_with=deleted_with, version=model.version + 1, updated_at=func.now())
            .returning(model.id))
    if session.execute(stmt).first() is None:
        raise ApiError(404, "NOT_FOUND")
