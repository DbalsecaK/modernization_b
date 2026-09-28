"""The signed-in user: profile, tenants, active tenant and preferences (spec 15.1, 18.6)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit import AuditEvent, record
from nexti_api.auth.routes import actor_kind
from nexti_api.auth.session import AuthMethod, CurrentSession, SessionStore, require_session
from nexti_api.auth.users import TenantRef, load_profile, platform_roles, set_locale, user_tenants
from nexti_api.db.session import DbScope, scoped_connection
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1", tags=["session"])


class TenantOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    locale: Literal["en", "es"]


class MeOut(ApiModel):
    user: UserOut
    active_tenant: TenantOut | None
    tenants: list[TenantOut]
    platform_roles: list[str]
    # Effective permissions in the active tenant, for the menu (filled from OpenFGA in step 8).
    permissions: list[str]
    auth_method: AuthMethod
    # Sent back in X-CSRF-Token on every mutating request.
    csrf_token: str


class MeUpdate(ApiModel):
    locale: Literal["en", "es"]


class ActiveTenantIn(ApiModel):
    tenant_id: uuid.UUID


def _engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine | None = request.app.state.resources.engine
    if engine is None:
        raise ProblemError(503, "database_unavailable", "The database is not configured.")
    return engine


def _tenant_out(t: TenantRef) -> TenantOut:
    return TenantOut(id=t.id, slug=t.slug, name=t.name)


@router.get("/me", response_model=MeOut)
async def me(request: Request, current: Annotated[CurrentSession, Depends(require_session)]) -> MeOut:
    engine = _engine(request)
    session = current.data
    profile = await load_profile(engine, session.user_id)
    if profile is None:
        # Disabled or removed since sign-in: the session ends now.
        await request.app.state.sessions.delete(current.id)
        raise ProblemError(401, "not_authenticated", "Sign in to continue.")
    tenants = await user_tenants(engine, session.user_id)
    active = next((t for t in tenants if t.id == session.active_tenant_id), None)
    if active is None and session.active_tenant_id is not None:
        # The membership of the active tenant was removed or suspended.
        store: SessionStore = request.app.state.sessions
        session = await store.update(current.id, session, active_tenant_id=None)
    return MeOut(
        user=UserOut(id=profile.id, email=profile.email, display_name=profile.display_name, locale=profile.locale),
        active_tenant=_tenant_out(active) if active else None,
        tenants=[_tenant_out(t) for t in tenants],
        platform_roles=await platform_roles(engine, session.user_id),
        permissions=[],
        auth_method=session.auth_method,
        csrf_token=session.csrf_token,
    )


@router.patch("/me", status_code=204)
async def update_me(
    request: Request, body: MeUpdate, current: Annotated[CurrentSession, Depends(require_session)]
) -> None:
    """The language preference persists across sessions and devices (spec 18.6)."""
    await set_locale(_engine(request), current.data.user_id, body.locale)


@router.put("/session/tenant", response_model=TenantOut)
async def switch_tenant(
    request: Request, body: ActiveTenantIn, current: Annotated[CurrentSession, Depends(require_session)]
) -> TenantOut:
    """Change the active tenant. Only tenants with an active membership; every other call derives the
    tenant from the session, never from a parameter."""
    engine = _engine(request)
    tenant = next((t for t in await user_tenants(engine, current.data.user_id) if t.id == body.tenant_id), None)
    if tenant is None:
        raise ProblemError(404, "tenant_not_found", "The tenant does not exist or you are not a member.")
    store: SessionStore = request.app.state.sessions
    await store.update(current.id, current.data, active_tenant_id=tenant.id)
    async with scoped_connection(engine, DbScope(tenant_id=tenant.id, user_id=current.data.user_id)) as conn:
        await record(
            conn,
            AuditEvent(
                action="session.tenant_switch", outcome="success", actor_kind=actor_kind(current),
                actor_id=current.data.user_id, tenant_id=tenant.id, target=f"tenant:{tenant.id}",
            ),
        )  # fmt: skip
    return _tenant_out(tenant)
