"""SCIM 2.0 per tenant against the real database, OpenFGA, Redis and Keycloak (M16 acceptance, ADR-0031).

An identity provider creates, finds, updates and deactivates the users and groups of its tenant and of no other; its
groups give tenant roles through the identity providers' mapping; a revoked bearer or one of another tenant gets 401;
every change is audited and the bearer is never stored in clear.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.auth.session import SessionStore
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.scim import protocol
from nexti_api.settings import Settings
from nexti_core.db.models import (
    AppUser,
    AuditLog,
    Membership,
    Role,
    RoleAssignment,
    ScimAccess,
    TenantIdentity,
    TenantIdentityProvider,
)

from .conftest import SETTINGS, World, keycloak_admin_headers

pytestmark = pytest.mark.skipif(
    not SETTINGS.keycloak_admin_client_secret.get_secret_value(), reason="Keycloak admin is not configured"
)
GROUP = "NexTI Auditors"  # mapped to the tenant role `auditor` by a provider of tenant A
KC_BASE = f"{SETTINGS.keycloak_url}/admin/realms/{SETTINGS.keycloak_realm}"


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings.model_copy(update={"dev_auth_enabled": True})),
                    base_url="https://testserver") as client:  # fmt: skip
        yield client


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(SETTINGS.redis_url.get_secret_value())
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
async def tenant_setup(owner_engine: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> None:
    """The tenants' domains, a provider of tenant A whose mapping sends a group to the auditor role, OpenFGA in sync."""
    await reconcile(app_engine, fga)
    async with owner_engine.begin() as conn:
        for tenant_id, domain in ((world.tenant_a, "andesbank.example"), (world.tenant_b, "pacificcu.example")):
            await conn.execute(pg_insert(TenantIdentity).values(tenant_id=tenant_id, domains=[domain])
                               .on_conflict_do_update(index_elements=[TenantIdentity.tenant_id],
                                                      set_={"domains": [domain], "local_accounts": True}))  # fmt: skip
        exists = (await conn.execute(select(TenantIdentityProvider.id).where(
            TenantIdentityProvider.tenant_id == world.tenant_a, TenantIdentityProvider.display_name == "SCIM map",
        ))).first()  # fmt: skip
        if exists is None:
            await conn.execute(insert(TenantIdentityProvider).values(
                tenant_id=world.tenant_a, alias=f"andes-bank-m0test-{uuid.uuid4().hex[:8]}", display_name="SCIM map",
                protocol="oidc", status="pending", group_roles={GROUP: "auditor"},
            ))  # fmt: skip


def admin_headers(api: TestClient, user: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


def new_bearer(api: TestClient, world: World) -> str:
    """A bearer for tenant A, made by its administrator in Identity."""
    created = api.post("/api/v1/identity/scim", headers=admin_headers(api, world.a_user))
    assert created.status_code == 201, created.text
    api.cookies.clear()
    value: str = created.json()["token"]
    return value


async def bearer_for(owner: AsyncEngine, tenant_id: uuid.UUID) -> str:
    value = f"nxscim_test_{uuid.uuid4().hex}"
    async with owner.begin() as conn:
        await conn.execute(update(ScimAccess).where(ScimAccess.tenant_id == tenant_id, ScimAccess.revoked_at.is_(None))
                           .values(revoked_at=text("now()")))  # fmt: skip
        digest = hashlib.sha256(value.encode()).digest()
        await conn.execute(insert(ScimAccess).values(tenant_id=tenant_id, hint=value[-4:], access_digest=digest))
    return value


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}", "Content-Type": protocol.SCIM_JSON}


def new_user_body(**extra: Any) -> dict[str, Any]:
    email = f"m0test-scim-{uuid.uuid4().hex[:8]}@andesbank.example"
    return {"schemas": [protocol.USER], "userName": email, "externalId": f"ext-{uuid.uuid4().hex[:8]}",
            "name": {"givenName": "Ana", "familyName": "Paz"}, "emails": [{"value": email, "primary": True}],
            **extra}  # fmt: skip


