"""Administration → Authentication (spec 15.1, ADR-0022): how the tenant signs in.

- The tenant's methods (own accounts, SSO; at least one), "MFA required" for own accounts and its e-mail domains.
- Its identity providers (OIDC or SAML 2.0): where they are, their domains, "SSO only", JIT and the mapping of groups
  to tenant roles. The client secret goes to Keycloak only: it is never stored, returned nor audited.
- The policies of the shared realm (passwords, lockout, sessions), read-only: Keycloak sets them per realm (D-20).

Every change reconciles the tenant's Keycloak Organization and is audited. Provider URLs must be https on a public
host (Keycloak calls them), except in a local environment, where the test identity provider runs on localhost.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.errors import ProblemError
from nexti_api.identity import providers, service
from nexti_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_core.db.models import Role, Tenant, TenantIdentity, TenantIdentityProvider
from nexti_ingest import Rejection
from nexti_ingest.git import ensure_public_host

router = APIRouter(prefix="/api/v1/identity", tags=["admin"])
ManageIdentity = Annotated[Authorized, Depends(require_tenant("identity.manage"))]
Protocol = Literal["oidc", "saml"]
DomainList = Annotated[list[Annotated[str, Field(min_length=3, max_length=253)]], Field(max_length=50)]
URL_SETTINGS = ("issuer", "authorization_url", "token_url", "jwks_url", "userinfo_url", "logout_url", "metadata_url",
                "sso_url")  # fmt: skip


class ProviderOut(ApiModel):
    id: uuid.UUID
    alias: str
    display_name: str
    protocol: Protocol
    settings: dict[str, str]
    domains: list[str]
    sso_only: bool
    jit: bool
    group_roles: dict[str, str]
    default_role: str | None
    status: Literal["pending", "active", "failed"]
    last_error: str | None
    created_at: datetime
    # What the customer registers in their provider as the redirect (reply) URL.
    redirect_uri: str


class RealmPolicy(ApiModel):
    """What Keycloak applies to the whole shared realm (read-only here)."""

    password_policy: str
    lockout_failures: int
    lockout_minutes: int
    session_idle_minutes: int
    session_max_hours: int


class IdentityOut(ApiModel):
    local_accounts: bool
    sso: bool
    mfa_required: bool
    domains: list[str]
    organization: str | None
    providers: list[ProviderOut]
    realm: RealmPolicy | None


class IdentityUpdate(ApiModel):
    local_accounts: bool
    sso: bool
    mfa_required: bool
    domains: DomainList = Field(default_factory=list)


class ProviderCreate(ApiModel):
    display_name: str = Field(min_length=1, max_length=100)
    protocol: Protocol
    settings: dict[str, str] = Field(default_factory=dict, max_length=12)
    # Sent to Keycloak only; never stored, returned nor audited.
    client_secret: str | None = Field(default=None, min_length=1, max_length=500)
    domains: DomainList = Field(default_factory=list)
    sso_only: bool = False
    jit: bool = True
    group_roles: dict[str, str] = Field(default_factory=dict, max_length=100)
    default_role: str | None = Field(default=None, max_length=100)


class ProviderUpdate(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    settings: dict[str, str] | None = Field(default=None, max_length=12)
    client_secret: str | None = Field(default=None, min_length=1, max_length=500)
    domains: DomainList | None = None
    sso_only: bool | None = None
    jit: bool | None = None
    group_roles: dict[str, str] | None = Field(default=None, max_length=100)
    default_role: str | None = Field(default=None, max_length=100)


def _admin(request: Request) -> KeycloakAdmin:
    admin: KeycloakAdmin | None = getattr(request.app.state, "keycloak_admin", None)
    if admin is None:
        raise ProblemError(503, "identity_unavailable", "The identity service (Keycloak admin) is not configured.")
    return admin


def _provider_out(row: Any, issuer: str) -> ProviderOut:
    return ProviderOut(
        id=row.id, alias=row.alias, display_name=row.display_name, protocol=row.protocol,
        settings=dict(row.settings or {}), domains=list(row.domains), sso_only=row.sso_only, jit=row.jit,
        group_roles=dict(row.group_roles or {}), default_role=row.default_role, status=row.status,
        last_error=row.last_error, created_at=row.created_at, redirect_uri=f"{issuer}/broker/{row.alias}/endpoint",
    )  # fmt: skip


def _domains(values: list[str]) -> list[str]:
    clean = sorted({v.strip().lower().rstrip(".") for v in values if v.strip()})
    for domain in clean:
        labels = domain.split(".")
        if len(labels) < 2 or not all(label and label.replace("-", "").isalnum() and label[0] != "-"
                                      and label[-1] != "-" for label in labels):  # fmt: skip
            raise ProblemError(422, "domain_invalid", f"{domain} is not a domain.")
    return clean


async def _checked_settings(request: Request, protocol: str, raw: dict[str, str]) -> dict[str, str]:
    """The known settings of the protocol; their URLs https on a public host (http and localhost only locally)."""
    settings = providers.clean_settings(protocol, raw)
    config = request.app.state.settings
    for key in URL_SETTINGS:
        if key not in settings:
            continue
        url = settings[key].rstrip("/") if key == "issuer" else settings[key]
        settings[key] = url
        parts = urlsplit(url)
        if config.is_local and parts.scheme in ("http", "https") and parts.hostname and not parts.username:
            continue
        try:
            await ensure_public_host(url, services.services(request).git_resolver)
        except Rejection as rejection:
            raise ProblemError(422, rejection.code, f"{key}: {rejection.detail}") from None
    if protocol == "oidc":
        settings = await _discovered(request, settings)
        missing = [
            k for k in ("client_id", "issuer", "authorization_url", "token_url", "jwks_url") if k not in settings
        ]
        if missing:
            raise ProblemError(422, "provider_settings_missing", f"The OIDC provider needs: {', '.join(missing)}.")
    elif "metadata_url" not in settings and not {"sso_url", "entity_id"} <= set(settings):
        raise ProblemError(422, "provider_settings_missing",
                           "The SAML provider needs its metadata URL, or its SSO URL and entity id.")  # fmt: skip
    return settings


async def _discovered(request: Request, settings: dict[str, str]) -> dict[str, str]:
    """Fills the endpoints the issuer publishes (OpenID discovery) that were not given."""
    wanted = {"authorization_url": "authorization_endpoint", "token_url": "token_endpoint", "jwks_url": "jwks_uri",
              "userinfo_url": "userinfo_endpoint", "logout_url": "end_session_endpoint"}  # fmt: skip
    if "issuer" not in settings or all(k in settings for k in ("authorization_url", "token_url", "jwks_url")):
        return settings
    http: httpx.AsyncClient = request.app.state.resources.http
    try:
        res = await http.get(f"{settings['issuer']}/.well-known/openid-configuration", timeout=10,
                             follow_redirects=False)  # fmt: skip
        found = res.json() if res.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        found = {}
    if not isinstance(found, dict) or not found:
        raise ProblemError(422, "provider_discovery_failed",
                           "The issuer does not publish its OpenID configuration: give its endpoints.")  # fmt: skip
    filled = dict(settings)
    for key, published in wanted.items():
        if key not in filled and isinstance(found.get(published), str):
            filled[key] = found[published]
    return await _checked_settings(request, "oidc", filled) if filled != settings else filled


async def _checked_roles(conn: AsyncConnection, group_roles: dict[str, str], default_role: str | None) -> None:
    keys = {*group_roles.values(), *([default_role] if default_role else [])}
    if not keys:
        return
    found = set((await conn.execute(select(Role.key).where(Role.key.in_(keys), Role.scope == "tenant"))).scalars())
    if missing := sorted(keys - found):
        raise ProblemError(422, "role_not_found", f"These tenant roles do not exist: {', '.join(missing)}.")


async def _realm(request: Request) -> RealmPolicy | None:
    admin: KeycloakAdmin | None = getattr(request.app.state, "keycloak_admin", None)
    if admin is None:
        return None
    try:
        realm = await admin.realm()
    except KeycloakAdminError:
        return None
    return RealmPolicy(
        password_policy=str(realm.get("passwordPolicy") or ""),
        lockout_failures=int(realm.get("failureFactor") or 0) if realm.get("bruteForceProtected") else 0,
        lockout_minutes=int(realm.get("maxFailureWaitSeconds") or 0) // 60,
        session_idle_minutes=int(realm.get("ssoSessionIdleTimeout") or 0) // 60,
        session_max_hours=int(realm.get("ssoSessionMaxLifespan") or 0) // 3600,
    )


async def _out(request: Request, conn: AsyncConnection, tenant_id: uuid.UUID) -> IdentityOut:
    identity = await service.identity_of(conn, tenant_id)
    rows = (await conn.execute(select(TenantIdentityProvider).order_by(TenantIdentityProvider.display_name))).all()
    issuer = request.app.state.settings.keycloak_public_issuer
    return IdentityOut(local_accounts=identity.local_accounts, sso=identity.sso, mfa_required=identity.mfa_required,
                       domains=list(identity.domains), organization=identity.organization_id,
                       providers=[_provider_out(r, issuer) for r in rows], realm=await _realm(request))  # fmt: skip


async def _load(conn: AsyncConnection, provider_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(select(TenantIdentityProvider).where(TenantIdentityProvider.id == provider_id))
    ).first()  # fmt: skip
    if row is None:
        raise not_found("identity_provider")
    return row


async def _reconcile(request: Request, conn: AsyncConnection, tenant_id: uuid.UUID) -> str:
    try:
        return await service.reconcile_organization(conn, _admin(request), tenant_id)
    except KeycloakAdminError as exc:
        raise ProblemError(502, "identity_sync_failed", f"Keycloak did not take the change: {exc}"[:300]) from None


@router.get("", response_model=IdentityOut)
async def get_identity(request: Request, auth: ManageIdentity) -> IdentityOut:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        return await _out(request, conn, auth.tenant_id)


@router.put("", response_model=IdentityOut)
async def update_identity(request: Request, body: IdentityUpdate, auth: ManageIdentity) -> IdentityOut:
    assert auth.tenant_id is not None  # noqa: S101
    if not (body.local_accounts or body.sso):
        raise ProblemError(422, "identity_method_required", "At least one sign-in method must be enabled.")
    domains = _domains(body.domains)
    async with transaction(request, auth) as conn:
        values = {"local_accounts": body.local_accounts, "sso": body.sso, "mfa_required": body.mfa_required,
                  "domains": domains, "updated_by": auth.user_id}  # fmt: skip
        await conn.execute(pg_insert(TenantIdentity).values(tenant_id=auth.tenant_id, **values)
                           .on_conflict_do_update(index_elements=[TenantIdentity.tenant_id], set_=values))  # fmt: skip
        if body.sso and not body.local_accounts:
            active = (await conn.execute(select(TenantIdentityProvider.id)
                                         .where(TenantIdentityProvider.status == "active"))).first()  # fmt: skip
            if active is None:
                raise ProblemError(422, "identity_provider_required",
                                   "Own accounts can be turned off once an SSO provider is active.")  # fmt: skip
        await _reconcile(request, conn, auth.tenant_id)
        await audit(conn, auth, "identity.update", f"tenant:{auth.tenant_id}",
                    {"local_accounts": body.local_accounts, "sso": body.sso, "mfa_required": body.mfa_required,
                     "domains": domains})  # fmt: skip
        return await _out(request, conn, auth.tenant_id)


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(request: Request, body: ProviderCreate, auth: ManageIdentity) -> ProviderOut:
    assert auth.tenant_id is not None  # noqa: S101
    settings = await _checked_settings(request, body.protocol, body.settings)
    if body.protocol == "oidc" and not body.client_secret:
        raise ProblemError(422, "provider_settings_missing", "The OIDC provider needs its client secret.")
    domains = _domains(body.domains)
    if body.sso_only and not domains:
        raise ProblemError(422, "domain_required", "An SSO-only provider needs at least one domain.")
    provider_id = uuid.uuid4()
    try:
        async with transaction(request, auth) as conn:
            await _checked_roles(conn, body.group_roles, body.default_role)
            slug = (await conn.execute(select(Tenant.slug).where(Tenant.id == auth.tenant_id))).scalar_one()
            await conn.execute(pg_insert(TenantIdentityProvider).values(
                id=provider_id, tenant_id=auth.tenant_id, alias=providers.alias_for(slug, body.display_name),
                display_name=body.display_name, protocol=body.protocol, settings=settings, domains=domains,
                sso_only=body.sso_only, jit=body.jit, group_roles=body.group_roles, default_role=body.default_role,
                created_by=auth.user_id,
            ))  # fmt: skip
            organization_id = await _reconcile(request, conn, auth.tenant_id)
            await service.apply_provider(conn, _admin(request), provider_id, organization_id, body.client_secret)
            row = await _load(conn, provider_id)
            await audit(conn, auth, "identity.provider_create", f"identity_provider:{provider_id}",
                        {"alias": row.alias, "protocol": body.protocol, "domains": domains, "sso_only": body.sso_only,
                         "jit": body.jit, "status": row.status},
                        outcome="success" if row.status == "active" else "failure")  # fmt: skip
            return _provider_out(row, request.app.state.settings.keycloak_public_issuer)
    except IntegrityError as exc:
        taken = "domain_taken" in str(exc.orig)
        raise ProblemError(409, "domain_taken" if taken else "identity_provider_taken",
                           "One of the domains already has a provider." if taken
                           else "A provider with that name already exists.") from exc  # fmt: skip


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    request: Request, provider_id: uuid.UUID, body: ProviderUpdate, auth: ManageIdentity
) -> ProviderOut:
    assert auth.tenant_id is not None  # noqa: S101
    try:
        async with transaction(request, auth) as conn:
            row = await _load(conn, provider_id)
            changes: dict[str, Any] = {}
            if body.display_name is not None:
                changes["display_name"] = body.display_name
            if body.settings is not None:
                changes["settings"] = await _checked_settings(request, row.protocol, body.settings)
            if body.domains is not None:
                changes["domains"] = _domains(body.domains)
            for key in ("sso_only", "jit", "group_roles"):
                if getattr(body, key) is not None:
                    changes[key] = getattr(body, key)
            if "default_role" in body.model_fields_set:
                changes["default_role"] = body.default_role
            await _checked_roles(conn, changes.get("group_roles", row.group_roles),
                                 changes.get("default_role", row.default_role))  # fmt: skip
            if changes.get("sso_only", row.sso_only) and not changes.get("domains", row.domains):
                raise ProblemError(422, "domain_required", "An SSO-only provider needs at least one domain.")
            if changes:
                await conn.execute(update(TenantIdentityProvider).where(TenantIdentityProvider.id == provider_id)
                                   .values(**changes))  # fmt: skip
            organization_id = await _reconcile(request, conn, auth.tenant_id)
            await service.apply_provider(conn, _admin(request), provider_id, organization_id, body.client_secret)
            row = await _load(conn, provider_id)
            await audit(conn, auth, "identity.provider_update", f"identity_provider:{provider_id}",
                        {"changed": sorted(changes), "access_rotated": body.client_secret is not None,
                         "status": row.status}, outcome="success" if row.status == "active" else "failure")  # fmt: skip
            return _provider_out(row, request.app.state.settings.keycloak_public_issuer)
    except IntegrityError as exc:
        raise ProblemError(409, "domain_taken", "One of the domains already has a provider.") from exc


@router.post("/providers/{provider_id}:apply", response_model=ProviderOut)
async def apply_provider(request: Request, provider_id: uuid.UUID, auth: ManageIdentity) -> ProviderOut:
    """Writes the provider to Keycloak again (after a failure), keeping its secret."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        await _load(conn, provider_id)
        organization_id = await _reconcile(request, conn, auth.tenant_id)
        await service.apply_provider(conn, _admin(request), provider_id, organization_id, None)
        row = await _load(conn, provider_id)
        await audit(conn, auth, "identity.provider_apply", f"identity_provider:{provider_id}", {"status": row.status},
                    outcome="success" if row.status == "active" else "failure")  # fmt: skip
        return _provider_out(row, request.app.state.settings.keycloak_public_issuer)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(request: Request, provider_id: uuid.UUID, auth: ManageIdentity) -> None:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        row = await _load(conn, provider_id)
        identity = await service.identity_of(conn, auth.tenant_id)
        others = (await conn.execute(select(TenantIdentityProvider.id).where(
            TenantIdentityProvider.id != provider_id, TenantIdentityProvider.status == "active"))).first()  # fmt: skip
        if not identity.local_accounts and others is None:
            raise ProblemError(409, "identity_provider_required",
                               "Turn own accounts on before deleting the last SSO provider.")  # fmt: skip
        try:
            await _admin(request).delete_identity_provider(row.alias)
        except KeycloakAdminError as exc:
            raise ProblemError(502, "identity_sync_failed", f"Keycloak did not take the change: {exc}"[:300]) from None
        await conn.execute(delete(TenantIdentityProvider).where(TenantIdentityProvider.id == provider_id))
        await _reconcile(request, conn, auth.tenant_id)
        await audit(conn, auth, "identity.provider_delete", f"identity_provider:{provider_id}", {"alias": row.alias})
