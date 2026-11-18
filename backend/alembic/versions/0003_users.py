"""user accounts: per-user watchlists/history, password resets, per-user Telegram

Existing data is handed to an admin account seeded from ADMIN_USERNAME / ADMIN_PASSWORD_HASH
(or ADMIN_PASSWORD), ADMIN_EMAIL and TELEGRAM_CHAT_ID, so upgrading loses nothing.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""
import bcrypt
import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _admin_password_hash(settings) -> str | None:
    if settings.admin_password_hash:
        return settings.admin_password_hash
    if settings.admin_password:
        return bcrypt.hashpw(settings.admin_password.encode(), bcrypt.gensalt()).decode()
    return None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("password_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("is_admin", sa.Boolean, server_default="false", nullable=False),
        sa.Column("telegram_chat_id", sa.String(32)),
        sa.Column("telegram_link_code", sa.String(64), unique=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.execute("CREATE UNIQUE INDEX uq_users_username_lower ON users (lower(username))")

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )

    for table in ("watchlists", "alert_events"):
        op.add_column(table, sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    op.add_column("notifications", sa.Column("recipient", sa.String(64)))

    # Seed the admin when credentials are configured, or when there is existing data to own.
    conn = op.get_bind()
    settings = get_settings()
    has_data = conn.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM watchlists) OR EXISTS (SELECT 1 FROM alert_events)"))
    pw_hash = _admin_password_hash(settings)
    if pw_hash or has_data:
        username = (settings.admin_username or "admin").strip()[:32]
        email = (settings.admin_email or f"{username.lower()}@localhost").strip().lower()
        admin_id = conn.scalar(
            sa.text(
                "INSERT INTO users (username, email, password_hash, is_admin, telegram_chat_id) "
                "VALUES (:u, :e, :h, true, :t) RETURNING id"
            ),
            # "!" is never a valid bcrypt hash: the account exists but needs `app.cli set-password`.
            {"u": username, "e": email, "h": pw_hash or "!",
             "t": settings.telegram_chat_id or None},
        )
        conn.execute(sa.text("UPDATE watchlists SET user_id = :id"), {"id": admin_id})
        conn.execute(sa.text("UPDATE alert_events SET user_id = :id"), {"id": admin_id})

    op.alter_column("watchlists", "user_id", nullable=False)
    op.drop_constraint("watchlists_name_key", "watchlists", type_="unique")
    op.create_unique_constraint("uq_watchlists_user_name", "watchlists", ["user_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_watchlists_user_name", "watchlists", type_="unique")
    # Names were only unique per user; keep the oldest of any duplicates' names intact.
    op.execute(
        "UPDATE watchlists w SET name = left(w.name, 90) || ' #' || w.id "
        "WHERE EXISTS (SELECT 1 FROM watchlists o WHERE o.name = w.name AND o.id < w.id)"
    )
    op.create_unique_constraint("watchlists_name_key", "watchlists", ["name"])
    op.drop_column("notifications", "recipient")
    op.drop_column("alert_events", "user_id")
    op.drop_column("watchlists", "user_id")
    op.drop_table("password_reset_tokens")
    op.drop_table("users")
