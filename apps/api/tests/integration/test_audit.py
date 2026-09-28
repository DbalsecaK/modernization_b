"""Audit log (M0 acceptance): append-only, hash-chained per tenant, tampering detected, isolated by tenant."""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit import AuditEvent, record, verify
from nexti_api.db.session import DbScope, scoped_connection
from nexti_api.tenancy import create_tenant

from .conftest import World


def event(tenant_id: uuid.UUID | None, action: str = "role.assign", **extra: object) -> AuditEvent:
    return AuditEvent(
        action=action,
        outcome="success",
        actor_kind="user",
        tenant_id=tenant_id,
        target="user:x",
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
async def fresh_tenant(owner_engine: AsyncEngine) -> uuid.UUID:
    """A tenant with an empty chain, so each test knows exactly what the chain contains."""
    async with owner_engine.begin() as conn:
        return await create_tenant(conn, slug=f"audit-{uuid.uuid4().hex[:8]}", name="Audit test")


async def write(engine: AsyncEngine, tenant_id: uuid.UUID, n: int) -> list[int | None]:
    seqs: list[int | None] = []
    for i in range(n):
        async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
            seqs.append(await record(conn, event(tenant_id, details={"i": i})))
    return seqs


async def verify_as_tenant(engine: AsyncEngine, tenant_id: uuid.UUID) -> tuple[int, int | None, str | None]:
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
        status = await verify(conn, tenant_id)
    return status.checked, status.first_broken_seq, status.reason


async def test_events_form_a_gapless_verified_chain(app_engine: AsyncEngine, fresh_tenant: uuid.UUID) -> None:
    assert await write(app_engine, fresh_tenant, 5) == [1, 2, 3, 4, 5]
    assert await verify_as_tenant(app_engine, fresh_tenant) == (5, None, None)
    async with scoped_connection(app_engine, DbScope(tenant_id=fresh_tenant)) as conn:
        rows = (await conn.execute(text("SELECT seq, prev_hash, hash FROM audit_log ORDER BY seq"))).all()
    assert rows[0].prev_hash is None
    assert all(rows[i].prev_hash == rows[i - 1].hash for i in range(1, len(rows)))


async def test_the_api_cannot_update_or_delete(app_engine: AsyncEngine, fresh_tenant: uuid.UUID) -> None:
    await write(app_engine, fresh_tenant, 1)
    for sql in ("UPDATE audit_log SET outcome = 'failure'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with scoped_connection(app_engine, DbScope(tenant_id=fresh_tenant)) as conn:
                await conn.execute(text(sql))


@pytest.mark.parametrize(
    "sql", ["UPDATE audit_log SET outcome = 'failure'", "DELETE FROM audit_log", "TRUNCATE audit_log CASCADE"]
)
async def test_not_even_the_owner_can_rewrite_history(owner_engine: AsyncEngine, sql: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_engine.begin() as conn:
            await conn.execute(text(sql))


async def _tamper(owner_engine: AsyncEngine, sql: str, params: dict[str, object]) -> None:
    # Only possible by disabling the trigger, as the owner: exactly the kind of change verify must catch.
    async with owner_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
        await conn.execute(text(sql), params)
        await conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))


async def test_an_altered_row_is_detected(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, fresh_tenant: uuid.UUID
) -> None:
    await write(app_engine, fresh_tenant, 4)
    await _tamper(
        owner_engine,
        "UPDATE audit_log SET outcome = 'denied' WHERE tenant_id = :t AND seq = 3",
        {"t": fresh_tenant},
    )
    assert await verify_as_tenant(app_engine, fresh_tenant) == (2, 3, "hash_mismatch")


async def test_a_deleted_row_is_detected(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, fresh_tenant: uuid.UUID
) -> None:
    await write(app_engine, fresh_tenant, 4)
    await _tamper(owner_engine, "DELETE FROM audit_log WHERE tenant_id = :t AND seq = 2", {"t": fresh_tenant})
    assert await verify_as_tenant(app_engine, fresh_tenant) == (1, 2, "missing_row")


async def test_a_rehashed_row_breaks_the_link_to_the_next(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, fresh_tenant: uuid.UUID
) -> None:
    # Rewriting a row and recomputing its own hash still breaks the next row's prev_hash.
    await write(app_engine, fresh_tenant, 3)
    await _tamper(
        owner_engine,
        "UPDATE audit_log a SET outcome = 'denied', hash = audit_digest(a) WHERE tenant_id = :t AND seq = 2",
        {"t": fresh_tenant},
    )
    _checked, broken, reason = await verify_as_tenant(app_engine, fresh_tenant)
    assert (broken, reason) in {(2, "hash_mismatch"), (3, "prev_hash_mismatch")}


async def test_concurrent_writers_keep_the_chain_intact(app_engine: AsyncEngine, fresh_tenant: uuid.UUID) -> None:
    async def one(i: int) -> int | None:
        async with scoped_connection(app_engine, DbScope(tenant_id=fresh_tenant)) as conn:
            return await record(conn, event(fresh_tenant, details={"i": i}))

    seqs = await asyncio.gather(*(one(i) for i in range(20)))
    assert sorted(s for s in seqs if s is not None) == list(range(1, 21))
    assert await verify_as_tenant(app_engine, fresh_tenant) == (20, None, None)


async def test_an_event_rolls_back_with_its_action(app_engine: AsyncEngine, fresh_tenant: uuid.UUID) -> None:
    # The action fails after the event was written in the same transaction.
    with pytest.raises(RuntimeError):  # noqa: PT012
        async with scoped_connection(app_engine, DbScope(tenant_id=fresh_tenant)) as conn:
            await record(conn, event(fresh_tenant))
            raise RuntimeError("the action failed")
    assert await verify_as_tenant(app_engine, fresh_tenant) == (0, None, None)


async def test_tenants_cannot_read_or_write_each_others_log(app_engine: AsyncEngine, world: World) -> None:
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_b)) as conn:
        await record(conn, event(world.tenant_b, action="project.configure"))
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
        seen: set[object] = set((await conn.execute(text("SELECT DISTINCT tenant_id FROM audit_log"))).scalars())
    assert world.tenant_b not in seen
    with pytest.raises(DBAPIError, match="row-level security"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await record(conn, event(world.tenant_b))
    with pytest.raises(DBAPIError, match="not accessible"):
        async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
            await verify(conn, world.tenant_b)


async def test_platform_events_are_written_from_any_session_but_read_only_with_platform_scope(
    app_engine: AsyncEngine, world: World
) -> None:
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
        await record(conn, event(None, action="auth.login"))
        platform_seen = (await conn.execute(text("SELECT count(*) FROM audit_log WHERE tenant_id IS NULL"))).scalar()
    assert platform_seen == 0
    async with scoped_connection(app_engine, DbScope(platform_scope=True)) as conn:
        status = await verify(conn, None)
        count = (await conn.execute(text("SELECT count(*) FROM audit_log WHERE tenant_id IS NULL"))).scalar()
    assert status.intact
    assert count is not None
    assert count >= 1


async def test_the_request_id_is_recorded(app_engine: AsyncEngine, fresh_tenant: uuid.UUID) -> None:
    import structlog

    structlog.contextvars.bind_contextvars(request_id="req-42")
    try:
        async with scoped_connection(app_engine, DbScope(tenant_id=fresh_tenant)) as conn:
            await record(conn, event(fresh_tenant))
            stored: str = (await conn.execute(text("SELECT request_id FROM audit_log"))).scalar_one()
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    assert stored == "req-42"
