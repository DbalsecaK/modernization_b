"""Acceptance of M0b (plan section 3, ADR-0022) against the real Keycloak of the Compose: enterprise identity.

The tenant administrator configures how Andes Bank signs in through the API. The realm `idp-test` plays the
customer's identity provider (as Entra ID or Okta would), with users in groups. Then:

- a user of the provider signs in by SSO (home-realm discovery from the e-mail), gets an account and a membership
  (JIT) and the tenant roles of their groups;
- an own account of a domain that is "SSO only" cannot sign in with a password;
- an own account signs in with a second factor (TOTP) when the tenant requires MFA, and a password-only session is
  sent back to Keycloak for the second factor;
- the Organization in the token chooses the tenant of the session, and a person in two tenants only sees the data of
  the active one.

Each login is what a browser does on Keycloak's pages (the forms are submitted, no API shortcut).
"""

import base64
import hashlib
import hmac
import re
import struct
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.keycloak_admin import KeycloakAdmin
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import AppUser, Membership, Role, RoleAssignment

from .conftest import SETTINGS, World, compose_env, keycloak_admin_headers
from .keycloak_browser import Browser, keycloak_form, totp_secret
from .test_runs_api import sign_in

PASSWORD = compose_env("KC_DEV_USER_PASSWORD")
CALLBACK = f"{SETTINGS.web_origin.rstrip('/')}/auth/callback"
PUBLIC = (SETTINGS.keycloak_public_url or SETTINGS.keycloak_url).rstrip("/")
# Keycloak calls the test provider from inside its container: the back channel is its own port.
INSIDE = "http://localhost:8080"
ADMIN = f"{SETTINGS.keycloak_url}/admin/realms/{SETTINGS.keycloak_realm}"


