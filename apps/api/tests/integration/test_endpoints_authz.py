"""Every endpoint has an allowed and a denied authorization test against the real OpenFGA (M0 acceptance, rule of
CLAUDE.md), every route declares its authorization, and every sensitive action lands in the audit log."""

import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import (
    AppUser,
    AuditLog,
    Invitation,
    Membership,
    PlatformRoleAssignment,
    Role,
    RoleAssignment,
)

from .conftest import World

# Routes that are public by design (no session): health, the sign-in flow and dev-auth (development only).
PUBLIC = {
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/auth/login"),
    ("GET", "/auth/callback"),
    ("GET", "/auth/dev/users"),
    ("POST", "/auth/dev/login"),
}
# Mutations that are not sensitive actions and therefore not audited.
NOT_AUDITED = {("PATCH", "/api/v1/me")}


def authz_marker(route: APIRoute) -> tuple[str, str] | None:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        marker = getattr(dep.call, "__authz__", None)
        if marker:
            return marker  # type: ignore[no-any-return]
        stack.extend(dep.dependencies)
    return None


def _flatten(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    # Recent FastAPI wraps included routers (_IncludedRouter) instead of copying their routes into app.routes.
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            extra = getattr(route.include_context, "prefix", "") or ""
            yield from _flatten(route.original_router.routes, prefix + extra)


def api_routes(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    found = {(method, path): route for path, route in _flatten(app.routes) for method in route.methods or ()}
    # Guard against a silent pass: the app has dozens of routes.
    assert len(found) > 20, f"route discovery found only {len(found)} routes"
    return found


@dataclass
class Ctx:
    world: World
    root: uuid.UUID
    owner: AsyncEngine

    async def member(self) -> uuid.UUID:
        """A throwaway member of tenant A (for destructive cases)."""
        async with self.owner.begin() as conn:
            user_id: uuid.UUID = (
                await conn.execute(
                    insert(AppUser)
                    .values(email=f"m0test-{uuid.uuid4().hex[:10]}@example.test", display_name="Throwaway")
                    .returning(AppUser.id)
                )
            ).scalar_one()
            await conn.execute(insert(Membership).values(tenant_id=self.world.tenant_a, user_id=user_id))
        return user_id

    async def role(self, key: str) -> uuid.UUID:
        async with self.owner.connect() as conn:
            found: uuid.UUID = (
                await conn.execute(select(Role.id).where(Role.tenant_id == self.world.tenant_a, Role.key == key))
            ).scalar_one()
        return found

    async def custom_role(self) -> uuid.UUID:
        async with self.owner.begin() as conn:
            role_id: uuid.UUID = (
                await conn.execute(
                    insert(Role)
                    .values(tenant_id=self.world.tenant_a, key=f"r{uuid.uuid4().hex[:10]}", scope="tenant", name="Tmp")
                    .returning(Role.id)
                )
            ).scalar_one()
        return role_id

    async def invitation(self) -> uuid.UUID:
        role_id = await self.role("auditor")
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(Invitation)
                    .values(
                        tenant_id=self.world.tenant_a,
                        email=f"m0test-{uuid.uuid4().hex[:10]}@example.test",
                        role_id=role_id,
                        role_scope="tenant",
                        invited_by=self.world.a_user,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    .returning(Invitation.id)
                )
            ).scalar_one()
        return found

    async def assignment(self) -> uuid.UUID:
        user_id = await self.member()
        role_id = await self.role("finance")
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(RoleAssignment)
                    .values(tenant_id=self.world.tenant_a, user_id=user_id, role_id=role_id, scope="tenant")
                    .returning(RoleAssignment.id)
                )
            ).scalar_one()
        return found


Request = tuple[str, dict[str, Any] | None]


@dataclass(frozen=True)
class Case:
    """How to call one route, who may and who may not. `allowed`/`denied` name users of the context."""

    method: str
    path: str
    allowed: str
    denied: str
    make: Callable[[Ctx], Awaitable[Request]]


