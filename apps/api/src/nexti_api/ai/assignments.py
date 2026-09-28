"""Model assignment matrix (spec 12.4, 12.5) and tenant policy (12.6)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.ai.catalog import tenant_policy
from nexti_api.ai.common import ConfigureModels
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.ai_catalog import AGENT_ROLES, PHASES
from nexti_core.db.models import ModelAssignment, ModelPolicy, ModelProfile, Project
from nexti_model_gateway.rules import AssignmentRow, resolve_profile

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class AssignmentOptions(ApiModel):
    phases: list[str]
    agent_roles: list[str]


class ModelAssignmentOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    phase: str | None
    agent_role: str | None
    profile_id: uuid.UUID


class ModelAssignmentIn(ApiModel):
    project_id: uuid.UUID | None = None
    phase: str | None = None
    agent_role: str | None = None
    # null removes the assignment at that level (the cascade falls back to the next one).
    profile_id: uuid.UUID | None


class ResolvedOut(ApiModel):
    profile_id: uuid.UUID | None


class PolicyOut(ApiModel):
    openrouter_allowed: bool
    allowed_upstream_providers: list[str] | None
    denied_upstream_providers: list[str]
    require_zdr: bool
    deny_data_collection: bool


class PolicyIn(ApiModel):
    openrouter_allowed: bool = True
    allowed_upstream_providers: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = None
    denied_upstream_providers: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list)
    require_zdr: bool = False
    deny_data_collection: bool = True


@router.get("/assignment-options", response_model=AssignmentOptions)
async def options(auth: ConfigureModels) -> AssignmentOptions:
    return AssignmentOptions(phases=list(PHASES), agent_roles=list(AGENT_ROLES))


@router.get("/assignments", response_model=list[ModelAssignmentOut])
async def list_assignments(
    request: Request,
    auth: ConfigureModels,
    project_id: Annotated[uuid.UUID | None, Query(alias="projectId")] = None,
) -> list[ModelAssignmentOut]:
    """Tenant-wide rows, plus the rows of `projectId` when given."""
    query = select(ModelAssignment)
    query = (
        query.where(ModelAssignment.project_id.is_(None) | (ModelAssignment.project_id == project_id))
        if project_id
        else query.where(ModelAssignment.project_id.is_(None))
    )
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(query)).all()
    return [
        ModelAssignmentOut(
            id=r.id, project_id=r.project_id, phase=r.phase, agent_role=r.agent_role, profile_id=r.profile_id
        )
        for r in rows
    ]


@router.put("/assignments", response_model=list[ModelAssignmentOut])
async def set_assignment(request: Request, body: ModelAssignmentIn, auth: ConfigureModels) -> list[ModelAssignmentOut]:
    if body.phase is not None and body.phase not in PHASES:
        raise ProblemError(422, "unknown_phase", f"Unknown phase: {body.phase}.")
    if body.agent_role is not None and body.agent_role not in AGENT_ROLES:
        raise ProblemError(422, "unknown_agent_role", f"Unknown agent role: {body.agent_role}.")
    # The row of exactly this level (NULL means "any" for that axis).
    level = (
        ModelAssignment.project_id.is_not_distinct_from(body.project_id),
        ModelAssignment.phase.is_not_distinct_from(body.phase),
        ModelAssignment.agent_role.is_not_distinct_from(body.agent_role),
    )
    async with transaction(request, auth) as conn:
        if (
            body.project_id is not None
            and (await conn.execute(select(Project.id).where(Project.id == body.project_id))).first() is None
        ):
            raise not_found("project")
        if body.profile_id is None:
            await conn.execute(delete(ModelAssignment).where(*level))
        else:
            if (await conn.execute(select(ModelProfile.id).where(ModelProfile.id == body.profile_id))).first() is None:
                raise not_found("profile")
            await conn.execute(
                pg_insert(ModelAssignment)
                .values(
                    tenant_id=auth.tenant_id,
                    project_id=body.project_id,
                    phase=body.phase,
                    agent_role=body.agent_role,
                    profile_id=body.profile_id,
                    updated_by=auth.user_id,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "project_id", "phase", "agent_role"],
                    set_={"profile_id": body.profile_id, "updated_by": auth.user_id},
                )
            )
        await audit(conn, auth, "ai.assignment_set", "assignments", body.model_dump(mode="json"))
    return await list_assignments(request, auth, body.project_id)


@router.get("/assignments:resolve", response_model=ResolvedOut)
async def resolve(
    request: Request,
    auth: ConfigureModels,
    project_id: Annotated[uuid.UUID | None, Query(alias="projectId")] = None,
    phase: str | None = None,
    agent_role: Annotated[str | None, Query(alias="agentRole")] = None,
) -> ResolvedOut:
    """Which profile the gateway would use for this context (the same cascade as the gateway)."""
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(select(ModelAssignment))).all()
    chosen = resolve_profile(
        [AssignmentRow(r.project_id, r.phase, r.agent_role, r.profile_id) for r in rows], project_id, phase, agent_role
    )
    return ResolvedOut(profile_id=chosen)


@router.get("/policy", response_model=PolicyOut)
async def get_policy(request: Request, auth: ConfigureModels) -> PolicyOut:
    async with transaction(request, auth) as conn:
        policy = await tenant_policy(conn)
    return PolicyOut(
        openrouter_allowed=policy.openrouter_allowed,
        allowed_upstream_providers=list(policy.allowed_upstream_providers)
        if policy.allowed_upstream_providers is not None
        else None,
        denied_upstream_providers=list(policy.denied_upstream_providers),
        require_zdr=policy.require_zdr,
        deny_data_collection=policy.deny_data_collection,
    )


@router.put("/policy", response_model=PolicyOut)
async def set_policy(request: Request, body: PolicyIn, auth: ConfigureModels) -> PolicyOut:
    values = {**body.model_dump(by_alias=False), "updated_by": auth.user_id}
    async with transaction(request, auth) as conn:
        await conn.execute(
            pg_insert(ModelPolicy)
            .values(tenant_id=auth.tenant_id, **values)
            .on_conflict_do_update(index_elements=["tenant_id"], set_=values)
        )
        await audit(conn, auth, "ai.policy_update", "policy", body.model_dump(mode="json"))
    return await get_policy(request, auth)