def patch(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": [protocol.PATCH], "Operations": list(operations)}


async def keycloak_user(email: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10) as http:
        headers = await keycloak_admin_headers(http)
        found = (await http.get(f"{KC_BASE}/users", params={"email": email, "exact": "true"}, headers=headers)).json()
    return found[0] if found else None


async def platform_user(owner: AsyncEngine, tenant_id: uuid.UUID, email: str) -> Any:
    async with owner.connect() as conn:
        return (await conn.execute(
            select(AppUser.id, AppUser.keycloak_sub, Membership.status)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(AppUser.email == email, Membership.tenant_id == tenant_id)
        )).one()  # fmt: skip


async def scim_roles(owner: AsyncEngine, user_id: uuid.UUID) -> set[str]:
    async with owner.connect() as conn:
        return set((await conn.execute(
            select(Role.key).join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id, RoleAssignment.source == "scim")
        )).scalars())  # fmt: skip


async def test_discovery_and_the_scim_format(api: TestClient, world: World) -> None:
    value = new_bearer(api, world)
    for path in ("/scim/v2/ServiceProviderConfig", "/scim/v2/ResourceTypes", "/scim/v2/Schemas"):
        res = api.get(path, headers=auth(value))
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith(protocol.SCIM_JSON)
    assert api.get("/scim/v2/ServiceProviderConfig", headers=auth(value)).json()["patch"]["supported"] is True
    bad = api.get("/scim/v2/Users", params={"filter": 'userName sw "a"'}, headers=auth(value))
    assert (bad.status_code, bad.json()["scimType"], bad.json()["schemas"]) == (400, "invalidFilter", [protocol.ERROR])


