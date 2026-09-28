"""Operational commands: python -m nexti_api.cli <command>"""

import argparse
import asyncio
import sys

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from nexti_api.audit.keycloak_events import pull_keycloak_events
from nexti_api.authz import fga as fga_module
from nexti_api.authz.reconcile import reconcile
from nexti_api.keycloak_admin import KeycloakAdmin
from nexti_api.seed import seed_dev
from nexti_api.settings import Settings, get_settings


async def _reconcile(settings: Settings, *, apply: bool) -> int:
    url = settings.database_url.get_secret_value()
    if not url or not settings.openfga_url:
        print("DATABASE_URL and OPENFGA_URL are required.", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            fga = await fga_module.connect(http, settings)
            report = await reconcile(engine, fga, apply=apply)
    finally:
        await engine.dispose()
    verb = "Corrected" if apply else "Would correct"
    print(f"{report.expected} expected tuples. {verb}: {len(report.missing)} missing, {len(report.extra)} extra.")
    return 0 if apply or report.in_sync else 1


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
    if settings.openfga_url:
        # The seed writes rows directly; the reconciliation derives their OpenFGA tuples.
        return await _reconcile(settings, apply=True)
    return 0


async def _keycloak_events(settings: Settings) -> int:
    url = settings.database_url.get_secret_value()
    if not url or not settings.keycloak_admin_client_secret.get_secret_value():
        print("DATABASE_URL and KEYCLOAK_ADMIN_CLIENT_SECRET are required.", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            copied = await pull_keycloak_events(engine, KeycloakAdmin(settings, http))
    finally:
        await engine.dispose()
    print(f"{copied} Keycloak events copied to the audit log.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexti_api.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-dev", help="insert the fictitious development data (development/test only)")
    rec = sub.add_parser("reconcile", help="make OpenFGA equal to what PostgreSQL implies")
    rec.add_argument("--check", action="store_true", help="only report differences (exit 1 if any)")
    sub.add_parser("keycloak-events", help="copy new Keycloak events to the audit log")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "seed-dev":
        return asyncio.run(_seed_dev(settings))
    if args.command == "keycloak-events":
        return asyncio.run(_keycloak_events(settings))
    if args.command == "reconcile":
        return asyncio.run(_reconcile(settings, apply=not args.check))
    return 1


if __name__ == "__main__":
    sys.exit(main())
