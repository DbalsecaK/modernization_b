"""Sign-in with a local Keycloak account through the BFF, end to end against the real Keycloak (M0 acceptance):
login and logout work, no token ever reaches the browser, the session lives in an httpOnly cookie."""

import html
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import AppUser, Membership

from .conftest import SETTINGS, World, compose_env

# The response type of starlette's TestClient (httpx or httpx2, whichever the environment has).
TestResponse = Any

JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.")
TOKEN_WORDS = re.compile(r"access_token|refresh_token|id_token", re.I)
PASSWORD = compose_env("KC_DEV_USER_PASSWORD")


@dataclass
class Browser:
    """The API as a browser sees it, over https so __Host- cookies behave as in production."""

    client: TestClient
    responses: list[TestResponse]

    def get(self, url: str, **kwargs: Any) -> TestResponse:
        res: TestResponse = self.client.get(url, follow_redirects=False, **kwargs)
        self.responses.append(res)
        return res

    def send(
        self, method: str, url: str, csrf: str | None = None, origin: str | None = None, **kwargs: Any
    ) -> TestResponse:
        headers = {}
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if origin is not None:
            headers["Origin"] = origin
        res: TestResponse = self.client.request(method, url, headers=headers, follow_redirects=False, **kwargs)
        self.responses.append(res)
        return res


def keycloak_sign_in(authorization_url: str, username: str, password: str) -> str:
    """Do what the user does on the Keycloak page; return the callback URL Keycloak redirects to."""
    with httpx.Client(follow_redirects=True, timeout=20) as kc:
        page = kc.get(authorization_url)
        match = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        assert match, "Keycloak login form not found"
        # Keycloak's cookies are Secure; browsers send them to http://localhost (a secure context), httpx does not.
        cookies = "; ".join(f"{c.name}={c.value}" for c in kc.cookies.jar)
        res = kc.post(
            html.unescape(match.group(1)),
            data={"username": username, "password": password, "credentialId": ""},
            headers={"Cookie": cookies},
            follow_redirects=False,
        )
    assert res.status_code == 302, f"Keycloak did not accept the credentials ({res.status_code})"
    return res.headers["location"]


def as_local_path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


@pytest.fixture(scope="module")
async def luis(owner_engine: AsyncEngine, world: World) -> uuid.UUID:
    """A realm user (landrade@andesbank.example) that exists in the platform but has never signed in (no sub)."""
    async with owner_engine.begin() as conn:
        user_id = (
            await conn.execute(
                insert(AppUser)
                .values(email="landrade@andesbank.example", display_name="Luis Andrade")
                .returning(AppUser.id)
            )
        ).scalar_one()
        for tenant in (world.tenant_a, world.tenant_b):
            await conn.execute(insert(Membership).values(tenant_id=tenant, user_id=user_id))
    return user_id


@pytest.fixture
def browser(api_settings: Settings) -> Iterator[Browser]:
    with TestClient(create_app(api_settings), base_url="https://testserver") as client:
        yield Browser(client, [])


def sign_in(browser: Browser, username: str, return_to: str = "/projects") -> TestResponse:
    start = browser.get(f"/auth/login?returnTo={return_to}")
    assert start.status_code == 302
    callback = keycloak_sign_in(start.headers["location"], username, PASSWORD)
    assert callback.startswith(f"{SETTINGS.web_origin}/auth/callback?")
    return browser.get(as_local_path(callback))


def assert_no_token_reached_the_browser(browser: Browser) -> None:
    for res in browser.responses:
        exposed = res.text + "\n".join(f"{k}: {v}" for k, v in res.headers.multi_items())
        assert not JWT.search(exposed), f"a JWT reached the browser in {res.request.url}"
        assert not TOKEN_WORDS.search(exposed), f"a token field reached the browser in {res.request.url}"


async def platform_events(owner_engine: AsyncEngine, action: str) -> list[tuple[str, str | None, dict[str, object]]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT outcome, actor_label, details FROM audit_log "
                "WHERE tenant_id IS NULL AND action = :a ORDER BY seq"
            ),
            {"a": action},
        )
        return [(r.outcome, r.actor_label, r.details) for r in rows]