def totp(secret: str, at: float | None = None) -> str:
    """RFC 6238 with Keycloak's defaults (SHA-1, 6 digits, 30 s), as an authenticator app computes it."""
    key = secret.replace(" ", "").upper()
    raw = base64.b32decode(key + "=" * (-len(key) % 8))
    digest = hmac.new(raw, struct.pack(">Q", int((at or time.time()) // 30)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def _page_text(page: str) -> str:
    """What a person reads on a Keycloak page (for failure messages)."""
    body = re.sub(r"<(script|style)[^>]*>.*?</>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:400]


class Login:
    """One person's browser: the platform (TestClient) and Keycloak's pages (real HTTP)."""

    def __init__(self, api: TestClient) -> None:
        self.api = api
        self.kc = Browser()
        api.cookies.clear()

    def start(self, email: str | None = None) -> httpx.Response:
        res = self.api.get("/auth/login", params={"returnTo": "/projects", **({"email": email} if email else {})},
                           follow_redirects=False)  # fmt: skip
        assert res.status_code == 302, res.text
        return self.kc.follow(self.kc.get(res.headers["location"]), CALLBACK)

    def submit(self, page: httpx.Response, form_id: str, fields: dict[str, str]) -> httpx.Response:
        action, values = keycloak_form(page.text, form_id)
        return self.kc.follow(self.kc.post(action, data={**values, **fields}), CALLBACK)

    def callback(self, res: httpx.Response) -> Any:
        """Keycloak redirected to the platform's callback: the platform answers (a session, a failure or a new round
        to Keycloak)."""
        assert res.is_redirect, (
            res.status_code,
            str(res.url).split("?")[0],
            _page_text(res.text)[-200:],
            re.findall(r'name="([^"]+)"', res.text),
            re.findall(r"input-error-([\w-]+)", res.text),
        )
        assert res.headers["location"].startswith(CALLBACK), res.headers["location"]
        parts = urlsplit(res.headers["location"])
        return self.api.get(f"{parts.path}?{parts.query}", follow_redirects=False)

    def close(self) -> None:
        self.kc.__exit__()


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings.model_copy(update={"dev_auth_enabled": True})),
                    base_url="https://testserver") as client:  # fmt: skip
        yield client


async def _keycloak_user(http: httpx.AsyncClient, email: str) -> str:
    """A local Keycloak account (own account) with the development password; returns its id."""
    headers = await keycloak_admin_headers(http)
    created = await http.post(f"{ADMIN}/users", headers=headers, json={
        "username": email, "email": email, "firstName": "Test", "lastName": "Person", "enabled": True,
        "emailVerified": True,
        "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
    })  # fmt: skip
    assert created.status_code in (201, 409), created.text
    found = (await http.get(f"{ADMIN}/users", headers=headers, params={"email": email, "exact": "true"})).json()
    return str(found[0]["id"])


async def _platform_user(owner: AsyncEngine, email: str, sub: str, tenants: list[uuid.UUID]) -> uuid.UUID:
    async with owner.begin() as conn:
        user_id: uuid.UUID = (
            await conn.execute(insert(AppUser).values(email=email, display_name=email, keycloak_sub=sub)
                               .returning(AppUser.id))
        ).scalar_one()  # fmt: skip
        for tenant in tenants:
            await conn.execute(insert(Membership).values(tenant_id=tenant, user_id=user_id))
    return user_id


async def _idp_roles(owner: AsyncEngine, email: str) -> dict[str, str]:
    async with owner.connect() as conn:
        rows = (await conn.execute(
            select(Role.key, RoleAssignment.source).join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .join(AppUser, AppUser.id == RoleAssignment.user_id).where(AppUser.email == email)
        )).all()  # fmt: skip
    return {r.key: r.source for r in rows}


async def _last_login(owner: AsyncEngine, email: str) -> dict[str, Any]:
    async with owner.connect() as conn:
        row = (await conn.execute(text(
            "SELECT outcome, details FROM audit_log WHERE action = 'auth.login' AND actor_label = :e "
            "ORDER BY id DESC LIMIT 1"), {"e": email})).one()  # fmt: skip
    return {"outcome": row.outcome, **row.details}


async def test_enterprise_identity_end_to_end(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    run = uuid.uuid4().hex[:6]
    headers = sign_in(api, world.a_user)  # María Torres, administrator of Andes Bank
    configured = api.put("/api/v1/identity", headers=headers, json={
        "localAccounts": True, "sso": True, "mfaRequired": False, "domains": ["andesbank.example"]})  # fmt: skip
    assert configured.status_code == 200, configured.text
    provider = api.post("/api/v1/identity/providers", headers=headers, json={
        "displayName": f"Corp SSO m0test {run}", "protocol": "oidc",
        "clientSecret": compose_env("KC_IDP_TEST_CLIENT_SECRET"),
        "settings": {"issuer": f"{PUBLIC}/realms/idp-test", "client_id": "nexti-broker",
                     "authorization_url": f"{PUBLIC}/realms/idp-test/protocol/openid-connect/auth",
                     "token_url": f"{INSIDE}/realms/idp-test/protocol/openid-connect/token",
                     "jwks_url": f"{INSIDE}/realms/idp-test/protocol/openid-connect/certs"},
        "domains": ["corp.example"], "ssoOnly": True, "jit": True,
        "groupRoles": {"it-admins": "tenantAdmin", "finance": "finance", "auditors": "auditor"},
    })  # fmt: skip
    assert provider.status_code == 201, provider.text
    alias = provider.json()["alias"]
    assert provider.json()["status"] == "active", provider.json()
    async with httpx.AsyncClient(timeout=20) as http:
        two_sub = await _keycloak_user(http, f"m0test-two-{run}@andesbank.example")
        mfa_sub = await _keycloak_user(http, f"m0test-mfa-{run}@andesbank.example")
        sso_sub = await _keycloak_user(http, f"m0test-pwd-{run}@corp.example")
    assert sso_sub
    try:
        # 1. SSO from the e-mail: Keycloak sends the user to the provider; JIT and the groups give the roles.
        for person, groups in (("jorge@corp.example", {"tenantAdmin", "auditor"}), ("lucia@corp.example", {"finance"})):
            login = Login(api)
            page = login.start(person)
            assert urlsplit(str(page.url)).path.startswith("/realms/idp-test/"), page.url
            done = login.callback(login.submit(page, "kc-form-login", {"username": person, "password": PASSWORD}))
            assert (done.status_code, done.headers["location"]) == (302, f"{SETTINGS.web_origin}/projects"), done.text
            me = api.get("/api/v1/me").json()
            assert me["activeTenant"]["id"] == str(world.tenant_a), me
            assert {k for k, v in (await _idp_roles(owner_engine, person)).items() if v == "idp"} == groups
            audit = await _last_login(owner_engine, person)
            assert (audit["outcome"], audit["via"], set(audit["idp_roles"])) == ("success", alias, groups)
            login.close()

        # 2. corp.example is SSO only: its own accounts cannot use a password.
        login = Login(api)
        page = login.start()
        refused = login.callback(login.submit(page, "kc-form-login", {"username": f"m0test-pwd-{run}@corp.example",
                                                                      "password": PASSWORD}))  # fmt: skip
        assert refused.headers["location"].endswith("/login?error=sso_required"), refused.headers
        login.close()

        # 3. The Organization of the token chooses the tenant: a person of both tenants, member of Pacific's
        #    Organization only, starts in Pacific (not in Andes, first by name) and sees only Pacific's projects.
        two = f"m0test-two-{run}@andesbank.example"
        two_id = await _platform_user(owner_engine, two, two_sub, [world.tenant_a, world.tenant_b])
        async with owner_engine.begin() as conn:
            for tenant, project in ((world.tenant_a, world.project_a), (world.tenant_b, world.project_b)):
                role = (await conn.execute(select(Role.id).where(Role.tenant_id == tenant,
                                                                 Role.key == "architect"))).scalar_one()  # fmt: skip
                await conn.execute(insert(RoleAssignment).values(tenant_id=tenant, user_id=two_id, role_id=role,
                                                                 scope="project", project_id=project))  # fmt: skip
        await reconcile(app_engine, fga)
        async with httpx.AsyncClient(timeout=20) as http:
            kc = KeycloakAdmin(SETTINGS, http)
            pacific = await kc.save_organization("pacific-cu", "Pacific Credit Union", [])
            await kc.add_organization_member(pacific, two_sub)
        login = Login(api)
        done = login.callback(login.submit(login.start(), "kc-form-login", {"username": two, "password": PASSWORD}))
        assert done.status_code == 302, done.headers
        assert done.headers["location"].endswith("/projects"), done.headers
        assert api.get("/api/v1/me").json()["activeTenant"]["id"] == str(world.tenant_b)
        projects = {p["id"] for p in api.get("/api/v1/projects").json()}
        assert str(world.project_b) in projects
        assert str(world.project_a) not in projects
        login.close()

        # 4. Andes Bank requires MFA: an own account sets up TOTP on its first login and gets acr=mfa.
        changed = api.put("/api/v1/identity", headers=sign_in(api, world.a_user), json={
            "localAccounts": True, "sso": True, "mfaRequired": True, "domains": ["andesbank.example"]})  # fmt: skip
        assert changed.status_code == 200, changed.text
        mfa = f"m0test-mfa-{run}@andesbank.example"
        await _platform_user(owner_engine, mfa, mfa_sub, [world.tenant_a])
        login = Login(api)
        page = login.submit(login.start(mfa), "kc-form-login", {"username": mfa, "password": PASSWORD})
        secret = totp_secret(page.text)
        done = login.callback(login.submit(page, "kc-totp-settings-form",
                                           {"totp": totp(secret), "userLabel": "phone"}))  # fmt: skip
        assert done.status_code == 302, done.headers
        assert done.headers["location"].endswith("/projects"), done.headers
        assert (await _last_login(owner_engine, mfa))["mfa"] is True
        login.close()

        #    Without the e-mail first, the password alone is not enough: the platform sends the person back to
        #    Keycloak, which asks only for the code (the next one: a code is not accepted twice).
        login = Login(api)
        first = login.callback(login.submit(login.start(), "kc-form-login", {"username": mfa, "password": PASSWORD}))
        assert first.status_code == 302, first.headers
        assert "acr_values=mfa" in first.headers["location"], first.headers
        page = login.kc.follow(login.kc.get(first.headers["location"]), CALLBACK)
        done = login.callback(login.submit(page, "kc-otp-login-form", {"otp": totp(secret, time.time() + 30)}))
        assert done.status_code == 302, done.headers
        assert done.headers["location"].endswith("/projects"), done.headers
        assert (await _last_login(owner_engine, mfa))["mfa"] is True
        login.close()
    finally:
        restore = api.put("/api/v1/identity", headers=sign_in(api, world.a_user), json={
            "localAccounts": True, "sso": False, "mfaRequired": False, "domains": []})  # fmt: skip
        assert restore.status_code == 200, restore.text
        api.delete(f"/api/v1/identity/providers/{provider.json()['id']}", headers=sign_in(api, world.a_user))
        async with httpx.AsyncClient(timeout=20) as http:
            admin_headers = await keycloak_admin_headers(http)
            for email in ("jorge@corp.example", "lucia@corp.example"):
                for user in (await http.get(f"{ADMIN}/users", headers=admin_headers,
                                            params={"email": email, "exact": "true"})).json():  # fmt: skip
                    await http.delete(f"{ADMIN}/users/{user['id']}", headers=admin_headers)
