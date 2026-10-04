"""Runs of a project and their gates (spec 10.4, 11.1, 16.3). Launching a run creates it and enqueues the worker in
the same transaction; deciding a gate records the decision and enqueues the worker to resume. The person who
launched a run cannot approve its gates (segregation of duties)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import RowMapping, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api import license_gate
from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, require_gate, require_project
from nexti_api.errors import ProblemError
from nexti_api.runs.schemas import (
    ACTIVE,
    FINAL,
    GateDecisionIn,
    GateOut,
    InvocationOut,
    PhaseRunOut,
    QuestionOut,
    RunDetail,
    RunIn,
    RunOut,
)
from nexti_api.spec import common as spec_common
from nexti_core.db.models import AgentInvocation, AppUser, Gate, PhaseRun, Project, ProjectConfig, Question, Run
from nexti_core.jobs import defer_backlog_sync, defer_run

router = APIRouter(prefix="/api/v1/projects/{project_id}/runs", tags=["runs"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
RunPipeline = Annotated[Authorized, Depends(require_project("pipeline.run"))]
DecideGate = Annotated[Authorized, Depends(require_gate())]
MAX_LISTED = 50


def run_query() -> Any:
    return select(Run, AppUser.display_name.label("started_by_name")).outerjoin(AppUser, AppUser.id == Run.started_by)


async def load_run(
    conn: AsyncConnection, project_id: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False
) -> RowMapping:
    query = run_query().where(Run.id == run_id, Run.project_id == project_id)
    row = (await conn.execute(query.with_for_update(of=Run) if lock else query)).mappings().one_or_none()
    if row is None:
        raise not_found("run")
    return row


async def cost_visible(request: Request, auth: Authorized) -> bool:
    if auth.tenant_id is None:
        return False
    return bool(await request.app.state.fga.check(names.user(auth.user_id), "cost_view", names.tenant(auth.tenant_id)))


def question_query() -> Any:
    return select(Question, AppUser.display_name.label("answered_by_name")).outerjoin(
        AppUser, AppUser.id == Question.answered_by
    )


def gate_query() -> Any:
    return select(Gate, AppUser.display_name.label("decided_by_name")).outerjoin(AppUser, AppUser.id == Gate.decided_by)


@router.get("", response_model=list[RunOut])
async def list_runs(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[RunOut]:
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                run_query().where(Run.project_id == project_id).order_by(Run.created_at.desc()).limit(MAX_LISTED)
            )
        ).mappings()
        return [RunOut.model_validate(dict(r)) for r in rows]


@router.post("", response_model=RunOut, status_code=201)
async def start_run(request: Request, project_id: uuid.UUID, body: RunIn, auth: RunPipeline) -> RunOut:
    """Launch the pipeline with the project's current configuration. The demo pipeline exists only in development
    and test (plan M3 decision 3)."""
    if body.kind == "demo" and not request.app.state.settings.is_local:
        raise ProblemError(422, "demo_not_available", "The demonstration pipeline is only available in development.")
    assert auth.tenant_id is not None  # noqa: S101 - require_project guarantees it
    await license_gate.ensure_writable(request, auth, "run.start", f"project:{project_id}")
    async with transaction(request, auth) as conn:
        project = (
            await conn.execute(select(Project.id).where(Project.id == project_id).with_for_update())
        ).one_or_none()
        if project is None:
            raise not_found("project")
        config = (
            (
                await conn.execute(
                    select(ProjectConfig.version, ProjectConfig.autonomy, ProjectConfig.max_iterations)
                    .where(ProjectConfig.project_id == project_id)
                    .order_by(ProjectConfig.version.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if config is None:
            raise ProblemError(409, "project_not_configured", "Configure the project before running the pipeline.")
        active = (
            await conn.execute(select(Run.id).where(Run.project_id == project_id, Run.status.in_(ACTIVE)).limit(1))
        ).first()
        if active is not None:
            raise ProblemError(409, "run_active", "The project already has a run in progress.", run_id=str(active.id))
        options = body.options.model_dump(exclude_unset=True, by_alias=False) if body.options else {}
        if body.kind == "pipeline":  # runs a person starts read the inventory in depth unless they opt out
            options = {"deep_inventory": body.deep_inventory is not False}
        run_id: uuid.UUID = (
            await conn.execute(
                insert(Run)
                .values(
                    tenant_id=auth.tenant_id, project_id=project_id, config_version=config["version"],
                    kind=body.kind, autonomy=config["autonomy"], max_iterations=config["max_iterations"],
                    options=options, started_by=auth.user_id,
                )
                .returning(Run.id)
            )
        ).scalar_one()  # fmt: skip
        await defer_run(conn, run_id, auth.tenant_id)
        await audit(
            conn, auth, "run.start", f"project:{project_id}",
            {"run_id": str(run_id), "kind": body.kind, "config_version": config["version"], "options": options},
        )  # fmt: skip
        return RunOut.model_validate(dict(await load_run(conn, project_id, run_id)))


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(request: Request, project_id: uuid.UUID, run_id: uuid.UUID, auth: ViewProject) -> RunDetail:
    money = await cost_visible(request, auth)
    async with transaction(request, auth) as conn:
        run = dict(await load_run(conn, project_id, run_id))
        phases = (
            await conn.execute(select(PhaseRun).where(PhaseRun.run_id == run_id).order_by(PhaseRun.position))
        ).mappings()
        phase_list = [PhaseRunOut.model_validate(dict(p)) for p in phases]
        invocations = (
            await conn.execute(
                select(AgentInvocation)
                .where(AgentInvocation.run_id == run_id)
                .order_by(AgentInvocation.started_at, AgentInvocation.iteration)
            )
        ).mappings()
        invocation_list = [
            InvocationOut.model_validate({**i, "cost_usd": i["cost_usd"] if money else None}) for i in invocations
        ]
        gates = (await conn.execute(gate_query().where(Gate.run_id == run_id).order_by(Gate.gate))).mappings()
        gate_list = [GateOut.model_validate(dict(g)) for g in gates]
        questions = (
            await conn.execute(question_query().where(Question.run_id == run_id).order_by(Question.created_at))
        ).mappings()
        question_list = [QuestionOut.model_validate(dict(q)) for q in questions]
    return RunDetail.model_validate(
        {
            **RunOut.model_validate(run).model_dump(),
            "phases": phase_list,
            "invocations": invocation_list,
            "gates": gate_list,
            "questions": question_list,
            "cost_visible": money,
        }
    )


@router.post("/{run_id}:cancel", response_model=RunOut)
async def cancel_run(request: Request, project_id: uuid.UUID, run_id: uuid.UUID, auth: RunPipeline) -> RunOut:
    """The run stops at its next step; its open questions are cancelled."""
    async with transaction(request, auth) as conn:
        run = await load_run(conn, project_id, run_id, lock=True)
        if run["status"] in FINAL:
            raise ProblemError(409, "run_finished", "The run has already finished.")
        await conn.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status="cancelled", waiting_reason=None, finished_at=func.now(), error="Cancelled by a person")
        )
        await conn.execute(
            update(Question).where(Question.run_id == run_id, Question.status == "open").values(status="cancelled")
        )
        await audit(conn, auth, "run.cancel", f"project:{project_id}", {"run_id": str(run_id)})
        return RunOut.model_validate(dict(await load_run(conn, project_id, run_id)))


async def approve_stories(conn: AsyncConnection, auth: Authorized, project_id: uuid.UUID) -> None:
    """At C1 the active stories are approved (a new version each); from then on a change is a change of scope."""
    for story in await spec_common.stories(conn, project_id):
        if story.active and story.status != "approved":
            await conn.execute(
                text(
                    "INSERT INTO user_story_version (tenant_id, story_id, version, feature, title, narrative, "
                    "criteria, links, priority, estimate, status, origin, out_of_scope, merged_into, reason, action, "
                    "created_by) "
                    "SELECT tenant_id, story_id, version + 1, feature, title, narrative, criteria, links, priority, "
                    "estimate, 'approved', origin, out_of_scope, merged_into, reason, 'status', :by "
                    "FROM user_story_version WHERE story_id = :s AND version = :v"
                ),
                {"s": story.id, "v": story.version, "by": auth.user_id},
            )


async def _decide(
    request: Request, project_id: uuid.UUID, run_id: uuid.UUID, gate: str, auth: Authorized, approve: bool,
    comment: str | None,
) -> GateOut:  # fmt: skip
    assert auth.tenant_id is not None  # noqa: S101 - require_gate guarantees it
    async with transaction(request, auth) as conn:
        started_by = (await load_run(conn, project_id, run_id))["started_by"]
        if started_by == auth.user_id:
            # Its own transaction: the refusal is audited although nothing else is written.
            await audit(
                conn, auth, "gate.decide", f"project:{project_id}",
                {"run_id": str(run_id), "gate": gate, "reason": "segregation_of_duties"}, outcome="denied",
            )  # fmt: skip
    if started_by == auth.user_id:
        raise ProblemError(403, "segregation_of_duties", "The person who launched the run cannot decide its gates.")
    async with transaction(request, auth) as conn:
        run = await load_run(conn, project_id, run_id, lock=True)
        found = (
            (await conn.execute(select(Gate).where(Gate.run_id == run_id, Gate.gate == gate).with_for_update()))
            .mappings()
            .one_or_none()
        )
        if found is None:
            raise not_found("gate")
        if found["status"] != "pending":
            raise ProblemError(409, "gate_decided", "The gate was already decided.")
        if run["status"] in FINAL:
            raise ProblemError(409, "run_finished", "The run has already finished.")
        # C1 approves the spec, the user stories and the plan together (7.7): code decides whether it can.
        if approve and gate == "C1" and run["kind"] == "pipeline":
            blockers = await spec_common.c1_blockers(conn, project_id)
            if blockers:
                raise ProblemError(409, "c1_blocked", "C1 cannot be approved yet.", blockers=blockers)
            await approve_stories(conn, auth, project_id)
            # Rule "create from the spec" (7.6): the approved stories go to the linked Jira / Azure DevOps project.
            linked = (
                await conn.execute(text("SELECT rules FROM project_backlog WHERE project_id = :p"), {"p": project_id})
            ).scalar_one_or_none()  # fmt: skip
            if linked is not None and linked.get("createFromSpec", True):
                await defer_backlog_sync(conn, project_id, auth.tenant_id, "C1")
        await conn.execute(
            update(Gate)
            .where(Gate.run_id == run_id, Gate.gate == gate)
            .values(
                status="approved" if approve else "rejected", decided_by=auth.user_id, decided_at=func.now(),
                comment=comment,
            )
        )  # fmt: skip
        if run["status"] == "waiting" and run["waiting_reason"] == "gate" and found["required"]:
            await defer_run(conn, run_id, auth.tenant_id)
        await audit(
            conn, auth, f"gate.{'approve' if approve else 'reject'}", f"project:{project_id}",
            {"run_id": str(run_id), "gate": gate, "required": found["required"], "comment": comment},
        )  # fmt: skip
        decided = (await conn.execute(gate_query().where(Gate.run_id == run_id, Gate.gate == gate))).mappings().one()
        return GateOut.model_validate(dict(decided))


@router.post("/{run_id}/gates/{gate}:approve", response_model=GateOut)
async def approve_gate(
    request: Request, project_id: uuid.UUID, run_id: uuid.UUID, gate: str, body: GateDecisionIn, auth: DecideGate
) -> GateOut:
    return await _decide(request, project_id, run_id, gate, auth, True, body.comment)


@router.post("/{run_id}/gates/{gate}:reject", response_model=GateOut)
async def reject_gate(
    request: Request, project_id: uuid.UUID, run_id: uuid.UUID, gate: str, body: GateDecisionIn, auth: DecideGate
) -> GateOut:
    if not (body.comment or "").strip():
        raise ProblemError(422, "comment_required", "Say why the gate is rejected.")
    return await _decide(request, project_id, run_id, gate, auth, False, body.comment)
