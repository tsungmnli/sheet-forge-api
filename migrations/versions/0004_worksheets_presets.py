"""B3: worksheets, worksheet_items, export_presets

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
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
        "worksheets", *_common(),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("student", sa.String(100), nullable=False, server_default=""),
        sa.Column("preset", postgresql.JSONB(), nullable=False),
        sa.Column("header", postgresql.JSONB(), nullable=False),
        sa.Column("unconfirmed_policy", sa.String(8), nullable=False, server_default="skip"),
        sa.Column("last_export", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_worksheets"),
    )
    op.create_index("ix_worksheets_owner_updated", "worksheets", ["owner_id", "updated_at"])
    op.create_table(
        "worksheet_items",
        sa.Column("worksheet_id", sa.String(40), nullable=False),
        sa.Column("problem_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["worksheet_id"], ["worksheets.id"],
                                name="fk_worksheet_items_worksheet_id_worksheets"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"],
                                name="fk_worksheet_items_problem_id_problems"),
        sa.PrimaryKeyConstraint("worksheet_id", "problem_id", name="pk_worksheet_items"),
    )
    op.create_index("ix_worksheet_items_pos", "worksheet_items", ["worksheet_id", "position"])
    op.create_index("ix_worksheet_items_problem", "worksheet_items", ["problem_id"])
    op.create_table(
        "export_presets", *_common(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("preset", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_export_presets"),
    )
    op.create_index("ix_export_presets_owner", "export_presets", ["owner_id"])


def downgrade() -> None:
    op.drop_table("export_presets")
    op.drop_table("worksheet_items")
    op.drop_table("worksheets")
