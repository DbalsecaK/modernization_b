"""Helpers shared by the administration routers."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexti_api.audit import AuditEvent, record
from nexti_api.authz.require import Authorized
from nexti_api.errors import ProblemError
from nexti_core.audit import Outcome
from nexti_core.db.session import scoped_connection


def engine(request: Request) -> AsyncEngine:
    db: AsyncEngine | None = request.app.state.resources.engine
    if db is None:
        raise ProblemError(503, "database_unavailable", "The database is not configured.")
    return db


@asynccontextmanager
async def transaction(request: Request, auth: Authorized) -> AsyncIterator[AsyncConnection]:
    """A transaction with the RLS scope of the authorized session; wakes the OpenFGA relay after commit."""
    async with scoped_connection(engine(request), auth.db_scope()) as conn:
        yield conn
    relay = getattr(request.app.state, "relay", None)
    if relay is not None:
        relay.wake()


async def audit(
    conn: AsyncConnection,
    auth: Authorized,
    action: str,
    target: str,
    details: Mapping[str, Any] | None = None,
    *,
    outcome: Outcome = "success",
    platform: bool = False,
) -> None:
    """Record a sensitive action in the active tenant's chain (or the platform chain)."""
    await record(
        conn,
        AuditEvent(
            action=action,
            outcome=outcome,
            actor_kind="dev-auth" if auth.session.data.auth_method == "dev-auth" else "user",
            actor_id=auth.user_id,
            tenant_id=None if platform else auth.tenant_id,
            target=target,
            details=details or {},
        ),
    )


def not_found(what: str) -> ProblemError:
    return ProblemError(404, f"{what}_not_found", f"The {what.replace('_', ' ')} does not exist.")
