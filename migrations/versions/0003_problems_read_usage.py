"""B2: problems, read_usage

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _common():
    return [
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_with", sa.String(40), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "problems", *_common(),
        sa.Column("exam_id", sa.String(40), nullable=False),
        sa.Column("segment_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="recognizing"),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("points", sa.Float(), nullable=True),
        sa.Column("recognized", postgresql.JSONB(), nullable=True),
        sa.Column("ocr_meta", postgresql.JSONB(), nullable=True),
        sa.Column("crop_ref", sa.String(40), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name="pk_problems"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], name="fk_problems_exam_id_exams"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], name="fk_problems_segment_id_segments"))
    # 한 칸에 살아 있는 문제는 하나(중복 읽기 방지)
    op.create_index("uq_problems_segment_alive", "problems", ["segment_id"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_problems_exam_status", "problems", ["exam_id", "status"])
    op.create_index("ix_problems_crop_ref", "problems", ["crop_ref"])

    op.create_table(
        "read_usage",
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("owner_id", "day", name="pk_read_usage"))


def downgrade() -> None:
    op.drop_table("read_usage")
    op.drop_table("problems")
