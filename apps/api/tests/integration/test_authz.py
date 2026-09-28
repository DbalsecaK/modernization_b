"""OpenFGA sync (M0 acceptance): a role change in the database reaches OpenFGA, and the reconciliation corrects a
forced difference. Plus endpoint authorization with audited denials and effective permissions in /me."""

import uuid
from collections.abc import Iterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz import names
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.names import Tuple
from nexti_api.authz.reconcile import reconcile
from nexti_api.authz.relay import OutboxRelay
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.authz.tuples import expected_tuples
from nexti_api.db.models import Membership, Role, RoleAssignment
from nexti_api.db.session import DbScope, scoped_connection
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import SETTINGS, World


async def role_id(engine: AsyncEngine, tenant_id: uuid.UUID, key: str) -> uuid.UUID:
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
        found: uuid.UUID = (await conn.execute(select(Role.id).where(Role.key == key))).scalar_one()
    return found


async def drain(relay: OutboxRelay) -> None:
    while await relay.run_once():
        pass


async def test_expected_tuples_follow_the_database(app_engine: AsyncEngine, world: World) -> None:
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
        tuples = await expected_tuples(conn, world.tenant_a)
    architect = await role_id(app_engine, world.tenant_a, "architect")
    tenant = names.tenant(world.tenant_a)
    assert Tuple(names.PLATFORM, "platform", tenant) in tuples
    assert Tuple(names.user(world.a_user), "admin", tenant) in tuples
    assert Tuple(names.user(world.shared), "member", tenant) in tuples
    assert Tuple(names.user(world.shared), "assignee", names.binding(world.project_a, architect)) in tuples
    assert (
        Tuple(names.binding_assignees(world.project_a, architect), "signoff_sign", names.project(world.project_a))
        in tuples
    )
    # Nothing of tenant B leaks into A's tuples.
    assert all(str(world.tenant_b) not in t.object and str(world.project_b) not in t.object for t in tuples)


async def test_a_role_change_reaches_openfga(
    app_engine: AsyncEngine, relay_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    relay = OutboxRelay(relay_engine, fga)
    await drain(relay)
    # The test data was seeded without the outbox: bring OpenFGA to the database state first.
    await reconcile(app_engine, fga)
    auditor = await role_id(app_engine, world.tenant_a, "auditor")
    who, tenant = names.user(world.shared), names.tenant(world.tenant_a)
    assert not await fga.check(who, "audit_view", tenant)

    async with (
        scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn,
        authz_change(conn, world.tenant_a),
    ):
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=world.shared, role_id=auditor, scope="tenant"
            )
        )
    await drain(relay)
    assert await fga.check(who, "audit_view", tenant)

    async with (
        scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn,
        authz_change(conn, world.tenant_a),
    ):
        await conn.execute(delete(RoleAssignment).where(RoleAssignment.role_id == auditor))
    await drain(relay)
    assert not await fga.check(who, "audit_view", tenant)


