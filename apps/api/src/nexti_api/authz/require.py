"""Endpoint authorization (spec 16.4): every protected endpoint declares one of these dependencies.

The user and the tenant always come from the session. Denials are audited. Each dependency carries an
`__authz__` marker so a test can prove that no route is left without authorization.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request

from nexti_api.audit import AuditEvent, record
from nexti_api.auth.session import CurrentSession, require_session
from nexti_api.authz import names
from nexti_api.authz.fga import OpenFga
from nexti_api.errors import ProblemError
from nexti_core.authz_catalog import permission_scopes
from nexti_core.db.session import DbScope, scoped_connection


@dataclass(frozen=True)
class Authorized:
    """What an endpoint may rely on after authorization."""

    session: CurrentSession
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    platform_scope: bool = False

    def db_scope(self) -> DbScope:
        return DbScope(tenant_id=self.tenant_id, user_id=self.user_id, platform_scope=self.platform_scope)


def _fga(request: Request) -> OpenFga:
    fga: OpenFga | None = request.app.state.fga
    if fga is None:
        raise ProblemError(503, "authorization_unavailable", "Authorization is not available.")
    return fga


async def deny(request: Request, current: CurrentSession, tenant_id: uuid.UUID | None, what: str, target: str) -> None:
    async with scoped_connection(request.app.state.resources.engine, DbScope(tenant_id=tenant_id)) as conn:
        await record(
            conn,
            AuditEvent(
                action="authz.deny",
                outcome="denied",
                actor_kind="dev-auth" if current.data.auth_method == "dev-auth" else "user",
                actor_id=current.data.user_id,
                tenant_id=tenant_id,
                target=target,
                details={"permission": what, "method": request.method, "path": request.url.path},
            ),
        )
    raise ProblemError(403, "forbidden", "You do not have permission to do this.")


Dependency = Callable[..., Awaitable[Authorized]]


def _mark(dependency: Any, kind: str, permission: str) -> Dependency:
    dependency.__authz__ = (kind, permission)
    typed: Dependency = dependency
    return typed


def require_tenant(permission: str) -> Dependency:
    """A tenant-level permission (e.g. users.manage) on the active tenant of the session."""
    if "tenant" not in permission_scopes().get(permission, ()) and permission != "tenant.view":
        raise ValueError(f"{permission} is not a tenant permission")
    rel = "viewer" if permission == "tenant.view" else names.relation(permission)

    async def dependency(request: Request, current: Annotated[CurrentSession, Depends(require_session)]) -> Authorized:
        tenant_id = current.data.active_tenant_id
        if tenant_id is None:
            raise ProblemError(403, "no_active_tenant", "Select a tenant first.")
        if not await _fga(request).check(names.user(current.data.user_id), rel, names.tenant(tenant_id)):
            await deny(request, current, tenant_id, permission, names.tenant(tenant_id))
        return Authorized(current, current.data.user_id, tenant_id)

    return _mark(dependency, "tenant", permission)


def require_project(permission: str) -> Dependency:
    """A project-level permission on the project of the path (`project_id`), within the active tenant."""
    if "project" not in permission_scopes().get(permission, ()) and permission != "project.view":
        raise ValueError(f"{permission} is not a project permission")
    rel = "viewer" if permission == "project.view" else names.relation(permission)

    async def dependency(
        request: Request, project_id: uuid.UUID, current: Annotated[CurrentSession, Depends(require_session)]
    ) -> Authorized:
        tenant_id = current.data.active_tenant_id
        if tenant_id is None:
            raise ProblemError(403, "no_active_tenant", "Select a tenant first.")
        if not await _fga(request).check(names.user(current.data.user_id), rel, names.project(project_id)):
            await deny(request, current, tenant_id, permission, names.project(project_id))
        # The project may still belong to another tenant where the user also works: RLS on the active tenant
        # hides it from every query that follows.
        return Authorized(current, current.data.user_id, tenant_id)

    return _mark(dependency, "project", permission)


def require_platform(role: str = "superAdmin") -> Dependency:
    """A platform role (NexTI operators). Grants platform scope to the database session."""
    rel = names.PLATFORM_RELATION[role]  # type: ignore[index]

    async def dependency(request: Request, current: Annotated[CurrentSession, Depends(require_session)]) -> Authorized:
        if not await _fga(request).check(names.user(current.data.user_id), rel, names.PLATFORM):
            await deny(request, current, None, f"platform.{role}", names.PLATFORM)
        return Authorized(current, current.data.user_id, current.data.active_tenant_id, platform_scope=True)

    return _mark(dependency, "platform", role)


def authenticated() -> Dependency:
    """Only a session (e.g. /me). Explicit so that 'no authorization' is always a decision."""

    async def dependency(current: Annotated[CurrentSession, Depends(require_session)]) -> Authorized:
        return Authorized(current, current.data.user_id, current.data.active_tenant_id)

    return _mark(dependency, "session", "")


TENANT_RELATIONS = sorted({names.relation(k) for k, scopes in permission_scopes().items() if "tenant" in scopes})


async def effective_tenant_permissions(fga: OpenFga, user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[str]:
    """Tenant permissions of the user in the tenant, as permission keys (for the menu)."""
    allowed = await fga.batch_check(names.user(user_id), names.tenant(tenant_id), TENANT_RELATIONS)
    return sorted(names.permission_key(r) for r, ok in allowed.items() if ok)
