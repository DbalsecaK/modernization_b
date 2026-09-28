"""Tenant creation: the tenant row plus its copy of the base roles (roles are configurable bundles, 16.2)."""

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.db.models import Role, RolePermission, Tenant
from nexti_core.authz_catalog import BASE_ROLES


async def create_tenant(
    conn: AsyncConnection,
    *,
    slug: str,
    name: str,
    deployment_model: str = "sharedSaas",
    default_language: str = "en",
) -> uuid.UUID:
    """Create a tenant with its base roles. Requires platform scope (or the migration role)."""
    tenant_id = (
        await conn.execute(
            insert(Tenant)
            .values(slug=slug, name=name, deployment_model=deployment_model, default_language=default_language)
            .returning(Tenant.id)
        )
    ).scalar_one()
    for base in BASE_ROLES:
        role_id = (
            await conn.execute(
                insert(Role)
                .values(tenant_id=tenant_id, key=base.key, scope=base.scope, name=base.name, is_system=True)
                .returning(Role.id)
            )
        ).scalar_one()
        if base.permissions:
            await conn.execute(
                insert(RolePermission),
                [
                    {"tenant_id": tenant_id, "role_id": role_id, "role_scope": base.scope, "permission_key": key}
                    for key in base.permissions
                ],
            )
    return tenant_id
