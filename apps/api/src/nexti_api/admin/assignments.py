"""Role assignments: a tenant role, or a project role in one project (the per-project role of spec 16.1).

Tenant roles need users.manage. Project roles need users.manage or project.configure on that project, so a
project owner can manage the team of their own project.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, deny, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.db.models import Membership, Project, Role, RoleAssignment
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/role-assignments", tags=["roles"])
# Any member reaches the handler; the handler decides between users.manage and project.configure.
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]


class AssignmentOut(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    role_key: str
    scope: Literal["tenant", "project"]
    project_id: uuid.UUID | None
    created_at: datetime


class AssignmentCreate(ApiModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    project_id: uuid.UUID | None = None


COLUMNS = (
    RoleAssignment.id,
    RoleAssignment.user_id,
    RoleAssignment.role_id,
    Role.key.label("role_key"),
    RoleAssignment.scope,
    RoleAssignment.project_id,
    RoleAssignment.created_at,
)


async def _authorize(request: Request, auth: Authorized, project_id: uuid.UUID | None) -> None:
    fga = request.app.state.fga
    if fga is None:
        raise ProblemError(503, "authorization_unavailable", "Authorization is not available.")
    user = names.user(auth.user_id)
    assert auth.tenant_id is not None  # noqa: S101
    if await fga.check(user, "users_manage", names.tenant(auth.tenant_id)):
        return
    if project_id is not None and await fga.check(user, "project_configure", names.project(project_id)):
        return
    target = names.project(project_id) if project_id else names.tenant(auth.tenant_id)
    await deny(request, auth.session, auth.tenant_id, "users.manage|project.configure", target)


async def _load(conn: AsyncConnection, assignment_id: uuid.UUID) -> AssignmentOut:
    row = (
        await conn.execute(
            select(*COLUMNS).join(Role, Role.id == RoleAssignment.role_id).where(RoleAssignment.id == assignment_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("role_assignment")
    return AssignmentOut.model_validate(row, from_attributes=True)


@router.get("", response_model=list[AssignmentOut])
async def list_assignments(
    request: Request,
    auth: Annotated[Authorized, Depends(require_tenant("users.manage"))],
    user_id: Annotated[uuid.UUID | None, Query(alias="userId")] = None,
    project_id: Annotated[uuid.UUID | None, Query(alias="projectId")] = None,
) -> list[AssignmentOut]:
    query = select(*COLUMNS).join(Role, Role.id == RoleAssignment.role_id).order_by(RoleAssignment.created_at)
    if user_id is not None:
        query = query.where(RoleAssignment.user_id == user_id)
    if project_id is not None:
        query = query.where(RoleAssignment.project_id == project_id)
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(query)).all()
    return [AssignmentOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=AssignmentOut, status_code=201)
async def assign(request: Request, body: AssignmentCreate, auth: TenantMember) -> AssignmentOut:
    assert auth.tenant_id is not None  # noqa: S101
    await _authorize(request, auth, body.project_id)
    async with transaction(request, auth) as conn:
        role = (await conn.execute(select(Role.id, Role.scope, Role.key).where(Role.id == body.role_id))).one_or_none()
        if role is None:
            raise not_found("role")
        if (role.scope == "project") != (body.project_id is not None):
            raise ProblemError(422, "scope_mismatch", "Project roles need a project; tenant roles must not have one.")
        if (
            body.project_id is not None
            and (await conn.execute(select(Project.id).where(Project.id == body.project_id))).first() is None
        ):
            raise not_found("project")
        if (await conn.execute(select(Membership.id).where(Membership.user_id == body.user_id))).first() is None:
            raise not_found("user")
        try:
            async with authz_change(conn, auth.tenant_id):
                assignment_id = (
                    await conn.execute(
                        insert(RoleAssignment)
                        .values(
                            tenant_id=auth.tenant_id,
                            user_id=body.user_id,
                            role_id=role.id,
                            scope=role.scope,
                            project_id=body.project_id,
                            created_by=auth.user_id,
                        )
                        .returning(RoleAssignment.id)
                    )
                ).scalar_one()
        except IntegrityError as exc:
            raise ProblemError(409, "already_assigned", "The user already has that role there.") from exc
        await audit(
            conn,
            auth,
            "role.assign",
            f"user:{body.user_id}",
            {"role": role.key, "project_id": str(body.project_id) if body.project_id else None},
        )
        return await _load(conn, assignment_id)


@router.delete("/{assignment_id}", status_code=204)
async def unassign(request: Request, assignment_id: uuid.UUID, auth: TenantMember) -> None:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        assignment = await _load(conn, assignment_id)
    await _authorize(request, auth, assignment.project_id)
    async with transaction(request, auth) as conn:
        async with authz_change(conn, auth.tenant_id):
            result = await conn.execute(delete(RoleAssignment).where(RoleAssignment.id == assignment_id))
        if result.rowcount == 0:
            raise not_found("role_assignment")
        await audit(
            conn,
            auth,
            "role.unassign",
            f"user:{assignment.user_id}",
            {"role": assignment.role_key, "project_id": str(assignment.project_id) if assignment.project_id else None},
        )