async def test_login_me_switch_locale_logout(
    browser: Browser, luis: uuid.UUID, world: World, owner_engine: AsyncEngine
) -> None:
    callback = sign_in(browser, "landrade@andesbank.example")
    assert callback.status_code == 302
    assert callback.headers["location"] == f"{SETTINGS.web_origin}/projects"
    cookie = next(
        v for k, v in callback.headers.multi_items() if k == "set-cookie" and v.startswith("__Host-nexti_session=")
    )
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()

    me = browser.get("/api/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["id"] == str(luis)
    assert body["authMethod"] == "keycloak"
    assert {t["id"] for t in body["tenants"]} == {str(world.tenant_a), str(world.tenant_b)}
    csrf = body["csrfToken"]

    # Mutations need the CSRF token and, when sent, the web origin.
    other = next(t["id"] for t in body["tenants"] if t["id"] != body["activeTenant"]["id"])
    assert browser.send("PUT", "/api/v1/session/tenant", json={"tenantId": other}).json()["code"] == "csrf_failed"
    wrong_origin = browser.send("PUT", "/api/v1/session/tenant", csrf, "https://evil.example", json={"tenantId": other})
    assert wrong_origin.json()["code"] == "origin_not_allowed"
    switched = browser.send("PUT", "/api/v1/session/tenant", csrf, SETTINGS.web_origin, json={"tenantId": other})
    assert switched.status_code == 200
    assert browser.get("/api/v1/me").json()["activeTenant"]["id"] == other
    stranger = browser.send("PUT", "/api/v1/session/tenant", csrf, json={"tenantId": str(uuid.uuid4())})
    assert stranger.status_code == 404

    assert browser.send("PATCH", "/api/v1/me", csrf, json={"locale": "es"}).status_code == 204

    assert browser.send("POST", "/auth/logout", csrf).status_code == 204
    assert browser.get("/api/v1/me").status_code == 401

    # The language preference survives the session (spec 18.6).
    sign_in(browser, "landrade@andesbank.example")
    assert browser.get("/api/v1/me").json()["user"]["locale"] == "es"
    assert_no_token_reached_the_browser(browser)

    logins = await platform_events(owner_engine, "auth.login")
    assert ("success", "landrade@andesbank.example") in [(o, label) for o, label, _ in logins]
    logouts = await platform_events(owner_engine, "auth.logout")
    assert logouts[-1][2]["keycloak_session_ended"] is True


async def test_keycloak_account_without_platform_user_is_refused(browser: Browser, owner_engine: AsyncEngine) -> None:
    res = sign_in(browser, "admin@nexti.example")
    assert res.headers["location"] == f"{SETTINGS.web_origin}/login?error=no_platform_access"
    assert browser.get("/api/v1/me").status_code == 401
    failures = await platform_events(owner_engine, "auth.login")
    assert ("failure", "admin@nexti.example", "no_platform_access") in [
        (o, label, d.get("reason")) for o, label, d in failures
    ]


async def test_email_already_linked_to_another_account_is_refused(browser: Browser, world: World) -> None:
    # cruiz@nexti.example exists in the platform linked to another sub ("sub-shared").
    res = sign_in(browser, "cruiz@nexti.example")
    assert res.headers["location"] == f"{SETTINGS.web_origin}/login?error=sign_in_failed"


def test_a_callback_replayed_in_another_browser_is_refused(
    browser: Browser, api_settings: Settings, luis: uuid.UUID
) -> None:
    start = browser.get("/auth/login")
    callback = keycloak_sign_in(start.headers["location"], "landrade@andesbank.example", PASSWORD)
    with TestClient(create_app(api_settings), base_url="https://testserver") as other:
        res = other.get(as_local_path(callback), follow_redirects=False)
    assert res.headers["location"] == f"{SETTINGS.web_origin}/login?error=sign_in_failed"


def test_a_login_state_is_single_use(browser: Browser, luis: uuid.UUID) -> None:
    start = browser.get("/auth/login")
    callback = as_local_path(keycloak_sign_in(start.headers["location"], "landrade@andesbank.example", PASSWORD))
    assert browser.get(callback).headers["location"] == f"{SETTINGS.web_origin}/"
    assert browser.get(callback).headers["location"].endswith("/login?error=sign_in_failed")


def test_unknown_session_cookie_is_not_authenticated(browser: Browser) -> None:
    browser.client.cookies.set("__Host-nexti_session", "forged", domain="testserver")
    res = browser.get("/api/v1/me")
    assert res.status_code == 401
    assert res.json()["code"] == "not_authenticated"