async def test_a_provider_creates_finds_updates_and_deactivates_users(
    api: TestClient, owner_engine: AsyncEngine, world: World, redis: Redis
) -> None:
    value = new_bearer(api, world)
    body = new_user_body()
    email = body["userName"]
    created = api.post("/scim/v2/Users", json=body, headers=auth(value))
    assert created.status_code == 201, created.text
    user = created.json()
    assert created.headers["location"].endswith(f"/scim/v2/Users/{user['id']}")
    assert (user["userName"], user["active"], user["name"]["givenName"]) == (email, True, "Ana")

    # In Keycloak: an enabled account in the tenant's Organization; in the platform: an account and a membership.
    account = await keycloak_user(email)
    assert account is not None
    assert account["enabled"] is True
    member = await platform_user(owner_engine, world.tenant_a, email)
    assert (member.status, member.keycloak_sub) == ("active", account["id"])
    async with owner_engine.connect() as conn:
        query = select(TenantIdentity.organization_id).where(TenantIdentity.tenant_id == world.tenant_a)
        organization = (await conn.execute(query)).scalar_one()
    async with httpx.AsyncClient(timeout=10) as http:
        headers = await keycloak_admin_headers(http)
        members = (await http.get(f"{KC_BASE}/organizations/{organization}/members", params={"max": 1000},
                                  headers=headers)).json()  # fmt: skip
    assert account["id"] in {m["id"] for m in members}

    # Search: userName (case-insensitive) and externalId; paging.
    by_name = api.get("/scim/v2/Users", params={"filter": f'userName eq "{email.upper()}"'}, headers=auth(value))
    assert [r["id"] for r in by_name.json()["Resources"]] == [user["id"]]
    by_ext = api.get("/scim/v2/Users", params={"filter": f'externalId eq "{body["externalId"]}"'}, headers=auth(value))
    assert by_ext.json()["totalResults"] == 1
    assert api.post("/scim/v2/Users", json=new_user_body(), headers=auth(value)).status_code == 201
    page = api.get("/scim/v2/Users", params={"startIndex": 2, "count": 1}, headers=auth(value)).json()
    assert (page["startIndex"], page["itemsPerPage"]) == (2, 1)
    assert page["totalResults"] >= 2

    # Conflicts and foreign domains are refused in the SCIM format.
    taken = api.post("/scim/v2/Users", json={**body, "externalId": "other"}, headers=auth(value))
    assert (taken.status_code, taken.json()["scimType"]) == (409, "uniqueness")
    foreign = api.post("/scim/v2/Users", json=new_user_body(userName="m0test-x@elsewhere.example", emails=[]),
                       headers=auth(value))  # fmt: skip
    assert foreign.status_code == 400

    # A session of the person in the tenant ends with the deactivation (Entra's PATCH: no path, "False").
    store = SessionStore(redis, SETTINGS)
    session_id, _ = await store.create(user_id=member.id, auth_method="keycloak", active_tenant_id=world.tenant_a)
    off = api.patch(f"/scim/v2/Users/{user['id']}", json=patch({"op": "Replace", "value": {"active": "False"}}),
                    headers=auth(value))  # fmt: skip
    assert (off.status_code, off.json()["active"]) == (200, False), off.text
    assert await store.get(session_id) is None
    assert (await keycloak_user(email) or {})["enabled"] is False
    assert (await platform_user(owner_engine, world.tenant_a, email)).status == "suspended"

    on = api.patch(f"/scim/v2/Users/{user['id']}", json=patch({"op": "replace", "path": "active", "value": True},
                   {"op": "replace", "path": "name.familyName", "value": "Rios"}), headers=auth(value))  # fmt: skip
    assert (on.json()["active"], on.json()["name"]["familyName"]) == (True, "Rios")
    assert (await keycloak_user(email) or {})["enabled"] is True
    assert (await platform_user(owner_engine, world.tenant_a, email)).status == "active"

    replaced = api.put(f"/scim/v2/Users/{user['id']}", json={**body, "displayName": "Ana Paz"}, headers=auth(value))
    assert replaced.json()["displayName"] == "Ana Paz"

    # DELETE deactivates and keeps the person (history).
    assert api.delete(f"/scim/v2/Users/{user['id']}", headers=auth(value)).status_code == 204
    assert api.get(f"/scim/v2/Users/{user['id']}", headers=auth(value)).json()["active"] is False
    assert (await keycloak_user(email) or {})["enabled"] is False

    async with owner_engine.connect() as conn:
        actions = set((await conn.execute(select(AuditLog.action).where(
            AuditLog.target == f"scim_user:{user['id']}", AuditLog.tenant_id == world.tenant_a,
            AuditLog.actor_label == "scim"))).scalars())  # fmt: skip
    assert {"scim.user_create", "scim.user_update", "scim.user_replace", "scim.user_deactivate"} <= actions


