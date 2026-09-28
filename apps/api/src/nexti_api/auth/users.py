"""Platform users at sign-in: find them by Keycloak `sub`, link them by verified e-mail the first time."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.auth.oidc import IdentityClaims
from nexti_api.db.models import AppUser, PlatformRoleAssignment, Tenant
from nexti_api.db.session import DbScope, scoped_connection


class SignInDeniedError(Exception):
    """The identity is valid in Keycloak but has no usable platform account. `code` is stable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TenantRef:
    id: uuid.UUID
    slug: str
    name: str


# Core connections return rows, not ORM objects: select the columns explicitly.
_USER_COLUMNS = (
    AppUser.id,
    AppUser.email,
    AppUser.display_name,
    AppUser.locale,
    AppUser.status,
    AppUser.keycloak_sub,
)


@dataclass(frozen=True)
class UserProfile:
    id: uuid.UUID
    email: str
    display_name: str
    locale: str


async def sign_in(engine: AsyncEngine, claims: IdentityClaims) -> UserProfile:
    """Resolve the platform user of a validated identity and record the login time."""
    verified_email = claims.email if claims.email_verified else None
    scope = DbScope(auth_sub=claims.sub, auth_email=verified_email)
    async with scoped_connection(engine, scope) as conn:
        user = (await conn.execute(select(*_USER_COLUMNS).where(AppUser.keycloak_sub == claims.sub))).one_or_none()
        if user is None and verified_email:
            # First sign-in of a seeded or invited user: link the Keycloak account by its verified e-mail.
            user = (
                await conn.execute(select(*_USER_COLUMNS).where(func.lower(AppUser.email) == verified_email))
            ).one_or_none()
            if user is not None and user.keycloak_sub not in (None, claims.sub):
                raise SignInDeniedError("account_conflict")
        if user is None:
            raise SignInDeniedError("no_platform_access")
        if user.status != "active":
            raise SignInDeniedError("account_disabled")
        await conn.execute(
            update(AppUser).where(AppUser.id == user.id).values(keycloak_sub=claims.sub, last_login_at=func.now())
        )
        return UserProfile(user.id, user.email, user.display_name, user.locale)


async def load_profile(engine: AsyncEngine, user_id: uuid.UUID) -> UserProfile | None:
    async with scoped_connection(engine, DbScope(user_id=user_id)) as conn:
        user = (await conn.execute(select(*_USER_COLUMNS).where(AppUser.id == user_id))).one_or_none()
    if user is None or user.status != "active":
        return None
    return UserProfile(user.id, user.email, user.display_name, user.locale)


async def user_tenants(engine: AsyncEngine, user_id: uuid.UUID) -> list[TenantRef]:
    """Tenants where the user has an active membership (RLS policy tenant_member), by name."""
    async with scoped_connection(engine, DbScope(user_id=user_id)) as conn:
        rows = (await conn.execute(select(Tenant.id, Tenant.slug, Tenant.name).order_by(Tenant.name))).all()
    return [TenantRef(r.id, r.slug, r.name) for r in rows]


async def platform_roles(engine: AsyncEngine, user_id: uuid.UUID) -> list[str]:
    async with scoped_connection(engine, DbScope(user_id=user_id)) as conn:
        rows = await conn.execute(
            select(PlatformRoleAssignment.role).where(PlatformRoleAssignment.user_id == user_id).order_by("role")
        )
        return list(rows.scalars())


async def set_locale(engine: AsyncEngine, user_id: uuid.UUID, locale: str) -> None:
    async with scoped_connection(engine, DbScope(user_id=user_id)) as conn:
        await conn.execute(update(AppUser).where(AppUser.id == user_id).values(locale=locale))
