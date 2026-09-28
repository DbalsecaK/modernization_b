import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from nexti_api.cli import main
from nexti_api.db.models import AppUser, RoleAssignment, Tenant
from nexti_api.seed import ASSIGNMENTS, TENANTS, USERS, seed_dev
from nexti_api.settings import Settings

from .conftest import Databases, create_database, drop_database, migrate


def test_seed_dev_is_idempotent(databases: Databases) -> None:
    name = f"platform_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(create_database(name))
    try:
        owner = databases.owner_url.set(database=name)
        migrate(owner)

        async def run() -> tuple[bool, bool, int, int, int]:
            engine = create_async_engine(owner)
            try:
                async with engine.begin() as conn:
                    first = await seed_dev(conn)
                async with engine.begin() as conn:
                    second = await seed_dev(conn)
                    counts = [
                        (await conn.execute(select(func.count()).select_from(model))).scalar_one()
                        for model in (Tenant, AppUser, RoleAssignment)
                    ]
            finally:
                await engine.dispose()
            return first, second, counts[0], counts[1], counts[2]

        first, second, tenants, users, assignments = asyncio.run(run())
    finally:
        asyncio.run(drop_database(name))
    assert (first, second) == (True, False)
    assert (tenants, users, assignments) == (len(TENANTS), len(USERS), len(ASSIGNMENTS))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_seed_dev_refuses_outside_development(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setattr("nexti_api.cli.get_settings", lambda: Settings(_env_file=None, app_env=app_env))
    assert main(["seed-dev"]) == 2