async def test_groups_give_and_take_the_roles_of_the_mapping(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    value = new_bearer(api, world)
    user = api.post("/scim/v2/Users", json=new_user_body(), headers=auth(value)).json()
    member = await platform_user(owner_engine, world.tenant_a, user["userName"])
    async with owner_engine.connect() as conn:
        existing = (await conn.execute(text("SELECT id FROM scim_group WHERE tenant_id = :t AND display_name = :n"),
                                       {"t": world.tenant_a, "n": GROUP})).scalar()  # fmt: skip
    if existing:
        assert api.delete(f"/scim/v2/Groups/{existing}", headers=auth(value)).status_code == 204

    created = api.post("/scim/v2/Groups", json={"schemas": [protocol.GROUP], "displayName": GROUP,
                                                "members": [{"value": user["id"]}]}, headers=auth(value))  # fmt: skip
    assert created.status_code == 201, created.text
    group = created.json()
    assert [m["value"] for m in group["members"]] == [user["id"]]
    assert await scim_roles(owner_engine, member.id) == {"auditor"}
    found = api.get("/scim/v2/Groups", params={"filter": f'displayName eq "{GROUP.lower()}"'}, headers=auth(value))
    assert [g["id"] for g in found.json()["Resources"]] == [group["id"]]

    # A role given by hand stays whatever SCIM does.
    async with owner_engine.begin() as conn:
        query = select(Role.id).where(Role.tenant_id == world.tenant_a, Role.scope == "tenant", Role.key != "auditor")
        other = (await conn.execute(query.limit(1))).scalar_one()
        manual_role = {"tenant_id": world.tenant_a, "user_id": member.id, "role_id": other, "scope": "tenant"}
        await conn.execute(insert(RoleAssignment).values(**manual_role, source="manual"))

    removed = api.patch(f"/scim/v2/Groups/{group['id']}", headers=auth(value),
                        json=patch({"op": "remove", "path": f'members[value eq "{user["id"]}"]'}))  # fmt: skip
    assert (removed.status_code, removed.json()["members"]) == (200, [])
    assert await scim_roles(owner_engine, member.id) == set()
    api.patch(f"/scim/v2/Groups/{group['id']}", headers=auth(value),
              json=patch({"op": "add", "path": "members", "value": [{"value": user["id"]}]}))  # fmt: skip
    assert await scim_roles(owner_engine, member.id) == {"auditor"}

    # Deactivation takes the SCIM roles away but keeps the person in the group (history).
    api.patch(f"/scim/v2/Users/{user['id']}", json=patch({"op": "replace", "path": "active", "value": False}),
              headers=auth(value))  # fmt: skip
    assert await scim_roles(owner_engine, member.id) == set()
    assert user["id"] in {m["value"] for m in api.get(f"/scim/v2/Groups/{group['id']}",
                                                      headers=auth(value)).json()["members"]}  # fmt: skip
    api.patch(f"/scim/v2/Users/{user['id']}", json=patch({"op": "replace", "path": "active", "value": True}),
              headers=auth(value))  # fmt: skip
    assert await scim_roles(owner_engine, member.id) == {"auditor"}

    # A name the mapping does not know gives nothing; deleting the group takes its roles.
    renamed = api.put(f"/scim/v2/Groups/{group['id']}", headers=auth(value),
                      json={"displayName": "Unmapped", "members": [{"value": user["id"]}]})  # fmt: skip
    assert renamed.json()["displayName"] == "Unmapped"
    assert await scim_roles(owner_engine, member.id) == set()
    api.patch(f"/scim/v2/Groups/{group['id']}", headers=auth(value),
              json=patch({"op": "replace", "path": "displayName", "value": GROUP}))  # fmt: skip
    assert await scim_roles(owner_engine, member.id) == {"auditor"}
    assert api.delete(f"/scim/v2/Groups/{group['id']}", headers=auth(value)).status_code == 204
    assert api.get(f"/scim/v2/Groups/{group['id']}", headers=auth(value)).status_code == 404
    assert await scim_roles(owner_engine, member.id) == set()

    async with owner_engine.connect() as conn:
        manual = (await conn.execute(select(RoleAssignment.id).where(
            RoleAssignment.user_id == member.id, RoleAssignment.source == "manual"))).all()  # fmt: skip
        actions = set((await conn.execute(select(AuditLog.action).where(
            AuditLog.target == f"scim_group:{group['id']}"))).scalars())  # fmt: skip
    assert len(manual) == 1
    assert {"scim.group_create", "scim.group_update", "scim.group_replace", "scim.group_delete"} <= actions


async def test_a_bearer_reaches_its_tenant_only_and_dies_when_revoked(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    value = new_bearer(api, world)
    a_user = api.post("/scim/v2/Users", json=new_user_body(), headers=auth(value)).json()
    b_value = await bearer_for(owner_engine, world.tenant_b)

    # Another tenant's bearer sees nothing of tenant A, and cannot provision into A's domains.
    assert api.get(f"/scim/v2/Users/{a_user['id']}", headers=auth(b_value)).status_code == 404
    assert api.patch(f"/scim/v2/Users/{a_user['id']}", headers=auth(b_value),
                     json=patch({"op": "replace", "path": "active", "value": False})).status_code == 404  # fmt: skip
    listed = api.get("/scim/v2/Users", params={"count": 200}, headers=auth(b_value)).json()
    assert a_user["id"] not in {r["id"] for r in listed["Resources"]}
    assert api.post("/scim/v2/Users", json=new_user_body(), headers=auth(b_value)).status_code == 400
    assert api.get(f"/scim/v2/Users/{a_user['id']}", headers=auth(value)).json()["active"] is True

    # Missing, unknown, rotated and revoked bearers: 401 in the SCIM format.
    for headers in ({}, {"Authorization": "Bearer nxscim_unknown"}, {"Authorization": f"Basic {value}"}):
        res = api.get("/scim/v2/Users", headers=headers)
        assert (res.status_code, res.json()["schemas"]) == (401, [protocol.ERROR])
        assert res.headers["www-authenticate"].startswith("Bearer")
    headers = admin_headers(api, world.a_user)
    rotated = api.post("/api/v1/identity/scim", headers=headers)
    assert rotated.json()["rotated"] is True
    new_value = rotated.json()["token"]
    shown = api.get("/api/v1/identity/scim").json()
    assert (shown["enabled"], shown["hint"], shown["baseUrl"].endswith("/scim/v2")) == (True, new_value[-4:], True)
    assert "token" not in shown
    assert api.get("/scim/v2/Users", headers=auth(value)).status_code == 401
    assert api.get("/scim/v2/Users", headers=auth(new_value)).status_code == 200
    assert api.delete("/api/v1/identity/scim", headers=headers).status_code == 204
    assert api.get("/api/v1/identity/scim").json()["enabled"] is False
    assert api.delete("/api/v1/identity/scim", headers=headers).status_code == 404
    api.cookies.clear()
    assert api.get("/scim/v2/Users", headers=auth(new_value)).status_code == 401

    # The bearer is never stored nor audited in clear.
    async with owner_engine.connect() as conn:
        stored: str = (await conn.execute(text("SELECT coalesce(string_agg(row_to_json(a)::text, ''), '') "
                                          "FROM scim_access a"))).scalar_one()  # fmt: skip
        everything = "SELECT coalesce(string_agg(details::text || coalesce(target, ''), ''), '') FROM audit_log"
        audited: str = (await conn.execute(text(everything))).scalar_one()
        query = select(AuditLog.action).where(AuditLog.tenant_id == world.tenant_a,
                                              AuditLog.action.like("identity.scim_access_%"))  # fmt: skip
        actions = set((await conn.execute(query)).scalars())
    for secret in (value, new_value, new_value[len("nxscim_") :]):
        assert secret not in stored
        assert secret not in audited
    assert {"identity.scim_access_create", "identity.scim_access_rotate", "identity.scim_access_revoke"} <= actions


async def test_a_member_cannot_manage_the_bearer(api: TestClient, world: World) -> None:
    headers = admin_headers(api, world.shared)  # an architect of tenant A, without identity.manage
    assert api.post("/api/v1/identity/scim", headers=headers).status_code == 403
    assert api.get("/api/v1/identity/scim").status_code == 403


async def test_a_domain_another_tenant_declares_cannot_be_provisioned(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    """Accounts are global (D-20): tenant B declaring A's domain must not let B's bearer provision A's people, link
    their accounts to B's organization or turn a disabled account back on."""
    async with owner_engine.begin() as conn:
        await conn.execute(update(TenantIdentity).where(TenantIdentity.tenant_id == world.tenant_b)
                           .values(domains=["pacificcu.example", "andesbank.example"]))  # fmt: skip
    try:
        b_value = await bearer_for(owner_engine, world.tenant_b)
        refused = api.post("/scim/v2/Users", json=new_user_body(), headers=auth(b_value))
        assert refused.status_code == 400
        assert "another tenant" in refused.json()["detail"]
        # tenant A, which declares it too, cannot either: a shared domain is neither's to provision
        assert api.post("/scim/v2/Users", json=new_user_body(), headers=auth(new_bearer(api, world))).status_code == 400
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(update(TenantIdentity).where(TenantIdentity.tenant_id == world.tenant_b)
                               .values(domains=["pacificcu.example"]))  # fmt: skip