def fixed(path: str, body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        return path.format(a=ctx.world.tenant_a, shared=ctx.world.shared), body

    return make


async def _new_tenant(ctx: Ctx) -> Request:
    return "/api/v1/tenants", {"slug": f"t-{uuid.uuid4().hex[:10]}", "name": "New tenant"}


async def _patch_member(ctx: Ctx) -> Request:
    return f"/api/v1/users/{await ctx.member()}", {"status": "suspended"}


async def _remove_member(ctx: Ctx) -> Request:
    return f"/api/v1/users/{await ctx.member()}/membership", None


async def _invite(ctx: Ctx) -> Request:
    email = f"m0test-{uuid.uuid4().hex[:10]}@example.test"
    return "/api/v1/invitations", {"email": email, "roleId": str(await ctx.role("auditor"))}


async def _resend(ctx: Ctx) -> Request:
    return f"/api/v1/invitations/{await ctx.invitation()}:resend", None


async def _revoke(ctx: Ctx) -> Request:
    return f"/api/v1/invitations/{await ctx.invitation()}", None


async def _new_role(ctx: Ctx) -> Request:
    return "/api/v1/roles", {"key": f"r{uuid.uuid4().hex[:10]}", "name": "Reviewer", "scope": "tenant"}


async def _rename_role(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}", {"name": "Renamed"}


async def _delete_role(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}", None


async def _role_permissions(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}/permissions", {"permissions": ["audit.view"]}


async def _assign(ctx: Ctx) -> Request:
    return "/api/v1/role-assignments", {"userId": str(await ctx.member()), "roleId": str(await ctx.role("auditor"))}


async def _unassign(ctx: Ctx) -> Request:
    return f"/api/v1/role-assignments/{await ctx.assignment()}", None


# allowed/denied: "root" super administrator; "admin" tenant admin of A; "member" plain member of A (architect in
# one project); "anonymous" no session.
CASES = [
    Case("GET", "/api/v1/tenants", "root", "admin", fixed("/api/v1/tenants")),
    Case("POST", "/api/v1/tenants", "root", "admin", _new_tenant),
    Case("GET", "/api/v1/tenants/{tenant_id}", "root", "admin", fixed("/api/v1/tenants/{a}")),
    Case("PATCH", "/api/v1/tenants/{tenant_id}", "root", "admin", fixed("/api/v1/tenants/{a}", {"name": "Andes Bank"})),
    Case("GET", "/api/v1/users", "admin", "member", fixed("/api/v1/users")),
    Case("GET", "/api/v1/users/{user_id}", "admin", "member", fixed("/api/v1/users/{shared}")),
    Case("PATCH", "/api/v1/users/{user_id}", "admin", "member", _patch_member),
    Case("DELETE", "/api/v1/users/{user_id}/membership", "admin", "member", _remove_member),
    Case("GET", "/api/v1/invitations", "admin", "member", fixed("/api/v1/invitations")),
    Case("POST", "/api/v1/invitations", "admin", "member", _invite),
    Case("POST", "/api/v1/invitations/{invitation_id}:resend", "admin", "member", _resend),
    Case("DELETE", "/api/v1/invitations/{invitation_id}", "admin", "member", _revoke),
    Case("GET", "/api/v1/permissions", "member", "anonymous", fixed("/api/v1/permissions")),
    Case("GET", "/api/v1/roles", "admin", "member", fixed("/api/v1/roles")),
    Case("POST", "/api/v1/roles", "admin", "member", _new_role),
    Case("PATCH", "/api/v1/roles/{role_id}", "admin", "member", _rename_role),
    Case("DELETE", "/api/v1/roles/{role_id}", "admin", "member", _delete_role),
    Case("PUT", "/api/v1/roles/{role_id}/permissions", "admin", "member", _role_permissions),
    Case("GET", "/api/v1/role-assignments", "admin", "member", fixed("/api/v1/role-assignments")),
    Case("POST", "/api/v1/role-assignments", "admin", "member", _assign),
    Case("DELETE", "/api/v1/role-assignments/{assignment_id}", "admin", "member", _unassign),
    Case("GET", "/api/v1/projects", "member", "root", fixed("/api/v1/projects")),
    Case("GET", "/api/v1/audit", "admin", "member", fixed("/api/v1/audit")),
    Case("GET", "/api/v1/audit/export", "admin", "member", fixed("/api/v1/audit/export")),
    Case("GET", "/api/v1/audit/verify", "admin", "member", fixed("/api/v1/audit/verify")),
    Case("GET", "/api/v1/me", "member", "anonymous", fixed("/api/v1/me")),
    Case("PATCH", "/api/v1/me", "member", "anonymous", fixed("/api/v1/me", {"locale": "en"})),
    Case("PUT", "/api/v1/session/tenant", "member", "anonymous", fixed("/api/v1/session/tenant", None)),
    Case("POST", "/auth/logout", "member", "anonymous", fixed("/auth/logout")),
]


@pytest.fixture(scope="module")
async def root(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        user_id: uuid.UUID = (
            await conn.execute(
                insert(AppUser)
                .values(email=f"m0test-root-{uuid.uuid4().hex[:6]}@example.test", display_name="Root")
                .returning(AppUser.id)
            )
        ).scalar_one()
        await conn.execute(insert(PlatformRoleAssignment).values(user_id=user_id, role="superAdmin"))
    return user_id


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(api_settings.model_copy(update={"dev_auth_enabled": True})), base_url="https://testserver"
    ) as client:
        yield client


def act_as(api: TestClient, who: str, ctx: Ctx) -> dict[str, str]:
    """Sign in (dev-auth) and return the headers a browser would send on a mutation."""
    api.cookies.clear()
    if who == "anonymous":
        return {}
    user = {"root": ctx.root, "admin": ctx.world.a_user, "member": ctx.world.shared}[who]
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


async def audit_count(owner: AsyncEngine) -> int:
    async with owner.connect() as conn:
        count: int = (await conn.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    return count


def test_every_route_declares_its_authorization(api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    unmarked = sorted(
        key for key, route in api_routes(app).items() if key not in PUBLIC and authz_marker(route) is None
    )
    assert unmarked == [], f"routes without an authorization dependency: {unmarked}"


def test_every_protected_route_has_an_authorization_case(api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    protected = {key for key in api_routes(app) if key not in PUBLIC}
    covered = {(c.method, c.path) for c in CASES}
    assert protected - covered == set(), "protected routes without an allowed/denied test"
    assert covered - protected == set(), "cases for routes that no longer exist"


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.method} {c.path}")
async def test_allowed_and_denied(
    case: Case,
    api: TestClient,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    fga: OpenFga,
    world: World,
    root: uuid.UUID,
) -> None:
    await reconcile(app_engine, fga)
    ctx = Ctx(world, root, owner_engine)

    headers = act_as(api, case.denied, ctx)
    path, body = await case.make(ctx)
    if case.path == "/api/v1/session/tenant":
        body = {"tenantId": str(world.tenant_a)}
    denied = api.request(case.method, path, json=body, headers=headers)
    assert denied.status_code == (401 if case.denied == "anonymous" else 403), denied.text

    headers = act_as(api, case.allowed, ctx)
    path, body = await case.make(ctx)
    if case.path == "/api/v1/session/tenant":
        body = {"tenantId": str(world.tenant_a)}
    before = await audit_count(owner_engine)
    allowed = api.request(case.method, path, json=body, headers=headers)
    assert allowed.status_code in (200, 201, 204), allowed.text
    if case.method != "GET" and (case.method, case.path) not in NOT_AUDITED:
        assert await audit_count(owner_engine) > before, "a sensitive action left no audit entry"


async def test_an_admin_of_one_tenant_reaches_nothing_of_another(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    await reconcile(app_engine, fga)
    headers = act_as(api, "admin", Ctx(world, root, owner_engine))
    async with owner_engine.connect() as conn:
        b_role = (
            await conn.execute(select(Role.id).where(Role.tenant_id == world.tenant_b, Role.key == "projectOwner"))
        ).scalar_one()
        b_assignment = (
            (await conn.execute(select(RoleAssignment.id).where(RoleAssignment.tenant_id == world.tenant_b)))
            .scalars()
            .first()
        )
        await conn.execute(text("SELECT 1"))

    assert api.get(f"/api/v1/users/{world.b_user}").status_code == 404
    assert api.patch(f"/api/v1/users/{world.b_user}", json={"status": "suspended"}, headers=headers).status_code == 404
    assert api.delete(f"/api/v1/users/{world.b_user}/membership", headers=headers).status_code == 404
    assert str(world.b_user) not in {u["id"] for u in api.get("/api/v1/users").json()}

    assert str(b_role) not in {r["id"] for r in api.get("/api/v1/roles").json()}
    assert api.patch(f"/api/v1/roles/{b_role}", json={"name": "x"}, headers=headers).status_code == 404
    assert api.put(f"/api/v1/roles/{b_role}/permissions", json={"permissions": []}, headers=headers).status_code == 404
    assert api.delete(f"/api/v1/roles/{b_role}", headers=headers).status_code == 404

    assert api.delete(f"/api/v1/role-assignments/{b_assignment}", headers=headers).status_code == 404
    foreign_role = api.post(
        "/api/v1/role-assignments", json={"userId": str(world.shared), "roleId": str(b_role)}, headers=headers
    )
    assert foreign_role.status_code == 404
    developer = await Ctx(world, root, owner_engine).role("developer")
    foreign_project = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(world.shared), "roleId": str(developer), "projectId": str(world.project_b)},
        headers=headers,
    )
    assert foreign_project.status_code in (403, 404)

    assert str(world.project_b) not in {p["id"] for p in api.get("/api/v1/projects").json()}
    assert api.get(f"/api/v1/tenants/{world.tenant_b}").status_code == 403
    assert all(
        e["target"] is None or str(world.tenant_b) not in e["target"] for e in api.get("/api/v1/audit").json()["items"]
    )


async def test_a_project_owner_manages_the_team_of_their_project_only(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    ctx = Ctx(world, root, owner_engine)
    owner_role = await ctx.role("projectOwner")
    async with owner_engine.begin() as conn:
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=world.shared, role_id=owner_role, scope="project",
                project_id=world.project_a,
            )
        )  # fmt: skip
    await reconcile(app_engine, fga)
    headers = act_as(api, "member", ctx)
    newcomer = await ctx.member()
    developer = await ctx.role("developer")
    in_project = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(newcomer), "roleId": str(developer), "projectId": str(world.project_a)},
        headers=headers,
    )
    assert in_project.status_code == 201, in_project.text
    tenant_role = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(newcomer), "roleId": str(await ctx.role("auditor"))},
        headers=headers,
    )
    assert tenant_role.status_code == 403
