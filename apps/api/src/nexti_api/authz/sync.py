"""The single way to change roles, memberships or projects: inside `authz_change`, which writes the OpenFGA diff
to the outbox in the same transaction as the business rows (ADR-0001)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.authz.names import Tuple
from nexti_api.authz.tuples import expected_tuples
from nexti_core.db.models import AuthzOutbox


async def enqueue(conn: AsyncConnection, tenant_id: uuid.UUID | None, writes: set[Tuple], deletes: set[Tuple]) -> int:
    """Store the diff for the relay. Returns how many outbox rows were written (0, 1 or 2)."""
    rows = []
    if deletes:
        rows.append({"tenant_id": tenant_id, "operation": "delete", "tuples": [t.as_key() for t in sorted(deletes)]})
    if writes:
        rows.append({"tenant_id": tenant_id, "operation": "write", "tuples": [t.as_key() for t in sorted(writes)]})
    if rows:
        await conn.execute(insert(AuthzOutbox), rows)
    return len(rows)


@asynccontextmanager
async def authz_change(conn: AsyncConnection, tenant_id: uuid.UUID) -> AsyncIterator[None]:
    """Wrap any change of a tenant's roles, permissions, memberships or projects:

        async with authz_change(conn, tenant_id):
            await conn.execute(insert(RoleAssignment)...)

    The tuples implied before and after are compared and the difference goes to the outbox. If the block
    raises, nothing is enqueued (and the caller's transaction rolls back).
    """
    before = await expected_tuples(conn, tenant_id)
    yield
    after = await expected_tuples(conn, tenant_id)
    await enqueue(conn, tenant_id, writes=after - before, deletes=before - after)
