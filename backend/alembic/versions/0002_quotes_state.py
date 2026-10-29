"""quotes + system_state for cron (free-hosting) mode

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("instrument_key", sa.String(64), primary_key=True),
        sa.Column("ltp", sa.Numeric(12, 2), nullable=False),
        sa.Column("close", sa.Numeric(12, 2)),
        sa.Column("ts", TS),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "system_state",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_state")
    op.drop_table("quotes")
