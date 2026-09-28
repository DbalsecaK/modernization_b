"""The OpenFGA tuples that PostgreSQL implies. Both the outbox and the reconciliation are diffs of this set.

Only active memberships produce tuples: suspending or removing a member revokes everything at once.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.authz import names
from nexti_api.authz.names import Tuple
from nexti_core.authz_catalog import TENANT_ADMIN_ROLE, PlatformRole
from nexti_core.db.models import (
    Membership,
    PlatformRoleAssignment,
    Project,
    Role,
    RoleAssignment,
    RolePermission,
    Tenant,
)


async def expected_tuples(conn: AsyncConnection, tenant_id: uuid.UUID) -> set[Tuple]:
    """All tuples of one tenant. The connection must see the tenant (its scope or platform scope)."""
    if (await conn.execute(select(Tenant.id).where(Tenant.id == tenant_id))).first() is None:
        return set()
    tenant = names.tenant(tenant_id)
    out = {Tuple(names.PLATFORM, "platform", tenant)}

    roles = (await conn.execute(select(Role.id, Role.key, Role.scope).where(Role.tenant_id == tenant_id))).all()
    grants = (
        await conn.execute(
            select(RolePermission.role_id, RolePermission.permission_key).where(RolePermission.tenant_id == tenant_id)
        )
    ).all()
    permissions: dict[uuid.UUID, list[str]] = {}
    for g in grants:
        permissions.setdefault(g.role_id, []).append(g.permission_key)
    projects = list((await conn.execute(select(Project.id).where(Project.tenant_id == tenant_id))).scalars())

    for p in projects:
        out.add(Tuple(tenant, "tenant", names.project(p)))
    for r in roles:
        if r.scope == "tenant":
            # The administrator holds every tenant permission through `admin`; its bundle adds nothing.
            if r.key != TENANT_ADMIN_ROLE:
                for key in permissions.get(r.id, []):
                    out.add(Tuple(names.role_assignees(r.id), names.relation(key), tenant))
        else:
            for p in projects:
                assignees = names.binding_assignees(p, r.id)
                out.add(Tuple(assignees, "member", names.project(p)))
                for key in permissions.get(r.id, []):
                    out.add(Tuple(assignees, names.relation(key), names.project(p)))

    members = list(
        (
            await conn.execute(
                select(Membership.user_id).where(Membership.tenant_id == tenant_id, Membership.status == "active")
            )
        ).scalars()
    )
    for u in members:
        out.add(Tuple(names.user(u), "member", tenant))

    assignments = (
        await conn.execute(
            select(RoleAssignment.user_id, RoleAssignment.role_id, RoleAssignment.project_id, Role.key)
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(
                Membership,
                (Membership.tenant_id == RoleAssignment.tenant_id) & (Membership.user_id == RoleAssignment.user_id),
            )
            .where(RoleAssignment.tenant_id == tenant_id, Membership.status == "active")
        )
    ).all()
    for a in assignments:
        who = names.user(a.user_id)
        if a.project_id is not None:
            out.add(Tuple(who, "assignee", names.binding(a.project_id, a.role_id)))
        elif a.key == TENANT_ADMIN_ROLE:
            out.add(Tuple(who, "admin", tenant))
        else:
            out.add(Tuple(who, "assignee", names.role(a.role_id)))
    return out


async def expected_platform_tuples(conn: AsyncConnection) -> set[Tuple]:
    rows = (await conn.execute(select(PlatformRoleAssignment.user_id, PlatformRoleAssignment.role))).all()
    out = set()
    for r in rows:
        role: PlatformRole = r.role
        out.add(Tuple(names.user(r.user_id), names.PLATFORM_RELATION[role], names.PLATFORM))
    return out
