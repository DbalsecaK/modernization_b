"""Roles of the active tenant as configurable bundles of permissions (the permission matrix, spec 16.2)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, authenticated, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.db.models import Role, RoleAssignment, RolePermission
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.authz_catalog import PERMISSIONS, permission_scopes

router = APIRouter(prefix="/api/v1", tags=["roles"])
ManageUsers = Annotated[Authorized, Depends(require_tenant("users.manage"))]
Scope = Literal["tenant", "project"]


class PermissionOut(ApiModel):
    key: str
    scopes: list[Scope]
    description: str


class RoleOut(ApiModel):
    id: uuid.UUID
    key: str
    scope: Scope
    name: str
    is_system: bool
    permissions: list[str]
    members: int


class RoleCreate(ApiModel):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9]{1,62}$")
    name: str = Field(min_length=1, max_length=200)
    scope: Scope
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class RolePermissionsIn(ApiModel):
    permissions: list[str]


def _check_permissions(scope: str, keys: list[str]) -> list[str]:
    scopes = permission_scopes()
    invalid = sorted(k for k in set(keys) if scope not in scopes.get(k, ()))
    if invalid:
        raise ProblemError(
            422, "invalid_permission", f"Not valid for a {scope} role: {', '.join(invalid)}.", permissions=invalid
        )
    return sorted(set(keys))


async def load_roles(conn: AsyncConnection, role_id: uuid.UUID | None = None) -> list[RoleOut]:
    query = select(Role.id, Role.key, Role.scope, Role.name, Role.is_system).order_by(Role.scope.desc(), Role.key)
    if role_id is not None:
        query = query.where(Role.id == role_id)
    roles = (await conn.execute(query)).all()
    grants: dict[uuid.UUID, list[str]] = {}
    for g in (await conn.execute(select(RolePermission.role_id, RolePermission.permission_key))).all():
        grants.setdefault(g.role_id, []).append(g.permission_key)
    counts = dict(
        (
            await conn.execute(
                select(RoleAssignment.role_id, func.count(func.distinct(RoleAssignment.user_id))).group_by(
                    RoleAssignment.role_id
                )
            )
        ).all()
    )
    return [
        RoleOut(
            id=r.id,
            key=r.key,
            scope=r.scope,
            name=r.name,
            is_system=r.is_system,
            permissions=sorted(grants.get(r.id, [])),
            members=counts.get(r.id, 0),
        )
        for r in roles
    ]


async def _role(conn: AsyncConnection, role_id: uuid.UUID) -> RoleOut:
    found = await load_roles(conn, role_id)
    if not found:
        raise not_found("role")
    return found[0]


@router.get("/permissions", response_model=list[PermissionOut], tags=["roles"])
async def list_permissions(auth: Annotated[Authorized, Depends(authenticated())]) -> list[PermissionOut]:
    """The permission catalog (the rows of the matrix)."""
    return [PermissionOut(key=p.key, scopes=list(p.scopes), description=p.description) for p in PERMISSIONS]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(request: Request, auth: ManageUsers) -> list[RoleOut]:
    async with transaction(request, auth) as conn:
        return await load_roles(conn)


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(request: Request, body: RoleCreate, auth: ManageUsers) -> RoleOut:
    permissions = _check_permissions(body.scope, body.permissions)
    assert auth.tenant_id is not None  # noqa: S101
    try:
        async with transaction(request, auth) as conn:
            async with authz_change(conn, auth.tenant_id):
                role_id = (
                    await conn.execute(
                        insert(Role)
                        .values(tenant_id=auth.tenant_id, key=body.key, scope=body.scope, name=body.name)
                        .returning(Role.id)
                    )
                ).scalar_one()
                if permissions:
                    await conn.execute(
                        insert(RolePermission),
                        [
                            {
                                "tenant_id": auth.tenant_id,
                                "role_id": role_id,
                                "role_scope": body.scope,
                                "permission_key": k,
                            }
                            for k in permissions
                        ],
                    )
            await audit(conn, auth, "role.create", f"role:{role_id}", {"key": body.key, "permissions": permissions})
            return await _role(conn, role_id)
    except IntegrityError as exc:
        raise ProblemError(409, "role_key_taken", "A role with that key already exists.") from exc


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(request: Request, role_id: uuid.UUID, body: RoleUpdate, auth: ManageUsers) -> RoleOut:
    async with transaction(request, auth) as conn:
        result = await conn.execute(update(Role).where(Role.id == role_id).values(name=body.name))
        if result.rowcount == 0:
            raise not_found("role")
        await audit(conn, auth, "role.update", f"role:{role_id}", {"name": body.name})
        return await _role(conn, role_id)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(request: Request, role_id: uuid.UUID, auth: ManageUsers) -> None:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        role = await _role(conn, role_id)
        if role.is_system:
            raise ProblemError(409, "system_role", "Base roles cannot be deleted; edit their permissions instead.")
        if role.members:
            raise ProblemError(409, "role_in_use", "Remove the role from its members before deleting it.")
        async with authz_change(conn, auth.tenant_id):
            await conn.execute(delete(Role).where(Role.id == role_id))
        await audit(conn, auth, "role.delete", f"role:{role_id}", {"key": role.key})


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
async def set_role_permissions(
    request: Request, role_id: uuid.UUID, body: RolePermissionsIn, auth: ManageUsers
) -> RoleOut:
    """Replace the bundle of a role (one column of the matrix). Takes effect for all its members."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        role = await _role(conn, role_id)
        permissions = _check_permissions(role.scope, body.permissions)
        added = sorted(set(permissions) - set(role.permissions))
        removed = sorted(set(role.permissions) - set(permissions))
        async with authz_change(conn, auth.tenant_id):
            if removed:
                await conn.execute(
                    delete(RolePermission).where(
                        RolePermission.role_id == role_id, RolePermission.permission_key.in_(removed)
                    )
                )
            if added:
                await conn.execute(
                    insert(RolePermission),
                    [
                        {"tenant_id": auth.tenant_id, "role_id": role_id, "role_scope": role.scope, "permission_key": k}
                        for k in added
                    ],
                )
        if added or removed:
            await audit(conn, auth, "role.permissions_change", f"role:{role_id}", {"added": added, "removed": removed})
        return await _role(conn, role_id)
