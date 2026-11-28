"""문제지에 부제(subtitle) 열 추가. 첫 쪽 제목 상자에 제목 아래 한 줄로 찍는다.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worksheets", sa.Column("subtitle", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("worksheets", "subtitle")
