"""Schema guarantees (M0 acceptance): no credentials stored, RLS everywhere, catalog and ORM in sync."""

import asyncio
import re
import uuid
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.authz_catalog import PERMISSIONS
from nexti_core.db.models import Base

from .conftest import SETTINGS, Databases, create_database, drop_database, migrate

# The platform never stores passwords, MFA secrets or tokens (spec 15.1, rule 11): they live in Keycloak/Redis.
CREDENTIAL_COLUMN = re.compile(r"pass(word|wd)?|pwd|secret|otp|totp|mfa|recovery|credential|token|api_?key", re.I)


async def test_no_column_can_hold_credentials(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        columns: list[str] = list(
            (
                await conn.execute(
                    text(
                        "SELECT table_name || '.' || column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).scalars()
        )
        offending = [c for c in columns if CREDENTIAL_COLUMN.search(c.split(".", 1)[1])]
    assert offending == []


async def test_every_table_with_tenant_id_has_forced_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("""
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM information_schema.columns col
                               WHERE col.table_schema = 'public' AND col.table_name = c.relname
                                 AND col.column_name = 'tenant_id') AS has_tenant
                FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
                """)
            )
        ).all()
    must_have_rls = {r.relname for r in rows if r.has_tenant} | {"tenant", "app_user"}
    missing = sorted(
        r.relname for r in rows if r.relname in must_have_rls and not (r.relrowsecurity and r.relforcerowsecurity)
    )
    assert missing == []
    assert must_have_rls >= {"membership", "role", "role_assignment", "project", "invitation", "authz_outbox"}


async def test_runtime_roles_cannot_bypass_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        query = text(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname IN ('platform_app', 'authz_relay') AND (rolbypassrls OR rolsuper)"
        )
        rows: list[str] = list((await conn.execute(query)).scalars())
        assert rows == []


async def test_permission_catalog_matches_nexti_core(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT permission_key, scope FROM permission_scope"))).all()
    in_db = {(r.permission_key, r.scope) for r in rows}
    in_code = {(p.key, scope) for p in PERMISSIONS for scope in p.scopes}
    assert in_db == in_code


def _diffs(connection: Connection) -> list[Any]:
    ctx = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": False})
    return list(compare_metadata(ctx, Base.metadata))


async def test_orm_models_match_the_migrations(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        diffs = await conn.run_sync(_diffs)
    # alembic_version belongs to Alembic, not to the models.
    diffs = [d for d in diffs if not (d[0] == "remove_table" and d[1].name == "alembic_version")]
    assert diffs == []


def test_downgrade_to_nothing_and_upgrade_again(databases: Databases) -> None:
    name = f"platform_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(create_database(name))
    try:
        owner = databases.owner_url.set(database=name)
        migrate(owner)
        migrate(owner, "base", downgrade=True)
        migrate(owner)
    finally:
        asyncio.run(drop_database(name))
    assert SETTINGS.migration_database_url.get_secret_value()
