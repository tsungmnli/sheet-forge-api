"""문제지의 header(위쪽 제목칸) 열 제거. 머리글은 MVP에서 뺐다(2026-11-16).

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("worksheets", "header")


def downgrade() -> None:
    op.add_column("worksheets", sa.Column("header", postgresql.JSONB(), nullable=False,
                                          server_default=sa.text("'{}'::jsonb")))
