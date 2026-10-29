import pytest

from app.config import Settings, normalize_database_url


@pytest.mark.parametrize("raw,expected", [
    ("postgresql://u:p@db.example.com:5432/postgres?sslmode=require",
     "postgresql+asyncpg://u:p@db.example.com:5432/postgres?ssl=require"),
    ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
    ("postgres://u:p@pooler:6543/db", "postgresql+asyncpg://u:p@pooler:6543/db?prepared_statement_cache_size=0"),
    ("postgresql+asyncpg://tracker:tracker@localhost:55432/tracker",
     "postgresql+asyncpg://tracker:tracker@localhost:55432/tracker"),
])
def test_database_url_normalization(raw, expected):
    assert normalize_database_url(raw) == expected


def test_asyncpg_dsn_uses_libpq_spelling():
    s = Settings(_env_file=None, database_url="postgresql://u:p@pooler:6543/db?sslmode=require")
    assert s.asyncpg_dsn == "postgresql://u:p@pooler:6543/db?sslmode=require"


@pytest.mark.parametrize("value", ["2027-09-29", "29/09/2027", "29-09-2027"])
def test_token_expiry_accepts_indian_date_formats(value):
    assert str(Settings(_env_file=None, upstox_token_expires_on=value).upstox_token_expires_on) == "2027-09-29"
