"""Invitations end to end: Keycloak account and e-mail (Mailpit), acceptance at the first sign-in, revocation,
expiry and tenant isolation."""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz import names
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.db.models import Invitation, Membership, Role, RoleAssignment
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import SETTINGS, World, compose_env, keycloak_admin_headers
from .test_auth_flow import PASSWORD, as_local_path, keycloak_sign_in

MAILPIT = f"http://127.0.0.1:{compose_env('MAILPIT_UI_PORT')}"


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def as_admin(api: TestClient, world: World) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(world.a_user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


async def role_id(owner: AsyncEngine, tenant_id: uuid.UUID, key: str) -> uuid.UUID:
    async with owner.connect() as conn:
        found: uuid.UUID = (
            await conn.execute(select(Role.id).where(Role.tenant_id == tenant_id, Role.key == key))
        ).scalar_one()
    return found


def new_email() -> str:
    return f"m0test-{uuid.uuid4().hex[:10]}@example.test"


async def mails_to(address: str) -> int:
    async with httpx.AsyncClient(timeout=10) as http:
        for _ in range(20):
            res = await http.get(f"{MAILPIT}/api/v1/search", params={"query": f'to:"{address}"'})
            count: int = res.json().get("messages_count", 0)
            if count:
                return count
            await asyncio.sleep(0.25)
    return 0


async def complete_keycloak_actions(email: str) -> None:
    """What the invitee does through the e-mailed link and the first Keycloak pages: set a password, verify the
    e-mail and complete the profile (Keycloak 26 asks for first and last name)."""
    base = f"{SETTINGS.keycloak_url}/admin/realms/{SETTINGS.keycloak_realm}"
    async with httpx.AsyncClient(timeout=10) as http:
        headers = await keycloak_admin_headers(http)
        user = (await http.get(f"{base}/users", params={"email": email, "exact": "true"}, headers=headers)).json()[0]
        assert set(user["requiredActions"]) == {"UPDATE_PASSWORD", "VERIFY_EMAIL"}
        await http.put(
            f"{base}/users/{user['id']}",
            json={"emailVerified": True, "requiredActions": [], "firstName": "Invited", "lastName": "Person"},
            headers=headers,
        )
        res = await http.put(
            f"{base}/users/{user['id']}/reset-password",
            json={"type": "password", "value": PASSWORD, "temporary": False},
            headers=headers,
        )
        assert res.status_code == 204


async def test_invite_then_first_sign_in_activates_membership_and_role(
    api: TestClient, owner_engine: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = as_admin(api, world)
    email = new_email()
    architect = await role_id(owner_engine, world.tenant_a, "architect")
    created = api.post(
        "/api/v1/invitations",
        json={
            "email": email,
            "displayName": "New Architect",
            "roleId": str(architect),
            "projectId": str(world.project_a),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"
    assert created.json()["emailSent"] is True
    assert await mails_to(email) >= 1

    # Invited, not yet a member: no access.
    listed = api.get("/api/v1/users").json()
    invitee = next(u for u in listed if u["email"] == email)
    assert invitee["status"] == "invited"

    await complete_keycloak_actions(email)
    api.cookies.clear()
    start = api.get("/auth/login", follow_redirects=False)
    callback = keycloak_sign_in(start.headers["location"], email, PASSWORD)
    assert api.get(as_local_path(callback), follow_redirects=False).status_code == 302

    me = api.get("/api/v1/me").json()
    assert me["activeTenant"]["id"] == str(world.tenant_a)
    async with owner_engine.connect() as conn:
        status = (await conn.execute(select(Invitation.status).where(Invitation.email == email))).scalar_one()
        grants = (
            (
                await conn.execute(
                    select(RoleAssignment.project_id).where(RoleAssignment.user_id == uuid.UUID(me["user"]["id"]))
                )
            )
            .scalars()
            .all()
        )
    assert status == "accepted"
    assert list(grants) == [world.project_a]

    who, project = names.user(uuid.UUID(me["user"]["id"])), names.project(world.project_a)
    for _ in range(40):  # the relay publishes in the background
        if await fga.check(who, "gate_c3_approve", project):
            break
        await asyncio.sleep(0.25)
    assert await fga.check(who, "gate_c3_approve", project)


async def test_inviting_a_member_or_twice_is_refused(api: TestClient, owner_engine: AsyncEngine, world: World) -> None:
    headers = as_admin(api, world)
    auditor = await role_id(owner_engine, world.tenant_a, "auditor")
    member = api.post(
        "/api/v1/invitations", json={"email": "cruiz@nexti.example", "roleId": str(auditor)}, headers=headers
    )
    assert member.json()["code"] == "already_member"
    email = new_email()
    assert (
        api.post("/api/v1/invitations", json={"email": email, "roleId": str(auditor)}, headers=headers).status_code
        == 201
    )
    again = api.post("/api/v1/invitations", json={"email": email, "roleId": str(auditor)}, headers=headers)
    assert again.json()["code"] == "invitation_pending"


async def test_revoking_removes_the_placeholder_membership(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    headers = as_admin(api, world)
    email = new_email()
    auditor = await role_id(owner_engine, world.tenant_a, "auditor")
    invitation = api.post("/api/v1/invitations", json={"email": email, "roleId": str(auditor)}, headers=headers).json()
    assert api.delete(f"/api/v1/invitations/{invitation['id']}", headers=headers).status_code == 204
    assert email not in {u["email"] for u in api.get("/api/v1/users").json()}
    listed = {i["id"]: i["status"] for i in api.get("/api/v1/invitations").json()}
    assert listed[invitation["id"]] == "revoked"
    assert api.delete(f"/api/v1/invitations/{invitation['id']}", headers=headers).status_code == 404


async def test_an_expired_invitation_is_not_accepted(api: TestClient, owner_engine: AsyncEngine, world: World) -> None:
    headers = as_admin(api, world)
    email = new_email()
    auditor = await role_id(owner_engine, world.tenant_a, "auditor")
    invitation = api.post("/api/v1/invitations", json={"email": email, "roleId": str(auditor)}, headers=headers).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            update(Invitation)
            .where(Invitation.id == uuid.UUID(invitation["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    await complete_keycloak_actions(email)
    api.cookies.clear()
    start = api.get("/auth/login", follow_redirects=False)
    api.get(as_local_path(keycloak_sign_in(start.headers["location"], email, PASSWORD)), follow_redirects=False)
    me = api.get("/api/v1/me").json()
    assert me["tenants"] == []
    async with owner_engine.connect() as conn:
        status = (await conn.execute(select(Invitation.status).where(Invitation.email == email))).scalar_one()
    assert status == "expired"


async def test_invitations_of_another_tenant_are_out_of_reach(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    b_owner = await role_id(owner_engine, world.tenant_b, "projectOwner")
    async with owner_engine.begin() as conn:
        b_invitation = (
            await conn.execute(
                insert(Invitation)
                .values(
                    tenant_id=world.tenant_b, email=new_email(), role_id=b_owner, role_scope="project",
                    project_id=world.project_b, invited_by=world.b_user,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
                .returning(Invitation.id)
            )
        ).scalar_one()  # fmt: skip
    headers = as_admin(api, world)
    assert str(b_invitation) not in {i["id"] for i in api.get("/api/v1/invitations").json()}
    assert api.delete(f"/api/v1/invitations/{b_invitation}", headers=headers).status_code == 404
    assert api.post(f"/api/v1/invitations/{b_invitation}:resend", headers=headers).status_code == 404
    foreign_role = api.post("/api/v1/invitations", json={"email": new_email(), "roleId": str(b_owner)}, headers=headers)
    assert foreign_role.status_code in (403, 404)
    async with owner_engine.connect() as conn:
        members_b = (
            (await conn.execute(select(Membership.status).where(Membership.tenant_id == world.tenant_b)))
            .scalars()
            .all()
        )
    assert "invited" not in members_b
