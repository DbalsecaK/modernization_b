"""Tenant isolation at SQL level (M0 acceptance): the runtime role only sees and writes rows of the active tenant."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.db.session import DbScope, scoped_connection

from .conftest import World

TENANT_TABLES = ("membership", "role", "role_permission", "project", "role_assignment", "invitation", "authz_outbox")
AI_TABLES = (
    "provider_connection",
    "model_profile",
    "model_assignment",
    "model_policy",
    "usage_ledger",
    "budget",
    "budget_alert",
)
RLS_TABLES = ("tenant", "app_user", *TENANT_TABLES, *AI_TABLES)


async def ids(engine: AsyncEngine, scope: DbScope, sql: str) -> list[object]:
    async with scoped_connection(engine, scope) as conn:
        return list((await conn.execute(text(sql))).scalars())


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_active_tenant_sees_only_its_rows(app_engine: AsyncEngine, world: World, table: str) -> None:
    scope = DbScope(tenant_id=world.tenant_a, user_id=world.a_user)
    tenants = await ids(app_engine, scope, f"SELECT DISTINCT tenant_id FROM {table}")  # noqa: S608 (fixed list)
    assert tenants == [world.tenant_a]


@pytest.mark.parametrize("table", RLS_TABLES)
async def test_without_scope_nothing_is_visible(app_engine: AsyncEngine, world: World, table: str) -> None:
    assert await ids(app_engine, DbScope(), f"SELECT 1 FROM {table}") == []  # noqa: S608


async def test_writing_into_another_tenant_is_rejected(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(
                text("INSERT INTO project (tenant_id, name) VALUES (:t, 'intruder')"), {"t": world.tenant_b}
            )


async def test_updates_and_deletes_cannot_reach_another_tenant(app_engine: AsyncEngine, world: World) -> None:
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
        updated = await conn.execute(text("UPDATE project SET name = 'x' WHERE id = :p"), {"p": world.project_b})
        deleted = await conn.execute(text("DELETE FROM role_assignment WHERE tenant_id = :t"), {"t": world.tenant_b})
    assert updated.rowcount == 0
    assert deleted.rowcount == 0


async def test_moving_a_row_to_another_tenant_is_rejected(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(
                text("UPDATE project SET tenant_id = :b WHERE id = :p"), {"b": world.tenant_b, "p": world.project_a}
            )


async def test_tenant_switcher_lists_only_own_memberships(app_engine: AsyncEngine, world: World) -> None:
    only_a = await ids(app_engine, DbScope(tenant_id=world.tenant_a, user_id=world.a_user), "SELECT id FROM tenant")
    both = await ids(app_engine, DbScope(tenant_id=world.tenant_a, user_id=world.shared), "SELECT id FROM tenant")
    assert only_a == [world.tenant_a]
    assert set(both) == {world.tenant_a, world.tenant_b}


async def test_users_of_other_tenants_are_invisible(app_engine: AsyncEngine, world: World) -> None:
    visible = await ids(app_engine, DbScope(tenant_id=world.tenant_a, user_id=world.a_user), "SELECT id FROM app_user")
    # Other tests may add members to A; what matters is that B's only user never shows up.
    assert {world.a_user, world.shared} <= set(visible)
    assert world.b_user not in visible


async def test_membership_of_the_shared_user_in_b_is_hidden_from_a(app_engine: AsyncEngine, world: World) -> None:
    rows = await ids(
        app_engine, DbScope(tenant_id=world.tenant_a, user_id=world.a_user), "SELECT tenant_id FROM membership"
    )
    assert world.tenant_b not in rows


async def test_sign_in_scope_sees_only_the_signing_in_user(app_engine: AsyncEngine, world: World) -> None:
    rows = await ids(app_engine, DbScope(auth_sub="sub-b"), "SELECT id FROM app_user")
    assert rows == [world.b_user]
    invites = await ids(app_engine, DbScope(auth_email=world.b_invitee_email.upper()), "SELECT email FROM invitation")
    assert invites == [world.b_invitee_email]


async def test_platform_scope_sees_every_tenant(app_engine: AsyncEngine, world: World) -> None:
    rows = await ids(app_engine, DbScope(platform_scope=True), "SELECT id FROM tenant")
    assert {world.tenant_a, world.tenant_b} <= set(rows)


async def test_invitation_helper_returns_an_existing_user_without_exposing_it(
    app_engine: AsyncEngine, world: World
) -> None:
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a, user_id=world.a_user)) as conn:
        found: object = (
            await conn.execute(text("SELECT ensure_user_for_invitation('AVELEZ@pacificcu.example', 'Ana')"))
        ).scalar_one()
        visible: int = (
            await conn.execute(text("SELECT count(*) FROM app_user WHERE id = :u"), {"u": found})
        ).scalar_one()
    assert found == world.b_user
    assert visible == 0


async def test_invitation_helper_requires_an_active_tenant(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="requires an active tenant"):
        async with scoped_connection(app_engine, DbScope()) as conn:
            await conn.execute(text("SELECT ensure_user_for_invitation('x@y.example', 'X')"))


async def test_catalog_is_read_only_for_the_api(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(text("INSERT INTO permission (key, description) VALUES ('x.y', 'x')"))


async def test_platform_roles_cannot_be_granted_by_the_api(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with scoped_connection(app_engine, DbScope(platform_scope=True)) as conn:
            await conn.execute(
                text("INSERT INTO platform_role_assignment (user_id, role) VALUES (:u, 'superAdmin')"),
                {"u": world.a_user},
            )


async def test_relay_reads_every_outbox_row_and_only_updates_status(relay_engine: AsyncEngine, world: World) -> None:
    async with relay_engine.begin() as conn:
        tenants: set[object] = set((await conn.execute(text("SELECT tenant_id FROM authz_outbox"))).scalars())
        await conn.execute(text("UPDATE authz_outbox SET attempts = attempts + 1 WHERE tenant_id IS NULL"))
    # Other tests add tenants; the relay must see every tenant's rows and the platform ones.
    assert {world.tenant_a, world.tenant_b, None} <= tenants
    with pytest.raises(DBAPIError, match="permission denied"):
        async with relay_engine.begin() as conn:
            await conn.execute(text("UPDATE authz_outbox SET tuples = '[]'::jsonb"))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with relay_engine.begin() as conn:
            await conn.execute(text("SELECT count(*) FROM project"))


async def test_the_api_cannot_rewrite_the_outbox(app_engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(text("UPDATE authz_outbox SET status = 'done'"))


async def role_id_of(engine: AsyncEngine, tenant_id: object, key: str) -> object:
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:  # type: ignore[arg-type]
        role_id: object = (await conn.execute(text("SELECT id FROM role WHERE key = :k"), {"k": key})).scalar_one()
    return role_id


async def test_assignment_needs_a_membership_in_the_same_tenant(app_engine: AsyncEngine, world: World) -> None:
    # b_user is not a member of A: the composite foreign key rejects the assignment even inside A's scope.
    role_id = await role_id_of(app_engine, world.tenant_a, "auditor")
    with pytest.raises(DBAPIError, match="foreign key"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(
                text("INSERT INTO role_assignment (tenant_id, user_id, role_id, scope) VALUES (:t, :u, :r, 'tenant')"),
                {"t": world.tenant_a, "u": world.b_user, "r": role_id},
            )


async def test_a_project_role_needs_a_project_of_the_same_tenant(app_engine: AsyncEngine, world: World) -> None:
    role_id = await role_id_of(app_engine, world.tenant_a, "developer")
    with pytest.raises(DBAPIError, match="foreign key"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await conn.execute(
                text(
                    "INSERT INTO role_assignment (tenant_id, user_id, role_id, scope, project_id) "
                    "VALUES (:t, :u, :r, 'project', :p)"
                ),
                {"t": world.tenant_a, "u": world.shared, "r": role_id, "p": world.project_b},
            )
