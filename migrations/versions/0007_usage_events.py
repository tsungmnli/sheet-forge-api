"""B5-3c: usage_events (호출 한 번 = 한 줄. 월 비용 확인용, 설계 8.1·9장)

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("job_kind", sa.String(20), nullable=False),     # page_process | problem_read | problem_reread
        sa.Column("target_id", sa.String(40), nullable=False),    # 사진 또는 문제 id
        sa.Column("call", sa.String(10), nullable=False),         # segment | read | repair
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thinking_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_usage_events"),
    )
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_table("usage_events")
