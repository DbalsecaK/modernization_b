"""Fictitious development data: the tenants and projects of the prototype and the users of the dev realm.

Users are matched to Keycloak by e-mail on their first sign-in (their `sub` is unknown until then).
Runs as the schema owner and only in development or test.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.db.models import AppUser, Membership, PlatformRoleAssignment, Project, Role, RoleAssignment, Tenant
from nexti_api.tenancy import create_tenant


@dataclass(frozen=True)
class SeedUser:
    email: str
    name: str
    platform_role: str | None = None


@dataclass(frozen=True)
class SeedAssignment:
    email: str
    tenant: str
    role: str
    project: str | None = None


TENANTS = (
    ("andes-bank", "Andes Bank", "customerCloud", "es"),
    ("pacific-cu", "Pacific Credit Union", "sharedSaas", "en"),
    ("nexti-internal", "NexTI Internal", "sharedSaas", "en"),
)
PROJECTS = (
    ("andes-bank", "Card Management — CICS to Spring Boot"),
    ("andes-bank", "Interest Accrual SP — Sybase to .NET 10"),
    ("andes-bank", "Branch Portal — ASPX to React + .NET 10"),
    ("pacific-cu", "Digital Onboarding — from Figma and user stories"),
    ("nexti-internal", "Loan Simulator — new feature"),
)
USERS = (
    SeedUser("admin@nexti.example", "Platform Admin", platform_role="superAdmin"),
    SeedUser("cruiz@nexti.example", "Carlos Ruiz"),
    SeedUser("mtorres@andesbank.example", "María Torres"),
    SeedUser("landrade@andesbank.example", "Luis Andrade"),
    SeedUser("avelez@pacificcu.example", "Ana Vélez"),
)
ASSIGNMENTS = (
    SeedAssignment("admin@nexti.example", "nexti-internal", "tenantAdmin"),
    SeedAssignment("cruiz@nexti.example", "nexti-internal", "analyst", "Loan Simulator — new feature"),
    SeedAssignment("cruiz@nexti.example", "nexti-internal", "developer", "Loan Simulator — new feature"),
    SeedAssignment("cruiz@nexti.example", "andes-bank", "developer", "Card Management — CICS to Spring Boot"),
    SeedAssignment("mtorres@andesbank.example", "andes-bank", "tenantAdmin"),
    SeedAssignment("mtorres@andesbank.example", "andes-bank", "projectOwner", "Card Management — CICS to Spring Boot"),
    SeedAssignment("landrade@andesbank.example", "andes-bank", "architect", "Card Management — CICS to Spring Boot"),
    SeedAssignment(
        "avelez@pacificcu.example", "pacific-cu", "businessReviewer", "Digital Onboarding — from Figma and user stories"
    ),
)


async def seed_dev(conn: AsyncConnection) -> bool:
    """Insert the development data. Returns False (and changes nothing) if it was already seeded."""
    if (await conn.execute(select(Tenant.id).where(Tenant.slug == TENANTS[0][0]))).first():
        return False

    tenants: dict[str, uuid.UUID] = {}
    for slug, name, deployment, language in TENANTS:
        tenants[slug] = await create_tenant(
            conn, slug=slug, name=name, deployment_model=deployment, default_language=language
        )

    projects: dict[str, uuid.UUID] = {}
    for slug, name in PROJECTS:
        stmt = insert(Project).values(tenant_id=tenants[slug], name=name).returning(Project.id)
        projects[name] = (await conn.execute(stmt)).scalar_one()

    users: dict[str, uuid.UUID] = {}
    for user in USERS:
        stmt = insert(AppUser).values(email=user.email, display_name=user.name).returning(AppUser.id)
        users[user.email] = (await conn.execute(stmt)).scalar_one()
        if user.platform_role:
            await conn.execute(
                insert(PlatformRoleAssignment).values(user_id=users[user.email], role=user.platform_role)
            )

    for tenant_slug, email in sorted({(a.tenant, a.email) for a in ASSIGNMENTS}):
        await conn.execute(insert(Membership).values(tenant_id=tenants[tenant_slug], user_id=users[email]))

    for a in ASSIGNMENTS:
        tenant_id = tenants[a.tenant]
        role = (
            await conn.execute(select(Role.id, Role.scope).where(Role.tenant_id == tenant_id, Role.key == a.role))
        ).one()
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=tenant_id,
                user_id=users[a.email],
                role_id=role.id,
                scope=role.scope,
                project_id=projects[a.project] if a.project else None,
            )
        )
    return True
