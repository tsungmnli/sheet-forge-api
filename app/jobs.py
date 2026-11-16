"""Postgres 작업 큐 (웹 REST API 설계 6장). 같은 대상의 같은 작업은 진행 중에 하나만 쌓인다."""
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db.ids import new_id
from .db.models import Job


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    owner_id: str
    kind: str
    target_type: str
    target_id: str
    attempts: int


_CLAIM = text("""
UPDATE jobs SET state = 'running', attempts = attempts + 1, updated_at = now()
WHERE id = (
    SELECT id FROM jobs
    WHERE (state = 'queued' AND run_after <= now())
       OR (state = 'running' AND updated_at < now() - make_interval(secs => CAST(:stale AS double precision)))
    ORDER BY run_after, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1)
RETURNING id, owner_id, kind, target_type, target_id, attempts
""")


def enqueue(session, owner_id: str, kind: str, target_type: str, target_id: str) -> bool:
    """작업을 쌓는다(커밋은 호출자). 이미 진행 중인 같은 작업이 있으면 False."""
    stmt = (pg_insert(Job)
            .values(id=new_id("job"), owner_id=owner_id, kind=kind, target_type=target_type, target_id=target_id)
            .on_conflict_do_nothing(index_elements=["kind", "target_id"],
                                    index_where=text("state IN ('queued','running')"))
            .returning(Job.id))
    # rowcount는 ORM 방식 INSERT에서 믿을 수 없어, 실제로 들어간 행이 돌아왔는지로 판단한다
    return session.execute(stmt).first() is not None


def claim(db, stale_s: int = 300):
    """다음 작업 하나를 running으로 바꿔 가져간다. 작업자가 죽어 stale_s초 넘게 running인 작업도 다시 가져간다."""
    with db.session() as s:
        row = s.execute(_CLAIM, {"stale": stale_s}).first()
        s.commit()
    return ClaimedJob(*row) if row else None


def complete(db, job_id: str) -> None:
    with db.session() as s:
        s.execute(text("UPDATE jobs SET state='done', updated_at=now() WHERE id=:id"), {"id": job_id})
        s.commit()


def retry_later(db, job_id: str, delay_s: float, error_code: str) -> None:
    with db.session() as s:
        s.execute(text("UPDATE jobs SET state='queued', error_code=:e, updated_at=now(), "
                       "run_after = now() + make_interval(secs => CAST(:d AS double precision)) WHERE id=:id"),
                  {"id": job_id, "e": error_code[:60], "d": delay_s})
        s.commit()


def fail(db, job_id: str, error_code: str) -> None:
    with db.session() as s:
        s.execute(text("UPDATE jobs SET state='failed', error_code=:e, updated_at=now() WHERE id=:id"),
                  {"id": job_id, "e": error_code[:60]})
        s.commit()
