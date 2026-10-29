"""Small admin helpers.

  python -m app.cli hash-password            prompt for a password, print ADMIN_PASSWORD_HASH line
  python -m app.cli sync-instruments         download the Upstox instrument master now
"""

import asyncio
import getpass
import sys

import bcrypt


def hash_password() -> None:
    pw = getpass.getpass("Dashboard password: ")
    if pw != getpass.getpass("Repeat: "):
        sys.exit("Passwords do not match")
    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    # Single quotes keep docker compose from interpolating the $ signs in the hash.
    print(f"ADMIN_PASSWORD_HASH='{hashed}'")


async def sync() -> None:
    from app.config import get_settings
    from app.db.session import get_sessionmaker
    from app.marketdata.instruments_sync import sync_instruments

    print(f"synced {await sync_instruments(get_sessionmaker(), get_settings())} instruments")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "hash-password":
        hash_password()
    elif cmd == "sync-instruments":
        asyncio.run(sync())
    else:
        sys.exit(__doc__)
