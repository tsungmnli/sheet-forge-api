"""B1: exams, pages, segments, jobs

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
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
        "exams", *_common(),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("student", sa.String(100), nullable=False, server_default=""),
        sa.Column("memo", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name="pk_exams"))
    op.create_index("ix_exams_owner_updated", "exams", ["owner_id", "updated_at"])

    op.create_table(
        "pages", *_common(),
        sa.Column("exam_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_ref", sa.String(40), nullable=False),
        sa.Column("corrected_ref", sa.String(40), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("correction", postgresql.JSONB(), nullable=True),
        sa.Column("processing", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pages"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], name="fk_pages_exam_id_exams"))
    op.create_index("ix_pages_exam_position", "pages", ["exam_id", "position"])
    op.create_index("ix_pages_original_ref", "pages", ["original_ref"])
    op.create_index("ix_pages_corrected_ref", "pages", ["corrected_ref"])

    op.create_table(
        "segments", *_common(),
        sa.Column("page_id", sa.String(40), nullable=False),
        sa.Column("exam_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=False),
        sa.Column("number", sa.String(20), nullable=True),
        sa.Column("marked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id", name="pk_segments"),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], name="fk_segments_page_id_pages"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], name="fk_segments_exam_id_exams"))
    op.create_index("ix_segments_page_position", "segments", ["page_id", "position"])
    op.create_index("ix_segments_exam_marked", "segments", ["exam_id", "marked"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(40), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"))
    op.create_index("uq_jobs_active_target", "jobs", ["kind", "target_id"], unique=True,
                    postgresql_where=sa.text("state IN ('queued','running')"))
    op.create_index("ix_jobs_state_run_after", "jobs", ["state", "run_after"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("segments")
    op.drop_table("pages")
    op.drop_table("exams")