async def test_suspending_a_membership_revokes_every_permission(
    app_engine: AsyncEngine, relay_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    relay = OutboxRelay(relay_engine, fga)
    await reconcile(app_engine, fga)
    project = names.project(world.project_a)
    who = names.user(world.shared)
    assert await fga.check(who, "gate_c3_approve", project)

    async def set_status(status: str) -> None:
        async with (
            scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn,
            authz_change(conn, world.tenant_a),
        ):
            await conn.execute(update(Membership).where(Membership.user_id == world.shared).values(status=status))

    await set_status("suspended")
    await drain(relay)
    assert not await fga.check(who, "gate_c3_approve", project)
    assert not await fga.check(who, "viewer", names.tenant(world.tenant_a))
    await set_status("active")
    await drain(relay)
    assert await fga.check(who, "gate_c3_approve", project)


async def test_nothing_is_enqueued_when_the_change_fails(app_engine: AsyncEngine, world: World) -> None:
    async def outbox_size() -> int:
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            count: int = (await conn.execute(text("SELECT count(*) FROM authz_outbox"))).scalar_one()
        return count

    before = await outbox_size()
    auditor = await role_id(app_engine, world.tenant_a, "auditor")
    with pytest.raises(RuntimeError):  # noqa: PT012 (the failure happens inside the change)
        async with (
            scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn,
            authz_change(conn, world.tenant_a),
        ):
            await conn.execute(
                insert(RoleAssignment).values(
                    tenant_id=world.tenant_a, user_id=world.a_user, role_id=auditor, scope="tenant"
                )
            )
            raise RuntimeError("the action failed")
    assert await outbox_size() == before


async def test_the_relay_keeps_order_and_retries_on_failure(
    app_engine: AsyncEngine, relay_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await drain(OutboxRelay(relay_engine, fga))
    await reconcile(app_engine, fga)
    finance = await role_id(app_engine, world.tenant_a, "finance")
    for change in ("add", "remove"):
        async with (
            scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn,
            authz_change(conn, world.tenant_a),
        ):
            if change == "add":
                await conn.execute(
                    insert(RoleAssignment).values(
                        tenant_id=world.tenant_a, user_id=world.shared, role_id=finance, scope="tenant"
                    )
                )
            else:
                await conn.execute(delete(RoleAssignment).where(RoleAssignment.role_id == finance))

    async with httpx.AsyncClient(timeout=2) as http:
        broken = OpenFga(http, "http://127.0.0.1:9", "", fga.store_id, fga.model_id)
        assert await OutboxRelay(relay_engine, broken).run_once() == 0
    async with relay_engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT status, attempts FROM authz_outbox WHERE status <> 'done' ORDER BY id"))
        ).all()
    # Only the first pending row was attempted; the later one waits for it.
    assert [(r.status, r.attempts) for r in rows] == [("pending", 1), ("pending", 0)]

    await drain(OutboxRelay(relay_engine, fga))
    assert not await fga.check(names.user(world.shared), "cost_view", names.tenant(world.tenant_a))


async def test_reconciliation_corrects_a_forced_difference(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    assert (await reconcile(app_engine, fga, apply=False)).in_sync

    legit = Tuple(names.user(world.a_user), "admin", names.tenant(world.tenant_a))
    rogue = Tuple(names.user(world.b_user), "admin", names.tenant(world.tenant_a))
    await fga.write(writes=[rogue], deletes=[legit])
    assert await fga.check(rogue.user, "users_manage", rogue.object)

    report = await reconcile(app_engine, fga)
    assert report.missing == {legit}
    assert report.extra == {rogue}
    assert not await fga.check(rogue.user, "users_manage", rogue.object)
    assert await fga.check(legit.user, "users_manage", legit.object)
    assert (await reconcile(app_engine, fga, apply=False)).in_sync

    async with owner_engine.connect() as conn:
        details: dict[str, int] = (
            await conn.execute(
                text("SELECT details FROM audit_log WHERE action = 'authz.reconcile' ORDER BY id DESC LIMIT 1")
            )
        ).scalar_one()
    assert details["written"] == 1
    assert details["deleted"] == 1


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))

    @app.get("/test/manage-users")
    async def manage_users(auth: Annotated[Authorized, Depends(require_tenant("users.manage"))]) -> dict[str, str]:
        return {"tenant": str(auth.tenant_id)}

    with TestClient(app, base_url="https://testserver") as client:
        yield client


def sign_in_as(api: TestClient, user_id: uuid.UUID) -> None:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user_id)}).status_code == 204


async def test_endpoint_authorization_allows_denies_and_audits(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    sign_in_as(api, world.a_user)
    allowed = api.get("/test/manage-users")
    assert allowed.status_code == 200
    assert allowed.json() == {"tenant": str(world.tenant_a)}

    sign_in_as(api, world.shared)  # member of A, architect in one project: no tenant permission
    denied = api.get("/test/manage-users")
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT tenant_id, outcome, details FROM audit_log WHERE action = 'authz.deny' "
                    "AND actor_id = :u ORDER BY id DESC LIMIT 1"
                ),
                {"u": world.shared},
            )
        ).one()
    assert row.tenant_id == world.tenant_a
    assert row.outcome == "denied"
    assert row.details["permission"] == "users.manage"


async def test_me_lists_effective_tenant_permissions(
    api: TestClient, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    sign_in_as(api, world.a_user)
    admin = api.get("/api/v1/me").json()["permissions"]
    assert {"users.manage", "audit.view", "cost.view", "project.create"} <= set(admin)
    sign_in_as(api, world.shared)
    assert api.get("/api/v1/me").json()["permissions"] == []


def test_openfga_is_reachable_for_these_tests() -> None:
    assert SETTINGS.openfga_url
