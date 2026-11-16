"""B4: pages.original_ref nullable (보존 기간이 지나면 원본만 지움)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pages", "original_ref", existing_type=sa.String(40), nullable=True)


def downgrade() -> None:
    # 원본이 이미 지워진 행(null)이 있으면 실패한다. 그런 행은 되돌릴 수 없다.
    op.alter_column("pages", "original_ref", existing_type=sa.String(40), nullable=False)
