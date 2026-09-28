"""Transactions with the Row-Level Security variables set (SET LOCAL: they end with the transaction).

This is the only way the API gets a database connection for business data; without an active tenant the
policies return no rows (fail closed).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@dataclass(frozen=True)
class DbScope:
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # Only after OpenFGA confirmed a platform role for the user.
    platform_scope: bool = False
    # During sign-in, before the platform user id is known (validated ID token claims).
    auth_sub: str | None = None
    auth_email: str | None = None


_SET_SCOPE = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), set_config('app.user_id', :user_id, true), "
    "set_config('app.platform_scope', :platform_scope, true), set_config('app.auth_sub', :auth_sub, true), "
    "set_config('app.auth_email', :auth_email, true)"
)


def _params(scope: DbScope) -> dict[str, str]:
    return {
        "tenant_id": str(scope.tenant_id) if scope.tenant_id else "",
        "user_id": str(scope.user_id) if scope.user_id else "",
        "platform_scope": "on" if scope.platform_scope else "",
        "auth_sub": scope.auth_sub or "",
        "auth_email": (scope.auth_email or "").lower(),
    }


async def apply_scope(conn: AsyncConnection, scope: DbScope) -> None:
    """Change the scope inside an open transaction (e.g. accepting invitations of several tenants at sign-in)."""
    await conn.execute(_SET_SCOPE, _params(scope))


@asynccontextmanager
async def scoped_connection(engine: AsyncEngine, scope: DbScope) -> AsyncIterator[AsyncConnection]:
    """One transaction with the given scope; commits on success, rolls back on error."""
    async with engine.begin() as conn:
        await apply_scope(conn, scope)
        yield conn
