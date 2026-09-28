"""dev-auth (spec 15.1, D-27, ADR-0004): sign in as a seeded user without a password, development and test only.

The routes exist only when the API was built with dev-auth enabled, which `create_app` refuses outside
development and test. The session and cookie are the same as with Keycloak; every sign-in is audited as
`dev-auth`. It does not replace Keycloak in the M0 acceptance tests.
"""

import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit import AuditEvent
from nexti_api.auth.routes import audit_platform, set_session_cookie
from nexti_api.auth.session import SessionStore
from nexti_api.auth.users import user_tenants
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_api.settings import Settings
from nexti_core.db.models import AppUser
from nexti_core.db.session import DbScope, scoped_connection

router = APIRouter(prefix="/auth/dev", tags=["dev-auth"])


class DevAuthDisabledError(RuntimeError):
    pass


def ensure_allowed(settings: Settings) -> None:
    """Called at startup: dev-auth outside development/test stops the API from starting."""
    if settings.dev_auth_enabled and not settings.is_local:
        raise DevAuthDisabledError(
            f"DEV_AUTH_ENABLED=true is not allowed with APP_ENV={settings.app_env}; "
            "dev-auth only exists in development and test."
        )


class DevUser(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str


class DevLoginIn(ApiModel):
    user_id: uuid.UUID


def _engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine | None = request.app.state.resources.engine
    if engine is None:
        raise ProblemError(503, "database_unavailable", "The database is not configured.")
    return engine


@router.get("/users", response_model=list[DevUser], summary="Seeded users to sign in as (development only)")
async def dev_users(request: Request) -> list[DevUser]:
    async with scoped_connection(_engine(request), DbScope(platform_scope=True)) as conn:
        rows = await conn.execute(
            select(AppUser.id, AppUser.email, AppUser.display_name)
            .where(AppUser.status == "active")
            .order_by(AppUser.email)
        )
        return [DevUser(id=r.id, email=r.email, display_name=r.display_name) for r in rows]


@router.post("/login", status_code=204, summary="Sign in as a seeded user without a password (development only)")
async def dev_login(request: Request, body: DevLoginIn) -> Response:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != settings.web_origin.rstrip("/"):
        raise ProblemError(403, "origin_not_allowed", "The request comes from an origin that is not allowed.")
    engine = _engine(request)
    async with scoped_connection(engine, DbScope(platform_scope=True)) as conn:
        user = (
            await conn.execute(
                select(AppUser.id, AppUser.email).where(AppUser.id == body.user_id, AppUser.status == "active")
            )
        ).one_or_none()
    if user is None:
        raise ProblemError(404, "user_not_found", "No active user with that id.")
    tenants = await user_tenants(engine, user.id)
    store: SessionStore = request.app.state.sessions
    session_id, _ = await store.create(
        user_id=user.id, auth_method="dev-auth", active_tenant_id=tenants[0].id if tenants else None
    )
    await audit_platform(
        engine,
        AuditEvent(
            action="auth.login", outcome="success", actor_kind="dev-auth", actor_id=user.id, actor_label=user.email,
            details={"method": "dev-auth", "tenants": len(tenants)},
        ),
    )  # fmt: skip
    response = Response(status_code=204)
    set_session_cookie(response, settings, session_id)
    return response
