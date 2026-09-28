"""BFF endpoints: /auth/login, /auth/callback, /auth/logout (outside /api/v1, proxied by the web origin)."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit import AuditEvent, record
from nexti_api.auth.oidc import OidcClient, OidcError
from nexti_api.auth.session import (
    LOGIN_STATE_TTL_SECONDS,
    CurrentSession,
    SessionStore,
    login_cookie_name,
    session_cookie_name,
)
from nexti_api.auth.users import SignInDeniedError, sign_in, user_tenants
from nexti_api.authz.require import Authorized, authenticated
from nexti_api.observability import log
from nexti_api.settings import Settings
from nexti_core.audit import ActorKind
from nexti_core.db.session import DbScope, scoped_connection

router = APIRouter(prefix="/auth", tags=["auth"])


def safe_return_path(value: str | None) -> str:
    """Only same-origin absolute paths: no scheme, no host, no protocol-relative '//' (open redirects)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value or "://" in value:
        return "/"
    return value


def set_session_cookie(response: Response, settings: Settings, session_id: str) -> None:
    response.set_cookie(
        session_cookie_name(settings),
        session_id,
        max_age=settings.session_max_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def actor_kind(current: CurrentSession) -> ActorKind:
    """Who acted, for the audit log: a person, marked `dev-auth` when signed in without Keycloak."""
    return "dev-auth" if current.data.auth_method == "dev-auth" else "user"


async def audit_platform(engine: AsyncEngine, event: AuditEvent) -> None:
    """Sign-in events go to the platform chain in their own transaction (also when sign-in is denied)."""
    async with scoped_connection(engine, DbScope()) as conn:
        await record(conn, event)


def _failure_redirect(settings: Settings, code: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.web_origin.rstrip('/')}/login?error={code}", status_code=302)
    response.delete_cookie(login_cookie_name(settings), path="/", secure=settings.session_cookie_secure)
    return response


@router.get("/login", summary="Start sign-in with Keycloak (authorization code + PKCE)")
async def login(request: Request, return_to: Annotated[str | None, Query(alias="returnTo")] = None) -> Response:
    settings: Settings = request.app.state.settings
    oidc: OidcClient = request.app.state.oidc
    store: SessionStore = request.app.state.sessions
    pending = oidc.start_login()
    # Binds the pending login to this browser: a callback URL replayed in another browser is rejected.
    binding = secrets.token_urlsafe(32)
    await store.save_login(
        pending.state,
        {
            "binding": binding,
            "nonce": pending.nonce,
            "verifier": pending.code_verifier,
            "return_to": safe_return_path(return_to),
        },
    )
    response = RedirectResponse(pending.authorization_url, status_code=302)
    response.set_cookie(
        login_cookie_name(settings),
        binding,
        max_age=LOGIN_STATE_TTL_SECONDS,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback", summary="Keycloak redirects here; creates the session and sets the cookie")
async def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> Response:
    settings: Settings = request.app.state.settings
    oidc: OidcClient = request.app.state.oidc
    store: SessionStore = request.app.state.sessions
    engine: AsyncEngine = request.app.state.resources.engine

    async def fail(reason: str, label: str | None = None) -> Response:
        await audit_platform(
            engine,
            AuditEvent(
                action="auth.login", outcome="failure", actor_kind="user", actor_label=label,
                details={"method": "keycloak", "reason": reason},
            ),
        )  # fmt: skip
        return _failure_redirect(settings, "sign_in_failed" if reason != "no_platform_access" else reason)

    if error or not code or not state:
        return await fail("provider_error" if error else "missing_parameters")
    pending = await store.pop_login(state)
    binding = request.cookies.get(login_cookie_name(settings), "")
    if pending is None or not secrets.compare_digest(binding, pending.get("binding", "")):
        return await fail("invalid_state")
    try:
        tokens = await oidc.exchange_code(code, pending["verifier"], pending["nonce"])
    except OidcError as exc:
        log.warning("oidc_exchange_failed", error=str(exc))
        return await fail("token_exchange_failed")
    try:
        user = await sign_in(engine, tokens.claims)
    except SignInDeniedError as exc:
        return await fail(exc.code, tokens.claims.email)

    if tokens.claims.email and tokens.claims.email_verified:
        # Imported here: the administration package depends on this module.
        from nexti_api.admin.invitations import accept_pending_invitations

        if await accept_pending_invitations(engine, user.id, tokens.claims.email):
            relay = getattr(request.app.state, "relay", None)
            if relay is not None:
                relay.wake()
    tenants = await user_tenants(engine, user.id)
    session_id, _ = await store.create(
        user_id=user.id,
        auth_method="keycloak",
        active_tenant_id=tenants[0].id if tenants else None,
        keycloak_sub=tokens.claims.sub,
        refresh_token=tokens.refresh_token,
    )
    await audit_platform(
        engine,
        AuditEvent(
            action="auth.login", outcome="success", actor_kind="user", actor_id=user.id, actor_label=user.email,
            details={"method": "keycloak", "tenants": len(tenants)},
        ),
    )  # fmt: skip
    response = RedirectResponse(f"{settings.web_origin.rstrip('/')}{pending['return_to']}", status_code=302)
    set_session_cookie(response, settings, session_id)
    response.delete_cookie(login_cookie_name(settings), path="/", secure=settings.session_cookie_secure)
    return response


@router.post("/logout", status_code=204, summary="End the session here and in Keycloak")
async def logout(request: Request, auth: Annotated[Authorized, Depends(authenticated())]) -> Response:
    current = auth.session
    settings: Settings = request.app.state.settings
    store: SessionStore = request.app.state.sessions
    oidc: OidcClient = request.app.state.oidc
    await store.delete(current.id)
    keycloak_ended = None
    if current.data.refresh_token:
        try:
            keycloak_ended = await oidc.logout(current.data.refresh_token)
        except Exception as exc:  # the local session is gone either way
            log.warning("keycloak_logout_failed", error=type(exc).__name__)
            keycloak_ended = False
    await audit_platform(
        request.app.state.resources.engine,
        AuditEvent(
            action="auth.logout", outcome="success", actor_kind=actor_kind(current), actor_id=current.data.user_id,
            details={"keycloak_session_ended": keycloak_ended},
        ),
    )  # fmt: skip
    response = Response(status_code=204)
    response.delete_cookie(session_cookie_name(settings), path="/", secure=settings.session_cookie_secure)
    return response
