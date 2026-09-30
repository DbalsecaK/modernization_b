"""Projects (spec 18.3): list, the composition proposal of the wizard, creation with its whole setup, detail, edit
and versioned configuration. The composition is decided by the deterministic engine on the server (9.4, 9.7)."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, deny, require_project, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.catalog_store import load_catalog
from nexti_api.errors import ProblemError
from nexti_api.projects.configs import ConfigInput, check, write_config
from nexti_api.projects.model_check import check_models
from nexti_api.schemas import ApiModel
from nexti_core.ai_catalog import AGENT_ROLES
from nexti_core.composition import Request as CompositionRequest
from nexti_core.composition import Target, evaluate
from nexti_core.db.models import (
    AppUser,
    AuthzOutbox,
    Budget,
    Membership,
    ModelAssignment,
    ModelProfile,
    Project,
    ProjectAgent,
    ProjectConfig,
    ProjectSkill,
    Role,
    RoleAssignment,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
CreateProjects = Annotated[Authorized, Depends(require_tenant("project.create"))]
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
ConfigureProject = Annotated[Authorized, Depends(require_project("project.configure"))]
Flow = Literal["modernization", "newFeature"]
Autonomy = Literal["guided", "balanced", "autonomous"]
Key = Annotated[str, Field(min_length=1, max_length=64)]
# Project permissions the screens use to show or hide actions (the API checks them anyway).
PROJECT_PERMISSIONS = (
    "project.configure", "input.upload", "agents.select", "skills.select", "code.download",
    # Runs (M3): launch, answer questions, decide gates.
    "pipeline.run", "question.answer", "gate.c1.approve", "gate.c2.approve", "gate.c3.approve", "signoff.sign",
    # Spec (M4): edit stories and the plan; see the code (traceability, proof packs).
    "story.edit", "plan.edit", "code.view",
    # UI design (M5): comment on prototypes, ask for changes and edit screen specs.
    "prototype.comment", "prototype.edit",
)  # fmt: skip


class TargetIn(ApiModel):
    architecture: Key
    backend: Key
    frontend: Key
    database: Key
    cloud: Key

    def to_target(self) -> Target:
        return Target(self.architecture, self.backend, self.frontend, self.database, self.cloud)


class ComposeIn(ApiModel):
    flow: Flow
    sources: list[Key] = Field(max_length=20)
    target: TargetIn
    agents: list[Key] | None = Field(default=None, max_length=40)
    skills: list[Key] | None = Field(default=None, max_length=100)
    project_id: uuid.UUID | None = None  # an existing project: its model assignments count too


class RecommendationOut(ApiModel):
    agent: str
    reason: str


class ProblemOut(ApiModel):
    code: str
    subject: str | None


class MissingSkillOut(ApiModel):
    source: str
    skill: str


class ModelCheckOut(ApiModel):
    agent: str
    profile_id: uuid.UUID | None
    profile_name: str | None
    missing: list[str]


class CompositionOut(ApiModel):
    recommended_agents: list[RecommendationOut]
    agents: list[str]
    recommended_skills: list[str]
    skills: list[str]
    warnings: list[str]
    missing_skills: list[MissingSkillOut]
    conflicts: list[list[str]]
    uncovered_phases: list[str]
    problems: list[ProblemOut]
    estimate_usd: int
    models: list[ModelCheckOut]


class TeamMemberIn(ApiModel):
    user_id: uuid.UUID
    role_key: Key


class ModelChoiceIn(ApiModel):
    agent_role: Key
    profile_id: uuid.UUID


class ConfigIn(ApiModel):
    sources: list[Key] = Field(min_length=1, max_length=20)
    target: TargetIn
    agents: list[Key] | None = Field(default=None, max_length=40)
    skills: list[Key] | None = Field(default=None, max_length=100)
    pipeline_template: Key
    autonomy: Autonomy = "balanced"
    max_iterations: int = Field(default=3, ge=1, le=10)
    sampling_pct: int = Field(default=10, ge=0, le=100)
    change_note: str | None = Field(default=None, max_length=500)

    def to_input(self) -> ConfigInput:
        return ConfigInput(
            sources=tuple(self.sources), target=self.target.to_target(), pipeline_template=self.pipeline_template,
            autonomy=self.autonomy, max_iterations=self.max_iterations, sampling_pct=self.sampling_pct,
            agents=self.agents, skills=self.skills, change_note=self.change_note,
        )  # fmt: skip


class ProjectCreate(ConfigIn):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    flow: Flow
    artifact_language: Literal["en", "es"] = "en"
    budget_usd: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    team: list[TeamMemberIn] = Field(default_factory=list, max_length=50)
    model_choices: list[ModelChoiceIn] = Field(default_factory=list, max_length=40)


class ProjectUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    artifact_language: Literal["en", "es"] | None = None
    status: Literal["active", "archived"] | None = None


class TargetOut(ApiModel):
    architecture: str
    backend: str
    frontend: str
    database: str
    cloud: str


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    status: Literal["active", "archived"]
    flow: Flow
    artifact_language: Literal["en", "es"]
    description: str
    sources: list[str]
    target: TargetOut | None
    config_version: int | None
    created_at: datetime
    updated_at: datetime


class ConfigOut(ApiModel):
    version: int
    sources: list[str]
    target: TargetOut
    pipeline_template: str
    autonomy: Autonomy
    max_iterations: int
    sampling_pct: int
    warnings: list[str]
    change_note: str | None
    created_at: datetime
    created_by: uuid.UUID | None


class ProjectAgentOut(ApiModel):
    key: str
    version: str
    reason: str | None


class ProjectSkillOut(ApiModel):
    key: str
    version: str
    recommended: bool


class TeamMemberOut(ApiModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role_key: str
    role_name: str


class ProjectDetail(ProjectOut):
    config: ConfigOut | None
    agents: list[ProjectAgentOut]
    skills: list[ProjectSkillOut]
    team: list[TeamMemberOut]
    budget_usd: Decimal | None
    permissions: list[str]


class ConfigVersionOut(ApiModel):
    version: int
    change_note: str | None
    warnings: list[str]
    agents: int
    skills: int
    created_at: datetime
    created_by: uuid.UUID | None


def _composition(evaluation: Any, models: list[Any]) -> CompositionOut:
    return CompositionOut(
        recommended_agents=[RecommendationOut(agent=r.agent, reason=r.reason) for r in evaluation.recommended_agents],
        agents=list(evaluation.agents),
        recommended_skills=list(evaluation.recommended_skills),
        skills=list(evaluation.skills),
        warnings=list(evaluation.warnings),
        missing_skills=[MissingSkillOut(source=m.source, skill=m.skill) for m in evaluation.missing_skills],
        conflicts=[list(c) for c in evaluation.conflicts],
        uncovered_phases=list(evaluation.uncovered_phases),
        problems=[ProblemOut(code=p.code, subject=p.subject) for p in evaluation.problems],
        estimate_usd=evaluation.estimate_usd,
        models=[
            ModelCheckOut(agent=m.agent, profile_id=m.profile_id, profile_name=m.profile_name, missing=list(m.missing))
            for m in models
        ],
    )


def _current_config() -> Any:
    latest = (
        select(ProjectConfig.project_id, func.max(ProjectConfig.version).label("version"))
        .group_by(ProjectConfig.project_id)
        .subquery()
    )
    return latest


async def _project_row(conn: AsyncConnection, project_id: uuid.UUID) -> Any:
    row = (await conn.execute(select(Project).where(Project.id == project_id))).first()
    if row is None:
        raise not_found("project")
    return row


async def _config(conn: AsyncConnection, project_id: uuid.UUID) -> Any:
    return (
        await conn.execute(
            select(ProjectConfig)
            .where(ProjectConfig.project_id == project_id)
            .order_by(ProjectConfig.version.desc())
            .limit(1)
        )
    ).first()


def _project_out(p: Any, config: Any) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "status": p.status, "flow": p.flow, "artifact_language": p.artifact_language,
        "description": p.description, "sources": list(config.sources) if config else [],
        "target": TargetOut(**config.target) if config else None, "config_version": config.version if config else None,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }  # fmt: skip


async def _publish_tuples(request: Request, conn_scope: Authorized) -> None:
    """Publish this tenant's pending OpenFGA tuples before answering, so the creator can open the project at once.
    Bounded wait: the background relay publishes anything left."""
    relay = getattr(request.app.state, "relay", None)
    if relay is None:
        return
    async with transaction(request, conn_scope) as conn:
        last = (await conn.execute(select(func.max(AuthzOutbox.id)))).scalar()
    if last is None:
        return
    for _ in range(30):
        await relay.run_once()
        async with transaction(request, conn_scope) as conn:
            pending = (
                await conn.execute(select(func.count()).where(AuthzOutbox.status == "pending", AuthzOutbox.id <= last))
            ).scalar_one()
        if not pending:
            return
        await asyncio.sleep(0.1)


@router.get("", response_model=list[ProjectOut])
async def list_projects(request: Request, auth: TenantMember) -> list[ProjectOut]:
    """OpenFGA answers which projects the user may see (ListObjects); RLS keeps it to the active tenant."""
    visible = await request.app.state.fga.list_objects(names.user(auth.user_id), "viewer", "project")
    ids = [uuid.UUID(obj.split(":", 1)[1]) for obj in visible]
    if not ids:
        return []
    latest = _current_config()
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                select(Project, ProjectConfig.sources, ProjectConfig.target, ProjectConfig.version)
                .outerjoin(latest, latest.c.project_id == Project.id)
                .outerjoin(
                    ProjectConfig,
                    (ProjectConfig.project_id == Project.id) & (ProjectConfig.version == latest.c.version),
                )
                .where(Project.id.in_(ids))
                .order_by(Project.name)
            )
        ).all()
    return [ProjectOut.model_validate(_project_out(r, r if r.version is not None else None)) for r in rows]


@router.post(":compose", response_model=CompositionOut)
async def compose(request: Request, body: ComposeIn, auth: TenantMember) -> CompositionOut:
    """The recommended team and skills for a choice, with the problems that would block it (nothing is saved)."""
    request_ = CompositionRequest(body.flow, tuple(body.sources), body.target.to_target())
    async with transaction(request, auth) as conn:
        catalog = await load_catalog(conn)
        evaluation = evaluate(catalog, request_, body.agents, body.skills)
        models = await check_models(conn, catalog, evaluation.agents, body.project_id)
    return _composition(evaluation, models)


async def _team_rows(
    conn: AsyncConnection, auth: Authorized, project_id: uuid.UUID, team: list[TeamMemberIn]
) -> list[dict[str, Any]]:
    roles = {r.key: r.id for r in (await conn.execute(select(Role.id, Role.key).where(Role.scope == "project"))).all()}
    members = set((await conn.execute(select(Membership.user_id).where(Membership.status == "active"))).scalars())
    wanted: list[tuple[uuid.UUID, str]] = []
    if auth.user_id in members:
        wanted.append((auth.user_id, "projectOwner"))  # the creator owns the project (18.3 step 8)
    for m in team:
        if m.role_key not in roles:
            raise ProblemError(422, "unknown_project_role", f"Unknown project role: {m.role_key}.")
        if m.user_id not in members:
            raise not_found("user")
        wanted.append((m.user_id, m.role_key))
    return [
        {"tenant_id": auth.tenant_id, "user_id": user, "role_id": roles[key], "scope": "project",
         "project_id": project_id, "created_by": auth.user_id}
        for user, key in dict.fromkeys(wanted)
        if key in roles
    ]  # fmt: skip


@router.post("", response_model=ProjectDetail, status_code=201)
async def create_project(request: Request, body: ProjectCreate, auth: CreateProjects) -> ProjectDetail:
    assert auth.tenant_id is not None  # noqa: S101
    # Choosing models per agent is configuring models (12.4): it needs that permission too.
    if body.model_choices and not await request.app.state.fga.check(
        names.user(auth.user_id), "models_configure", names.tenant(auth.tenant_id)
    ):
        await deny(request, auth.session, auth.tenant_id, "models.configure", names.tenant(auth.tenant_id))
    config = body.to_input()
    try:
        async with transaction(request, auth) as conn:
            catalog = await load_catalog(conn)
            check(catalog, body.flow, config)  # 422 before anything is written
            for choice in body.model_choices:
                if choice.agent_role not in AGENT_ROLES:
                    raise ProblemError(422, "unknown_agent_role", f"Unknown agent role: {choice.agent_role}.")
                found = select(ModelProfile.id).where(ModelProfile.id == choice.profile_id)
                if (await conn.execute(found)).first() is None:
                    raise not_found("profile")
            async with authz_change(conn, auth.tenant_id):
                project_id: uuid.UUID = (
                    await conn.execute(
                        insert(Project)
                        .values(
                            tenant_id=auth.tenant_id, name=body.name, description=body.description, flow=body.flow,
                            artifact_language=body.artifact_language, created_by=auth.user_id,
                        )
                        .returning(Project.id)
                    )
                ).scalar_one()  # fmt: skip
                team = await _team_rows(conn, auth, project_id, body.team)
                if team:
                    await conn.execute(insert(RoleAssignment), team)
            version, evaluation = await write_config(
                conn, catalog, tenant_id=auth.tenant_id, project_id=project_id, flow=body.flow, config=config,
                by=auth.user_id,
            )  # fmt: skip
            if body.budget_usd is not None:
                await conn.execute(
                    insert(Budget).values(
                        tenant_id=auth.tenant_id, project_id=project_id, period="total", amount_usd=body.budget_usd,
                        created_by=auth.user_id,
                    )
                )  # fmt: skip
            for choice in body.model_choices:
                await conn.execute(
                    insert(ModelAssignment).values(
                        tenant_id=auth.tenant_id, project_id=project_id, agent_role=choice.agent_role,
                        profile_id=choice.profile_id, updated_by=auth.user_id,
                    )
                )  # fmt: skip
            await audit(
                conn, auth, "project.create", f"project:{project_id}",
                {"name": body.name, "flow": body.flow, "config_version": version, "agents": list(evaluation.agents),
                 "skills": list(evaluation.skills), "team": len(team), "budget_usd": str(body.budget_usd or "")},
            )  # fmt: skip
    except IntegrityError as exc:
        raise ProblemError(409, "project_name_taken", "A project with that name already exists.") from exc
    await _publish_tuples(request, auth)
    return await _detail(request, auth, project_id)


async def _detail(request: Request, auth: Authorized, project_id: uuid.UUID) -> ProjectDetail:
    async with transaction(request, auth) as conn:
        p = await _project_row(conn, project_id)
        config = await _config(conn, project_id)
        agents: Sequence[Any] = []
        skills: Sequence[Any] = []
        if config is not None:
            agents = (
                await conn.execute(
                    select(ProjectAgent).where(
                        ProjectAgent.project_id == project_id, ProjectAgent.config_version == config.version
                    )
                )
            ).all()
            skills = (
                await conn.execute(
                    select(ProjectSkill).where(
                        ProjectSkill.project_id == project_id, ProjectSkill.config_version == config.version
                    )
                )
            ).all()
        team = (
            await conn.execute(
                select(RoleAssignment.user_id, AppUser.display_name, AppUser.email, Role.key, Role.name)
                .join(Role, Role.id == RoleAssignment.role_id)
                .join(AppUser, AppUser.id == RoleAssignment.user_id)
                .where(RoleAssignment.project_id == project_id)
                .order_by(AppUser.display_name)
            )
        ).all()
        budget = (
            await conn.execute(
                select(Budget.amount_usd).where(Budget.project_id == project_id, Budget.period == "total")
            )
        ).scalar()
    allowed = await request.app.state.fga.batch_check(
        names.user(auth.user_id), names.project(project_id), [names.relation(k) for k in PROJECT_PERMISSIONS]
    )
    order = {a.key: a.order for a in (await _catalog_order(request, auth))}
    return ProjectDetail(
        **_project_out(p, config),
        config=ConfigOut(
            version=config.version, sources=list(config.sources), target=TargetOut(**config.target),
            pipeline_template=config.pipeline_template, autonomy=config.autonomy,
            max_iterations=config.max_iterations, sampling_pct=config.sampling_pct, warnings=list(config.warnings),
            change_note=config.change_note, created_at=config.created_at, created_by=config.created_by,
        ) if config else None,
        agents=[
            ProjectAgentOut(key=a.agent_key, version=a.agent_version, reason=a.reason)
            for a in sorted(agents, key=lambda a: order.get(a.agent_key, 999))
        ],
        skills=[ProjectSkillOut(key=s.skill_key, version=s.skill_version, recommended=s.recommended) for s in skills],
        team=[
            TeamMemberOut(user_id=t.user_id, display_name=t.display_name, email=t.email, role_key=t.key,
                          role_name=t.name)
            for t in team
        ],
        budget_usd=budget,
        permissions=[k for k in PROJECT_PERMISSIONS if allowed.get(names.relation(k))],
    )  # fmt: skip


async def _catalog_order(request: Request, auth: Authorized) -> Any:
    async with transaction(request, auth) as conn:
        return (await load_catalog(conn)).agents


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(request: Request, project_id: uuid.UUID, auth: ViewProject) -> ProjectDetail:
    return await _detail(request, auth, project_id)


@router.patch("/{project_id}", response_model=ProjectDetail)
async def update_project(
    request: Request, project_id: uuid.UUID, body: ProjectUpdate, auth: ConfigureProject
) -> ProjectDetail:
    changes = body.model_dump(exclude_none=True, by_alias=False)
    try:
        async with transaction(request, auth) as conn:
            await _project_row(conn, project_id)
            if changes:
                await conn.execute(update(Project).where(Project.id == project_id).values(**changes))
                await audit(conn, auth, "project.update", f"project:{project_id}", changes)
    except IntegrityError as exc:
        raise ProblemError(409, "project_name_taken", "A project with that name already exists.") from exc
    return await _detail(request, auth, project_id)


@router.put("/{project_id}/config", response_model=ProjectDetail)
async def change_config(
    request: Request, project_id: uuid.UUID, body: ConfigIn, auth: ConfigureProject
) -> ProjectDetail:
    """A new configuration version. Changing the team needs agents.select; changing skills needs skills.select."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        project = await _project_row(conn, project_id)
        current = await _config(conn, project_id)
        catalog = await load_catalog(conn)
        evaluation = check(catalog, project.flow, body.to_input())
        before_agents: set[str] = set()
        before_skills: set[str] = set()
        if current is not None:
            before_agents = set(
                (
                    await conn.execute(
                        select(ProjectAgent.agent_key).where(
                            ProjectAgent.project_id == project_id, ProjectAgent.config_version == current.version
                        )
                    )
                ).scalars()
            )
            before_skills = set(
                (
                    await conn.execute(
                        select(ProjectSkill.skill_key).where(
                            ProjectSkill.project_id == project_id, ProjectSkill.config_version == current.version
                        )
                    )
                ).scalars()
            )
    user, obj = names.user(auth.user_id), names.project(project_id)
    agents_changed = set(evaluation.agents) != before_agents
    skills_changed = set(evaluation.skills) != before_skills
    if agents_changed and not await request.app.state.fga.check(user, "agents_select", obj):
        await deny(request, auth.session, auth.tenant_id, "agents.select", obj)
    if skills_changed and not await request.app.state.fga.check(user, "skills_select", obj):
        await deny(request, auth.session, auth.tenant_id, "skills.select", obj)
    async with transaction(request, auth) as conn:
        version, evaluation = await write_config(
            conn, catalog, tenant_id=auth.tenant_id, project_id=project_id, flow=project.flow, config=body.to_input(),
            by=auth.user_id,
        )  # fmt: skip
        await audit(
            conn, auth, "project.config_change", f"project:{project_id}",
            {"version": version, "agents_changed": agents_changed, "skills_changed": skills_changed,
             "agents": list(evaluation.agents), "skills": list(evaluation.skills), "note": body.change_note},
        )  # fmt: skip
    return await _detail(request, auth, project_id)


@router.get("/{project_id}/config/versions", response_model=list[ConfigVersionOut])
async def config_versions(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[ConfigVersionOut]:
    agents = (
        select(func.count())
        .where(
            ProjectAgent.project_id == ProjectConfig.project_id, ProjectAgent.config_version == ProjectConfig.version
        )
        .scalar_subquery()
    )
    skills = (
        select(func.count())
        .where(
            ProjectSkill.project_id == ProjectConfig.project_id, ProjectSkill.config_version == ProjectConfig.version
        )
        .scalar_subquery()
    )
    async with transaction(request, auth) as conn:
        await _project_row(conn, project_id)
        rows = (
            await conn.execute(
                select(
                    ProjectConfig.version, ProjectConfig.change_note, ProjectConfig.warnings,
                    agents.label("agents"), skills.label("skills"), ProjectConfig.created_at, ProjectConfig.created_by,
                )
                .where(ProjectConfig.project_id == project_id)
                .order_by(ProjectConfig.version.desc())
            )
        ).all()  # fmt: skip
    return [ConfigVersionOut.model_validate(r, from_attributes=True) for r in rows]
