"""Operational commands: python -m nexti_api.cli <command>"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from nexti_api.seed import seed_dev
from nexti_api.settings import Settings, get_settings


async def _seed_dev(settings: Settings) -> int:
    if not settings.is_local:
        print(f"seed-dev only runs in development or test (APP_ENV={settings.app_env}).", file=sys.stderr)
        return 2
    url = settings.migration_database_url.get_secret_value()
    if not url:
        print("MIGRATION_DATABASE_URL is not set (run infra/docker-compose/init_env.py).", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            seeded = await seed_dev(conn)
    finally:
        await engine.dispose()
    print("Development data seeded." if seeded else "Development data already present; nothing changed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexti_api.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-dev", help="insert the fictitious development data (development/test only)")
    args = parser.parse_args(argv)
    if args.command == "seed-dev":
        return asyncio.run(_seed_dev(get_settings()))
    return 1


if __name__ == "__main__":
    sys.exit(main())
