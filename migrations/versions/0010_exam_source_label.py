"""시험지에 출처(source_label) 열 추가. 내보낼 때 "[대안중 2025기말]"처럼 찍는 인쇄용 이름이다(관리용 제목과 별개).

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exams", sa.Column("source_label", sa.String(100), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("exams", "source_label")
