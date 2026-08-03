"""Run ordered PostgreSQL migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import get_settings
from .db import apply_migrations


async def migrate() -> list[int]:
    settings = get_settings()
    migrations = Path(__file__).resolve().parent / "migrations"
    return await apply_migrations(settings.database_url, migrations)


def main() -> None:
    applied = asyncio.run(migrate())
    if applied:
        print("Applied migrations: " + ", ".join(str(item) for item in applied))
    else:
        print("Database schema is current")


if __name__ == "__main__":
    main()
