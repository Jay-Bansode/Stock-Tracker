"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "instruments",
        sa.Column("instrument_key", sa.String(64), primary_key=True),
        sa.Column("trading_symbol", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("instrument_type", sa.String(16), nullable=False),
        sa.Column("isin", sa.String(16)),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["trading_symbol"])
    # Autocomplete: ILIKE '%q%' over "SYMBOL name" uses this trigram index.
    op.execute(
        "CREATE INDEX ix_instruments_search_trgm ON instruments "
        "USING gin ((trading_symbol || ' ' || name) gin_trgm_ops)"
    )

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "watchlist_id",
            sa.Integer,
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_key",
            sa.String(64),
            sa.ForeignKey("instruments.instrument_key"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text),
        sa.Column("added_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("watchlist_id", "instrument_key"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "watchlist_item_id",
            sa.Integer,
            sa.ForeignKey("watchlist_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("condition", sa.String(8), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("trigger_mode", sa.String(8), nullable=False),
        sa.Column("rearm_pct", sa.Numeric(5, 2), server_default="0.5", nullable=False),
        sa.Column("cooldown_sec", sa.Integer, server_default="900", nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("last_triggered_at", TS),
        sa.Column("last_trigger_price", sa.Numeric(12, 2)),
        sa.Column("trigger_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("condition IN ('ABOVE','BELOW')", name="ck_alerts_condition"),
        sa.CheckConstraint("trigger_mode IN ('ONCE','REPEAT')", name="ck_alerts_trigger_mode"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','TRIGGERED','DISABLED')", name="ck_alerts_status"
        ),
        sa.CheckConstraint("target_price > 0", name="ck_alerts_target_positive"),
    )
    op.create_index("ix_alerts_watchlist_item_id", "alerts", ["watchlist_item_id"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("alert_id", sa.Integer, sa.ForeignKey("alerts.id", ondelete="SET NULL")),
        sa.Column("watchlist_id", sa.Integer),
        sa.Column("watchlist_name", sa.String(100), nullable=False),
        sa.Column("instrument_key", sa.String(64), nullable=False),
        sa.Column("trading_symbol", sa.String(64), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("condition", sa.String(8), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("trigger_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("exchange_ts", TS),
        sa.Column("triggered_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])
    op.create_index("ix_alert_events_watchlist_id", "alert_events", ["watchlist_id"])
    op.create_index("ix_alert_events_trading_symbol", "alert_events", ["trading_symbol"])
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "alert_event_id",
            sa.BigInteger,
            sa.ForeignKey("alert_events.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("next_attempt_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text),
        sa.Column("provider_message_id", sa.String(128)),
        sa.Column("sent_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alert_event_id", "channel"),
    )
    op.create_index(
        "ix_notifications_pending", "notifications", ["channel", "status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("instruments")
