"""The backlog of a project in Jira or Azure DevOps (spec 7.6, ADR-0019): the link to one integration of the tenant and
its external project, the type mapping and the automation rules; the items the platform keeps in sync and the
corrections the developer agent proposed for bugs. The sync itself runs in the worker (a queued job): the API only
links, shows and asks for a sync."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.db.models import Project, ProjectBacklog, TenantIntegration
from nexti_core.jobs import defer_backlog_sync

router = APIRouter(prefix="/api/v1/projects/{project_id}/backlog", tags=["backlog"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
ConfigureProject = Annotated[Authorized, Depends(require_project("project.configure"))]
TRACKERS = ("jira", "azure_devops")
RULES = ("createFromSpec", "markDone", "bugOnFailure", "autoFix")
DEFAULT_RULES = dict.fromkeys(RULES, True)


class Rules(ApiModel):
    create_from_spec: bool = True
    mark_done: bool = True
    bug_on_failure: bool = True
    auto_fix: bool = True


class BacklogIn(ApiModel):
    integration_id: uuid.UUID
    external_project: str = Field(min_length=1, max_length=200)
    rules: Rules = Field(default_factory=Rules)
    types: dict[str, str] = Field(default_factory=dict, max_length=4)
    states: dict[str, str] = Field(default_factory=dict, max_length=4)


class ConnectionOption(ApiModel):
    id: uuid.UUID
    kind: Literal["jira", "azure_devops"]
    name: str
    status: Literal["untested", "ok", "failed"]


class BacklogLinkOut(ApiModel):
    integration_id: uuid.UUID
    integration_name: str
    kind: Literal["jira", "azure_devops"]
    external_project: str
    rules: Rules
    types: dict[str, str]
    states: dict[str, str]
    last_synced_at: datetime | None
    last_sync_detail: str | None


class WorkItemOut(ApiModel):
    element: str
    kind: Literal["feature", "story", "task", "bug"]
    title: str
    external_key: str
    url: str
    state: Literal["open", "review", "done", "discarded"]
    updated_at: datetime


class BugFixOut(ApiModel):
    element: str
    iteration: int
    status: Literal["proposed", "failed", "escalated"]
    detail: str
    created_at: datetime


class BacklogOut(ApiModel):
    link: BacklogLinkOut | None
    items: list[WorkItemOut]
    fixes: list[BugFixOut]
    connections: list[ConnectionOption]


def _rules(raw: dict[str, Any]) -> Rules:
    merged = {**DEFAULT_RULES, **{k: bool(v) for k, v in raw.items() if k in RULES}}
    return Rules(create_from_spec=merged["createFromSpec"], mark_done=merged["markDone"],
                 bug_on_failure=merged["bugOnFailure"], auto_fix=merged["autoFix"])  # fmt: skip


async def _project(conn: Any, project_id: uuid.UUID) -> None:
    if (await conn.execute(select(Project.id).where(Project.id == project_id))).first() is None:
        raise not_found("project")


@router.get("", response_model=BacklogOut)
async def get_backlog(request: Request, project_id: uuid.UUID, auth: ViewProject) -> BacklogOut:
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
        link = (
            await conn.execute(
                text("SELECT b.*, i.name AS integration_name, i.kind FROM project_backlog b JOIN tenant_integration i "
                     "ON i.id = b.integration_id WHERE b.project_id = :p"), {"p": project_id})
        ).mappings().first()  # fmt: skip
        items = (
            await conn.execute(
                text("SELECT element, kind, title, external_key, url, state, updated_at FROM work_item_link "
                     "WHERE project_id = :p ORDER BY array_position(ARRAY['feature','story','task','bug'], kind), "
                     "element"), {"p": project_id})
        ).mappings().all()  # fmt: skip
        fixes = (
            await conn.execute(
                text("SELECT element, iteration, status, detail, created_at FROM bug_fix WHERE project_id = :p "
                     "ORDER BY created_at DESC"), {"p": project_id})
        ).mappings().all()  # fmt: skip
        options = (
            await conn.execute(
                select(TenantIntegration.id, TenantIntegration.kind, TenantIntegration.name, TenantIntegration.status)
                .where(TenantIntegration.kind.in_(TRACKERS)).order_by(TenantIntegration.name))
        ).mappings().all()  # fmt: skip
    return BacklogOut(
        link=BacklogLinkOut(
            integration_id=link["integration_id"], integration_name=link["integration_name"], kind=link["kind"],
            external_project=link["external_project"], rules=_rules(link["rules"]), types=link["types"],
            states=link["states"], last_synced_at=link["last_synced_at"], last_sync_detail=link["last_sync_detail"],
        ) if link else None,
        items=[WorkItemOut.model_validate(dict(i)) for i in items],
        fixes=[BugFixOut.model_validate(dict(f)) for f in fixes],
        connections=[ConnectionOption.model_validate(dict(o)) for o in options],
    )  # fmt: skip


@router.put("", response_model=BacklogOut)
async def set_backlog(request: Request, project_id: uuid.UUID, body: BacklogIn, auth: ConfigureProject) -> BacklogOut:
    assert auth.tenant_id is not None  # noqa: S101
    rules = {"createFromSpec": body.rules.create_from_spec, "markDone": body.rules.mark_done,
             "bugOnFailure": body.rules.bug_on_failure, "autoFix": body.rules.auto_fix}  # fmt: skip
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
        kind = (
            await conn.execute(select(TenantIntegration.kind).where(TenantIntegration.id == body.integration_id))
        ).scalar_one_or_none()
        if kind is None:
            raise not_found("integration")  # another tenant's integration is not visible (RLS)
        if kind not in TRACKERS:
            raise ProblemError(422, "integration_not_a_backlog", "Link a Jira or Azure DevOps integration.")
        values = {"integration_id": body.integration_id, "external_project": body.external_project.strip(),
                  "rules": rules, "types": body.types, "states": body.states}  # fmt: skip
        await conn.execute(
            pg_insert(ProjectBacklog)
            .values(tenant_id=auth.tenant_id, project_id=project_id, created_by=auth.user_id, **values)
            .on_conflict_do_update(index_elements=["project_id"], set_={**values, "updated_at": text("now()")})
        )
        await audit(conn, auth, "backlog.link", f"project:{project_id}",
                    {"integration_id": str(body.integration_id), "kind": kind,
                     "external_project": body.external_project.strip(), "rules": rules})  # fmt: skip
    return await get_backlog(request, project_id, auth)


@router.delete("", status_code=204)
async def delete_backlog(request: Request, project_id: uuid.UUID, auth: ConfigureProject) -> None:
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
        found = await conn.execute(delete(ProjectBacklog).where(ProjectBacklog.project_id == project_id))
        if found.rowcount == 0:
            raise not_found("backlog")
        await audit(conn, auth, "backlog.unlink", f"project:{project_id}")


class SyncOut(ApiModel):
    queued: bool


@router.post(":sync", response_model=SyncOut, status_code=202)
async def sync_backlog(request: Request, project_id: uuid.UUID, auth: ConfigureProject) -> SyncOut:
    """Ask the worker to sync now (approved stories, verified items, bugs). Every external write it makes is audited."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
        linked = (
            await conn.execute(select(ProjectBacklog.project_id).where(ProjectBacklog.project_id == project_id))
        ).first()
        if linked is None:
            raise ProblemError(409, "backlog_not_linked", "Link the project to Jira or Azure DevOps first.")
        queued = await defer_backlog_sync(conn, project_id, auth.tenant_id, "manual")
        await audit(conn, auth, "backlog.sync_requested", f"project:{project_id}", {"queued": queued})
    return SyncOut(queued=queued)
