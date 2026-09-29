"""The migration plan by waves (spec 7.7): the platform suggests it, people change it, code validates it. Moving a
story before a hard dependency is rejected (also when the API is called directly); before a soft one it is saved
with a warning. Every change is a new version, audited."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.spec import common
from nexti_api.spec.schemas import PlanIn, PlanOut, PlanProblemOut

router = APIRouter(prefix="/api/v1/projects/{project_id}/plan", tags=["spec"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
EditPlan = Annotated[Authorized, Depends(require_project("plan.edit"))]


def _problems(items: list[Any]) -> list[PlanProblemOut]:
    return [PlanProblemOut(code=p.code, story=p.story, on=p.on, message=p.message) for p in items]


async def _out(conn: AsyncConnection, project_id: uuid.UUID) -> PlanOut:
    current = await common.plan(conn, project_id)
    if current is None:
        raise not_found("plan")
    stories = await common.stories(conn, project_id)
    keys = common.planned_stories(stories)
    waves = common.clean_waves(current["waves"], keys)
    suggested = common.clean_waves(current["suggested"], keys)
    check = common.check_plan(waves, stories, await common.dependencies(conn, project_id))
    return PlanOut(
        version=current["version"], waves=waves, suggested=suggested, differs_from_suggested=waves != suggested,
        errors=_problems(check.errors), warnings=_problems(check.warnings), change_note=current["change_note"],
        created_by_name=current["created_by_name"], created_at=current["created_at"],
    )  # fmt: skip


async def _save(
    conn: AsyncConnection, auth: Authorized, project_id: uuid.UUID, waves: list[list[str]], note: str | None
) -> None:
    current = await common.plan(conn, project_id)
    if current is None:
        raise not_found("plan")
    stories = await common.stories(conn, project_id)
    check = common.check_plan(waves, stories, await common.dependencies(conn, project_id))
    if check.errors:
        raise ProblemError(
            422, "invalid_plan", check.errors[0].message,
            problems=[p.model_dump(by_alias=True) for p in _problems(check.errors)],
        )  # fmt: skip
    await conn.execute(
        text(
            "INSERT INTO migration_plan (tenant_id, project_id, version, waves, suggested, warnings, change_note, "
            "created_by) VALUES (:t, :p, :v, CAST(:w AS jsonb), CAST(:s AS jsonb), CAST(:wa AS jsonb), :n, :by)"
        ),
        {
            "t": auth.tenant_id, "p": project_id, "v": current["version"] + 1, "w": json.dumps(waves),
            "s": json.dumps(current["suggested"]), "wa": json.dumps([p.message for p in check.warnings]),
            "n": note, "by": auth.user_id,
        },
    )  # fmt: skip
    await audit(conn, auth, "plan.change", f"project:{project_id}",
                {"version": current["version"] + 1, "waves": waves, "warnings": len(check.warnings)})  # fmt: skip


@router.get("", response_model=PlanOut)
async def get_plan(request: Request, project_id: uuid.UUID, auth: ViewProject) -> PlanOut:
    async with transaction(request, auth) as conn:
        return await _out(conn, project_id)


@router.put("", response_model=PlanOut)
async def change_plan(request: Request, project_id: uuid.UUID, body: PlanIn, auth: EditPlan) -> PlanOut:
    waves = [list(dict.fromkeys(w)) for w in body.waves if w]
    async with transaction(request, auth) as conn:
        await _save(conn, auth, project_id, waves, body.change_note)
        return await _out(conn, project_id)


@router.post(":reset", response_model=PlanOut)
async def reset_plan(request: Request, project_id: uuid.UUID, auth: EditPlan) -> PlanOut:
    """Back to the order the platform suggested."""
    async with transaction(request, auth) as conn:
        current = await common.plan(conn, project_id)
        if current is None:
            raise not_found("plan")
        keys = common.planned_stories(await common.stories(conn, project_id))
        await _save(conn, auth, project_id, common.clean_waves(current["suggested"], keys), "Back to the suggestion")
        return await _out(conn, project_id)
