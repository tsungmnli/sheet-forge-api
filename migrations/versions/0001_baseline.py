"""baseline: pg_trgm 확장 (문제 검색용, 웹 REST API 설계 13장 13번)

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm은 PostgreSQL 13+에서 데이터베이스 CREATE 권한만 있으면 만들 수 있는 trusted 확장이다.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    pass  # 확장은 다른 객체가 쓸 수 있으므로 지우지 않는다
