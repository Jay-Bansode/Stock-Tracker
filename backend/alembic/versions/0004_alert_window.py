"""per-alert daily check window (only at a time / between two times, IST)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("check_from", sa.Time))
    op.add_column("alerts", sa.Column("check_until", sa.Time))


def downgrade() -> None:
    op.drop_column("alerts", "check_until")
    op.drop_column("alerts", "check_from")
