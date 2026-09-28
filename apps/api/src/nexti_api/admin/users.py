"""Users of the active tenant (their memberships and roles). Credentials live in Keycloak."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.db.models import AppUser, Membership, Project, Role, RoleAssignment

router = APIRouter(prefix="/api/v1/users", tags=["users"])
ManageUsers = Annotated[Authorized, Depends(require_tenant("users.manage"))]


class RoleGrant(ApiModel):
    assignment_id: uuid.UUID
    role_id: uuid.UUID
    role_key: str
    scope: Literal["tenant", "project"]
    project_id: uuid.UUID | None
    project_name: str | None


class MemberOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    status: Literal["invited", "active", "suspended"]
    last_login_at: datetime | None
    roles: list[RoleGrant]


class MemberUpdate(ApiModel):
    status: Literal["active", "suspended"]


async def load_members(conn: AsyncConnection, user_id: uuid.UUID | None = None) -> list[MemberOut]:
    """Members of the active tenant (RLS), optionally one of them."""
    query = (
        select(AppUser.id, AppUser.email, AppUser.display_name, AppUser.last_login_at, Membership.status)
        .join(Membership, Membership.user_id == AppUser.id)
        .order_by(AppUser.display_name)
    )
    if user_id is not None:
        query = query.where(AppUser.id == user_id)
    members = (await conn.execute(query)).all()
    grants_query = (
        select(
            RoleAssignment.id,
            RoleAssignment.user_id,
            RoleAssignment.role_id,
            RoleAssignment.scope,
            RoleAssignment.project_id,
            Role.key,
            Project.name,
        )
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(Project, Project.id == RoleAssignment.project_id)
        .order_by(Role.key)
    )
    if user_id is not None:
        grants_query = grants_query.where(RoleAssignment.user_id == user_id)
    grants: dict[uuid.UUID, list[RoleGrant]] = {}
    for g in (await conn.execute(grants_query)).all():
        grants.setdefault(g.user_id, []).append(
            RoleGrant(
                assignment_id=g.id,
                role_id=g.role_id,
                role_key=g.key,
                scope=g.scope,
                project_id=g.project_id,
                project_name=g.name,
            )
        )
    return [
        MemberOut(
            id=m.id,
            email=m.email,
            display_name=m.display_name,
            status=m.status,
            last_login_at=m.last_login_at,
            roles=grants.get(m.id, []),
        )
        for m in members
    ]


def _not_self(auth: Authorized, user_id: uuid.UUID) -> None:
    if user_id == auth.user_id:
        raise ProblemError(409, "cannot_change_self", "You cannot change your own membership.")


@router.get("", response_model=list[MemberOut])
async def list_users(request: Request, auth: ManageUsers) -> list[MemberOut]:
    async with transaction(request, auth) as conn:
        return await load_members(conn)


@router.get("/{user_id}", response_model=MemberOut)
async def get_user(request: Request, user_id: uuid.UUID, auth: ManageUsers) -> MemberOut:
    async with transaction(request, auth) as conn:
        found = await load_members(conn, user_id)
    if not found:
        raise not_found("user")
    return found[0]


@router.patch("/{user_id}", response_model=MemberOut)
async def update_user(request: Request, user_id: uuid.UUID, body: MemberUpdate, auth: ManageUsers) -> MemberOut:
    """Suspend or reactivate a member in the active tenant. Suspending revokes every permission at once."""
    _not_self(auth, user_id)
    assert auth.tenant_id is not None  # noqa: S101 (require_tenant guarantees it)
    async with transaction(request, auth) as conn:
        async with authz_change(conn, auth.tenant_id):
            result = await conn.execute(
                update(Membership)
                .where(Membership.user_id == user_id, Membership.status != "invited")
                .values(status=body.status)
            )
        if result.rowcount == 0:
            raise not_found("user")
        await audit(conn, auth, "user.status_change", f"user:{user_id}", {"status": body.status})
        found = await load_members(conn, user_id)
    return found[0]


@router.delete("/{user_id}/membership", status_code=204)
async def remove_user(request: Request, user_id: uuid.UUID, auth: ManageUsers) -> None:
    """Remove the person from the tenant (their role assignments go with the membership)."""
    _not_self(auth, user_id)
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        async with authz_change(conn, auth.tenant_id):
            result = await conn.execute(delete(Membership).where(Membership.user_id == user_id))
        if result.rowcount == 0:
            raise not_found("user")
        await audit(conn, auth, "user.remove", f"user:{user_id}")
