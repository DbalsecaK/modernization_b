"""Removes from the development database the projects the end-to-end tests create ("E2E ..."), so the projects
list shows the seeded and demo projects (plan P1). Development only; the usage ledger is append-only and keeps its
rows.

    uv run --no-sync python tools/demo/clean.py
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nexti_api.settings import Settings

PATTERN = "E2E %"


async def main() -> int:
    settings = Settings()
    if not settings.is_local:
        print(f"Only in development (APP_ENV={settings.app_env}).", file=sys.stderr)
        return 2
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            ids = (
                (await conn.execute(text("SELECT id FROM project WHERE name LIKE :p"), {"p": PATTERN})).scalars().all()
            )
            for table in ("role_assignment", "invitation"):
                await conn.execute(text(f"DELETE FROM {table} WHERE project_id = ANY(:ids)"), {"ids": list(ids)})  # noqa: S608
            await conn.execute(text("DELETE FROM project WHERE id = ANY(:ids)"), {"ids": list(ids)})
    finally:
        await engine.dispose()
    print(f"Removed {len(ids)} end-to-end test project(s).")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
