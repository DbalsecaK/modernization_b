"""The tenant's sign-in rules at the BFF (ADR-0022), checked by code on the validated ID token.

- Home-realm discovery: the domain of the e-mail says which provider the login goes to and whether the tenant asks
  own accounts for a second factor.
- "SSO only": a domain with an SSO-only provider never signs in with a password.
- A tenant without own accounts only lets in its providers' users; "MFA required" asks own accounts for `acr=mfa`.
- JIT and groups: a user of a provider with JIT gets an account and a membership the first time; at every sign-in the
  groups of the provider give the tenant roles of its mapping (assignments with source `idp`; manual ones stay).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.auth.oidc import IdentityClaims
from nexti_api.authz.sync import authz_change
from nexti_api.identity import providers
from nexti_api.observability import log
from nexti_core.db.models import AppUser, Membership, Role, RoleAssignment, TenantIdentity, TenantIdentityProvider
from nexti_core.db.session import DbScope, scoped_connection

MFA = "mfa"  # the acr the client nexti-bff maps to the second level of authentication


@dataclass(frozen=True)
class Route:
    """What the login page needs to know about a domain, before anyone signs in."""

    tenant_id: uuid.UUID
    tenant_slug: str
    alias: str | None
    sso_only: bool
    mfa_required: bool


@dataclass(frozen=True)
class TenantRules:
    local_accounts: bool
    mfa_required: bool


def domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


async def route_for(engine: AsyncEngine, email: str | None) -> Route | None:
    domain = domain_of(email)
    if domain is None:
        return None
    async with scoped_connection(engine, DbScope()) as conn:
        row = (await conn.execute(text("SELECT * FROM identity_route(:d)"), {"d": domain})).first()
    if row is None:
        return None
    return Route(row.tenant_id, row.tenant_slug, row.alias, bool(row.sso_only), bool(row.mfa_required))


def sso_required(route: Route | None, claims: IdentityClaims) -> bool:
    """The e-mail's domain is SSO-only and the user did not come through its provider."""
    return route is not None and route.alias is not None and route.sso_only and claims.identity_provider != route.alias


async def tenant_rules(engine: AsyncEngine, tenant_id: uuid.UUID, user_id: uuid.UUID) -> TenantRules:
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id, user_id=user_id)) as conn:
        row = (
            await conn.execute(select(TenantIdentity.local_accounts, TenantIdentity.mfa_required)
                               .where(TenantIdentity.tenant_id == tenant_id))
        ).first()  # fmt: skip
    return TenantRules(row.local_accounts, row.mfa_required) if row else TenantRules(True, False)


async def _provider(engine: AsyncEngine, claims: IdentityClaims) -> tuple[uuid.UUID, Any] | None:
    """The provider the user came through (alias in the validated token) and its tenant."""
    if not claims.identity_provider:
        return None
    async with scoped_connection(engine, DbScope()) as conn:
        tenant_id = (
            await conn.execute(text("SELECT identity_provider_tenant(:a)"), {"a": claims.identity_provider})
        ).scalar()  # fmt: skip
    if tenant_id is None:
        return None
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
        row = (
            await conn.execute(select(TenantIdentityProvider)
                               .where(TenantIdentityProvider.alias == claims.identity_provider))
        ).first()  # fmt: skip
    return (tenant_id, row) if row is not None else None


def _domain_allowed(provider: Any, email: str | None) -> bool:
    """A provider speaks for its own domains only (when it declares some)."""
    return not provider.domains or domain_of(email) in provider.domains


async def provision(engine: AsyncEngine, claims: IdentityClaims) -> bool:
    """JIT: creates the account of a provider's user that the platform does not know. Returns whether it did."""
    found = await _provider(engine, claims)
    if found is None or not claims.email or not claims.email_verified:
        return False
    tenant_id, provider = found
    if not provider.jit or not _domain_allowed(provider, claims.email):
        return False
    scope = DbScope(tenant_id=tenant_id, auth_sub=claims.sub, auth_email=claims.email)
    async with scoped_connection(engine, scope) as conn:
        existing = (await conn.execute(select(AppUser.id).where(func.lower(AppUser.email) == claims.email))).first()
        if existing is not None:
            return False  # an account with that e-mail exists: linking it is sign_in's job, not JIT's
        await conn.execute(insert(AppUser).values(email=claims.email, display_name=claims.name or claims.email,
                                                  keycloak_sub=claims.sub))  # fmt: skip
    return True


async def sync_groups(engine: AsyncEngine, claims: IdentityClaims, user_id: uuid.UUID) -> list[str]:
    """In the provider's tenant: the membership (JIT) and the roles its groups give. Returns the role keys."""
    found = await _provider(engine, claims)
    if found is None:
        return []
    tenant_id, provider = found
    if not _domain_allowed(provider, claims.email):
        return []
    wanted = providers.roles_for(list(claims.idp_groups), dict(provider.group_roles or {}), provider.default_role)
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id, user_id=user_id)) as conn:
        member = (
            await conn.execute(select(Membership.status)
                               .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id))
        ).first()  # fmt: skip
        if member is None and not provider.jit:
            return []
        if member is not None and member.status != "active":
            return []  # a suspended person stays suspended, whatever the provider says
        async with authz_change(conn, tenant_id):
            if member is None:
                await conn.execute(insert(Membership).values(tenant_id=tenant_id, user_id=user_id))
            roles = {
                r.key: r.id
                for r in (await conn.execute(select(Role.key, Role.id).where(Role.scope == "tenant",
                                                                             Role.key.in_(wanted or {""})))).all()
            }  # fmt: skip
            keep = list(roles.values()) or [uuid.uuid4()]
            await conn.execute(delete(RoleAssignment).where(
                RoleAssignment.user_id == user_id, RoleAssignment.source == "idp",
                RoleAssignment.project_id.is_(None), RoleAssignment.role_id.not_in(keep),
            ))  # fmt: skip
            for role_id in roles.values():
                await conn.execute(pg_insert(RoleAssignment).values(
                    tenant_id=tenant_id, user_id=user_id, role_id=role_id, scope="tenant", source="idp",
                ).on_conflict_do_nothing())  # fmt: skip
    return sorted(roles)


async def organization_member(state: Any, engine: AsyncEngine, tenant_id: uuid.UUID, user_id: uuid.UUID,
                              sub: str) -> None:  # fmt: skip
    """Best effort: the user joins the tenant's Organization, so the next token names it. Never blocks a login."""
    admin = getattr(state, "keycloak_admin", None)
    if admin is None:
        return
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id, user_id=user_id)) as conn:
        organization_id = (
            await conn.execute(select(TenantIdentity.organization_id).where(TenantIdentity.tenant_id == tenant_id))
        ).scalar()  # fmt: skip
    if not organization_id:
        return
    try:
        await admin.add_organization_member(organization_id, sub)
    except Exception as exc:
        log.warning("organization_member_failed", error=type(exc).__name__)
