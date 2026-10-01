"""The tenant's identity in Keycloak (ADR-0022): the platform is the source of truth and Keycloak follows it.

- The Organization of the tenant (alias = slug) carries the tenant's domains and the domains of its providers, and has
  as members the tenant's people who already have a Keycloak account, so the token says which tenant they sign in to.
- Each provider is a Keycloak identity provider linked to the Organization; its status says whether Keycloak took it.
"""

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.identity import providers
from nexti_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError
from nexti_core.db.models import AppUser, Membership, Tenant, TenantIdentity, TenantIdentityProvider


async def identity_of(conn: AsyncConnection, tenant_id: uuid.UUID) -> Any:
    """The tenant's identity row, or the defaults when it has never been configured."""
    row = (await conn.execute(select(TenantIdentity).where(TenantIdentity.tenant_id == tenant_id))).first()
    if row is not None:
        return row
    return TenantIdentity(tenant_id=tenant_id, local_accounts=True, sso=False, second_factor=False, domains=[],
                          organization_id=None)  # fmt: skip


async def reconcile_organization(conn: AsyncConnection, admin: KeycloakAdmin, tenant_id: uuid.UUID) -> str:
    """Creates or updates the tenant's Organization and adds its members; returns the Organization id."""
    tenant = (await conn.execute(select(Tenant.slug, Tenant.name).where(Tenant.id == tenant_id))).one()
    identity = await identity_of(conn, tenant_id)
    provider_domains = (await conn.execute(select(TenantIdentityProvider.domains))).scalars().all()
    domains = sorted({*identity.domains, *(d for ds in provider_domains for d in ds)})
    organization_id = await admin.save_organization(tenant.slug, tenant.name, domains, identity.organization_id)
    await conn.execute(
        pg_insert(TenantIdentity)
        .values(tenant_id=tenant_id, organization_id=organization_id)
        .on_conflict_do_update(index_elements=[TenantIdentity.tenant_id], set_={"organization_id": organization_id})
    )
    subs = (
        await conn.execute(
            select(AppUser.keycloak_sub)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.tenant_id == tenant_id, Membership.status == "active", AppUser.keycloak_sub.is_not(None))
        )
    ).scalars().all()  # fmt: skip
    current = await admin.organization_members(organization_id)
    for sub in sorted({str(s) for s in subs if s} - current):
        await admin.add_organization_member(organization_id, str(sub))
    return organization_id


async def apply_provider(
    conn: AsyncConnection, admin: KeycloakAdmin, provider_id: uuid.UUID, organization_id: str,
    client_secret: str | None,
) -> bool:  # fmt: skip
    """Writes the provider to Keycloak and links it to the Organization; records whether it worked."""
    row = (
        await conn.execute(select(TenantIdentityProvider).where(TenantIdentityProvider.id == provider_id))
    ).one()  # fmt: skip
    settings = dict(row.settings or {})
    try:
        imported = None
        if row.protocol == "saml" and settings.get("metadata_url"):
            imported = await admin.import_saml_metadata(settings["metadata_url"])
        domain = row.domains[0] if row.domains else None
        representation = providers.representation(row.alias, row.display_name, row.protocol, settings, client_secret,
                                                  domain, imported)  # fmt: skip
        await admin.save_identity_provider(representation, providers.mappers(row.protocol, settings))
        await admin.link_identity_provider(organization_id, row.alias)
        status, error = "active", None
    except KeycloakAdminError as exc:
        status, error = "failed", str(exc)[:500]
    await conn.execute(
        update(TenantIdentityProvider)
        .where(TenantIdentityProvider.id == provider_id)
        .values(status=status, last_error=error)
    )
    return status == "active"
