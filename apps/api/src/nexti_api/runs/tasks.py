"""My tasks (spec 10.4, 18.2): the questions and gate approvals the user can resolve, across every project they may
see in the active tenant. Gates of runs the user launched are not theirs to decide (segregation of duties)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from nexti_api.admin.common import transaction
from nexti_api.authz import names
from nexti_api.authz.require import GATE_PERMISSIONS, Authorized, require_tenant
from nexti_api.runs.schemas import TaskOut
from nexti_core.db.models import Gate, Project, Question, Run

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
RELATIONS = ["question_answer", *(names.relation(p) for p in GATE_PERMISSIONS.values())]
MAX_PROJECTS = 200


@router.get("", response_model=list[TaskOut])
async def my_tasks(request: Request, auth: TenantMember) -> list[TaskOut]:
    fga = request.app.state.fga
    user = names.user(auth.user_id)
    visible = [uuid.UUID(o.split(":", 1)[1]) for o in await fga.list_objects(user, "viewer", "project")]
    answerable: set[uuid.UUID] = set()
    gates_by_project: dict[uuid.UUID, set[str]] = {}
    for project_id in visible[:MAX_PROJECTS]:
        allowed = await fga.batch_check(user, names.project(project_id), RELATIONS)
        if allowed.get("question_answer"):
            answerable.add(project_id)
        gates = {g for g, p in GATE_PERMISSIONS.items() if allowed.get(names.relation(p))}
        if gates:
            gates_by_project[project_id] = gates
    tasks: list[TaskOut] = []
    async with transaction(request, auth) as conn:
        if answerable:
            rows = (
                await conn.execute(
                    select(Question, Project.name.label("project_name"))
                    .join(Project, Project.id == Question.project_id)
                    .where(Question.status == "open", Question.project_id.in_(answerable))
                )
            ).mappings()
            tasks += [
                TaskOut(
                    kind="question",
                    project_id=r["project_id"],
                    project_name=r["project_name"],
                    run_id=r["run_id"],
                    question_id=r["id"],
                    phase=r["phase"],
                    title=r["question_text"],
                    impact=r["impact"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        if gates_by_project:
            gate_rows = (
                await conn.execute(
                    select(Gate, Run.project_id, Run.current_phase, Run.started_by, Project.name.label("project_name"))
                    .join(Run, Run.id == Gate.run_id)
                    .join(Project, Project.id == Run.project_id)
                    .where(
                        Gate.status == "pending",
                        Gate.required,
                        Run.status == "waiting",
                        Run.waiting_reason == "gate",
                        Run.project_id.in_(gates_by_project),
                    )
                )
            ).mappings()
            tasks += [
                TaskOut(
                    kind="gate",
                    project_id=r["project_id"],
                    project_name=r["project_name"],
                    run_id=r["run_id"],
                    gate=r["gate"],
                    phase=r["current_phase"] or "",
                    title=f"Approve gate {r['gate']}",
                    impact="high",
                    created_at=r["requested_at"],
                )
                for r in gate_rows
                if r["gate"] in gates_by_project[r["project_id"]] and r["started_by"] != auth.user_id
            ]
    # High impact first, then the oldest.
    return sorted(tasks, key=lambda t: (t.impact != "high", t.created_at))
