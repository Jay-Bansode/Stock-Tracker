"""optional buying date per watchlist item (for the "Held" duration)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watchlist_items", sa.Column("bought_on", sa.Date))


def downgrade() -> None:
    op.drop_column("watchlist_items", "bought_on")
