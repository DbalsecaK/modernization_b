"""Integration fixtures: a throwaway, fully migrated database per test session, with two tenants of data.

Skipped when the local services are not configured (run infra/docker-compose/init_env.py and docker compose up).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from nexti_api.db.models import AppUser, AuthzOutbox, Invitation, Membership, Project, Role, RoleAssignment
from nexti_api.settings import API_DIR, Settings
from nexti_api.tenancy import create_tenant

SETTINGS = Settings(app_env="test")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(str(item.fspath)).parent.name == "integration":
            item.add_marker(pytest.mark.integration)
            if not SETTINGS.migration_database_url.get_secret_value():
                item.add_marker(pytest.mark.skip(reason="local services not configured (run init_env.py)"))


def _asyncpg_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@dataclass(frozen=True)
class Databases:
    name: str
    owner_url: URL
    app_url: URL
    relay_url: URL


async def create_database(name: str) -> None:
    owner = make_url(SETTINGS.migration_database_url.get_secret_value())
    conn = await asyncpg.connect(_asyncpg_dsn(owner))
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
        await conn.execute(f'GRANT CONNECT ON DATABASE "{name}" TO platform_app, authz_relay')
        await conn.execute(f'REVOKE ALL ON DATABASE "{name}" FROM PUBLIC')
    finally:
        await conn.close()


async def drop_database(name: str) -> None:
    owner = make_url(SETTINGS.migration_database_url.get_secret_value())
    conn = await asyncpg.connect(_asyncpg_dsn(owner))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


def migrate(owner_url: URL, revision: str = "head", downgrade: bool = False) -> None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", owner_url.render_as_string(hide_password=False).replace("%", "%%"))
    (command.downgrade if downgrade else command.upgrade)(cfg, revision)


@pytest.fixture(scope="session")
def databases() -> Iterator[Databases]:
    name = f"platform_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(create_database(name))
    owner = make_url(SETTINGS.migration_database_url.get_secret_value()).set(database=name)
    app = make_url(SETTINGS.database_url.get_secret_value()).set(database=name)
    relay = app.set(username="authz_relay", password=_relay_password())
    migrate(owner)
    try:
        yield Databases(name, owner, app, relay)
    finally:
        asyncio.run(drop_database(name))


def _relay_password() -> str:
    # The relay password is only in the Compose .env (the API's .env does not need it).
    env = API_DIR.parents[1] / "infra" / "docker-compose" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("AUTHZ_RELAY_PASSWORD="):
            return line.split("=", 1)[1]
    raise RuntimeError("AUTHZ_RELAY_PASSWORD not found in infra/docker-compose/.env")


@pytest.fixture(scope="session")
async def owner_engine(databases: Databases) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(databases.owner_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(databases: Databases) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(databases.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def relay_engine(databases: Databases) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(databases.relay_url)
    yield engine
    await engine.dispose()


@dataclass(frozen=True)
class World:
    """Two tenants. `shared` belongs to both; `a_user` only to A; `b_user` only to B."""

    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    a_user: uuid.UUID
    b_user: uuid.UUID
    shared: uuid.UUID
    project_a: uuid.UUID
    project_b: uuid.UUID
    b_invitee_email: str


async def _user(conn: AsyncConnection, email: str, sub: str) -> uuid.UUID:
    stmt = insert(AppUser).values(email=email, display_name=email.split("@")[0], keycloak_sub=sub)
    return (await conn.execute(stmt.returning(AppUser.id))).scalar_one()


async def _role(conn: AsyncConnection, tenant_id: uuid.UUID, key: str) -> tuple[uuid.UUID, str]:
    from sqlalchemy import select

    row = (await conn.execute(select(Role.id, Role.scope).where(Role.tenant_id == tenant_id, Role.key == key))).one()
    return row.id, row.scope


@pytest.fixture(scope="session")
async def world(owner_engine: AsyncEngine) -> World:
    async with owner_engine.begin() as conn:
        tenant_a = await create_tenant(conn, slug="andes-bank", name="Andes Bank")
        tenant_b = await create_tenant(conn, slug="pacific-cu", name="Pacific Credit Union")
        a_user = await _user(conn, "mtorres@andesbank.example", "sub-a")
        b_user = await _user(conn, "avelez@pacificcu.example", "sub-b")
        shared = await _user(conn, "cruiz@nexti.example", "sub-shared")
        for tenant, user in ((tenant_a, a_user), (tenant_b, b_user), (tenant_a, shared), (tenant_b, shared)):
            await conn.execute(insert(Membership).values(tenant_id=tenant, user_id=user))
        project_a = (
            await conn.execute(insert(Project).values(tenant_id=tenant_a, name="Card Management").returning(Project.id))
        ).scalar_one()
        project_b = (
            await conn.execute(
                insert(Project).values(tenant_id=tenant_b, name="Digital Onboarding").returning(Project.id)
            )
        ).scalar_one()
        admin_a, admin_scope = await _role(conn, tenant_a, "tenantAdmin")
        owner_b, owner_scope = await _role(conn, tenant_b, "projectOwner")
        architect_a, architect_scope = await _role(conn, tenant_a, "architect")
        await conn.execute(
            insert(RoleAssignment),
            [
                {"tenant_id": tenant_a, "user_id": a_user, "role_id": admin_a, "scope": admin_scope,
                 "project_id": None},
                {"tenant_id": tenant_b, "user_id": b_user, "role_id": owner_b, "scope": owner_scope,
                 "project_id": project_b},
                {"tenant_id": tenant_a, "user_id": shared, "role_id": architect_a, "scope": architect_scope,
                 "project_id": project_a},
            ],
        )  # fmt: skip
        invitee = "newcomer@pacificcu.example"
        await conn.execute(
            insert(Invitation).values(
                tenant_id=tenant_b, email=invitee, role_id=owner_b, role_scope=owner_scope, project_id=project_b,
                invited_by=b_user, expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )  # fmt: skip
        await conn.execute(
            insert(Invitation).values(
                tenant_id=tenant_a, email="ljimenez@andesbank.example", role_id=admin_a, role_scope=admin_scope,
                invited_by=a_user, expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )  # fmt: skip
        tuple_ = [{"user": "user:x", "relation": "member", "object": "tenant:y"}]
        await conn.execute(
            insert(AuthzOutbox),
            [
                {"tenant_id": tenant_a, "operation": "write", "tuples": tuple_},
                {"tenant_id": tenant_b, "operation": "write", "tuples": tuple_},
                {"tenant_id": None, "operation": "write", "tuples": tuple_},
            ],
        )
    return World(tenant_a, tenant_b, a_user, b_user, shared, project_a, project_b, invitee)
