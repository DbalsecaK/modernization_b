"""Keycloak events reach the platform audit log (M0 acceptance: every sensitive action, Keycloak's included)."""

import uuid
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit.keycloak_events import pull_keycloak_events
from nexti_api.keycloak_admin import KeycloakAdmin

from .conftest import SETTINGS
from .keycloak_browser import keycloak_form
from .test_auth_flow import PASSWORD, keycloak_sign_in

AUTH_URL = (
    f"{SETTINGS.keycloak_public_issuer}/protocol/openid-connect/auth?client_id={SETTINGS.oidc_client_id}"
    f"&response_type=code&scope=openid&redirect_uri={SETTINGS.web_origin}/auth/callback&state=s&nonce=n"
    "&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&code_challenge_method=S256"
)
SAFE_DETAIL_KEYS = {"keycloak_event_id", "client_id", "ip_address", "error", "auth_client_id"}


def failed_sign_in(username: str) -> None:
    with httpx.Client(follow_redirects=True, timeout=20) as kc:
        page = kc.get(AUTH_URL)
        action, _ = keycloak_form(page.text, "kc-form-login")
        cookies = "; ".join(f"{c.name}={c.value}" for c in kc.cookies.jar)
        res = kc.post(action, data={"username": username, "password": "wrong-password"}, headers={"Cookie": cookies})
    assert res.status_code == 200  # the form again, with the error


async def keycloak_rows(owner: AsyncEngine, action: str, label: str | None = None) -> list[dict[str, Any]]:
    async with owner.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT outcome, actor_label, details, actor_kind, tenant_id FROM audit_log "
                "WHERE action = :a AND (CAST(:l AS text) IS NULL OR actor_label = :l) ORDER BY seq"
            ),
            {"a": action, "l": label},
        )
        return [dict(r._mapping) for r in rows]


async def test_logins_failures_and_admin_events_are_copied_once(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    failed_sign_in("avelez@pacificcu.example")
    keycloak_sign_in(AUTH_URL, "admin@nexti.example", PASSWORD)
    email = f"m0test-{uuid.uuid4().hex[:10]}@example.test"
    async with httpx.AsyncClient(timeout=10) as http:
        admin = KeycloakAdmin(SETTINGS, http)
        await admin.create_user(email)
        assert await pull_keycloak_events(app_engine, admin) > 0
        again = await pull_keycloak_events(app_engine, admin)

    failures = await keycloak_rows(owner_engine, "keycloak.login_error", "avelez@pacificcu.example")
    assert failures
    assert failures[-1]["outcome"] == "failure"
    assert failures[-1]["actor_kind"] == "keycloak"
    assert failures[-1]["tenant_id"] is None  # platform chain

    logins = await keycloak_rows(owner_engine, "keycloak.login")
    assert logins
    assert logins[-1]["outcome"] == "success"
    created = await keycloak_rows(owner_engine, "keycloak.admin.user_create")
    assert created

    for rows in (failures, logins, created):
        for row in rows:
            assert set(row["details"]) <= SAFE_DETAIL_KEYS
    ids = [r["details"]["keycloak_event_id"] for r in failures + logins + created]
    assert len(ids) == len(set(ids)), "an event was copied twice"
    # Nothing new happened in between (the service account's own token requests are not security events).
    assert again == 0
