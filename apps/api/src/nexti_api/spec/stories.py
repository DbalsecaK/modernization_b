"""User stories of a project (spec 7.7): see, edit, create, split, merge, discard and restore, each as a new
version with its author, audited. Acceptance criteria are validated by code on every save (D-26); the same
validator answers the editor live (`POST /gherkin:validate`). Coverage and C1 readiness are computed, never typed."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, authenticated, require_project
from nexti_api.errors import ProblemError
from nexti_api.spec import common
from nexti_api.spec.schemas import (
    C1CheckOut,
    CoverageOut,
    DependencyIn,
    DiscardIn,
    GherkinIn,
    GherkinOut,
    GherkinProblemOut,
    MergeIn,
    RuleOut,
    SplitIn,
    StoryIn,
    StoryOut,
)
from nexti_core.spec import gherkin

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["spec"])
tools = APIRouter(prefix="/api/v1", tags=["spec"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
EditStories = Annotated[Authorized, Depends(require_project("story.edit"))]
EditPlan = Annotated[Authorized, Depends(require_project("plan.edit"))]
Session = Annotated[Authorized, Depends(authenticated())]


def problems_of(criteria: list[str]) -> list[GherkinProblemOut]:
    return [
        GherkinProblemOut(criterion=index, code=p.code, line=p.line, message=p.message)
        for index, found in sorted(gherkin.validate_criteria(criteria).items())
        for p in found
    ]


def require_valid(criteria: list[str]) -> None:
    problems = problems_of(criteria)
    if problems:
        raise ProblemError(
            422, "invalid_gherkin", "Some acceptance criteria are not valid Gherkin.",
            problems=[p.model_dump(by_alias=True) for p in problems],
        )  # fmt: skip


@tools.post("/gherkin:validate", response_model=GherkinOut)
async def validate_gherkin(body: GherkinIn, auth: Session) -> GherkinOut:
    """The validator of the server, for the editor while the person types (the same code that guards saving)."""
    problems = problems_of(body.criteria)
    return GherkinOut(valid=not problems, problems=problems)


async def _story_out(conn: AsyncConnection, project_id: uuid.UUID, row: common.StoryRow) -> StoryOut:
    deps = [d for d in await common.dependencies(conn, project_id) if d["story"] == row.key]
    merged = None
    if row.merged_into:
        merged = (await conn.execute(text("SELECT key FROM user_story WHERE id = :i"), {"i": row.merged_into})).scalar()
    return StoryOut.model_validate({
        **{k: getattr(row, k) for k in ("key", "version", "feature", "title", "narrative", "criteria", "links",
                                        "priority", "estimate", "status", "origin", "out_of_scope", "reason",
                                        "action", "created_by", "created_by_name", "created_at")},
        "merged_into": merged, "traced": bool(row.links),
        "depends_on": [{"on": d["on_key"], "strength": d["strength"], "reason": d["reason"], "origin": d["origin"]}
                       for d in deps],
    })  # fmt: skip


async def _new_version(
    conn: AsyncConnection, auth: Authorized, current: common.StoryRow | None, story_id: uuid.UUID,
    values: dict[str, Any], action: str,
) -> None:  # fmt: skip
    base = {k: getattr(current, k) for k in ("feature", "title", "narrative", "criteria", "links", "priority",
                                              "estimate", "status", "origin", "out_of_scope", "merged_into",
                                              "reason")} if current else {}  # fmt: skip
    data = {**base, **values}
    await conn.execute(
        text(
            "INSERT INTO user_story_version (tenant_id, story_id, version, feature, title, narrative, criteria, links, "
            "priority, estimate, status, origin, out_of_scope, merged_into, reason, action, created_by) VALUES (:t, "
            ":s, :v, :f, :ti, :n, CAST(:c AS jsonb), CAST(:l AS jsonb), :pr, :e, :st, :o, :oos, :mi, :r, :a, :by)"
        ),
        {
            "t": auth.tenant_id, "s": story_id, "v": (current.version + 1) if current else 1,
            "f": data.get("feature", ""), "ti": data["title"], "n": data.get("narrative", ""),
            "c": json.dumps(data.get("criteria", [])), "l": json.dumps(data.get("links", [])),
            "pr": data.get("priority", "P1"), "e": data.get("estimate", 3), "st": data.get("status", "review"),
            "o": data.get("origin", "person"), "oos": data.get("out_of_scope", False),
            "mi": data.get("merged_into"), "r": data.get("reason"), "a": action, "by": auth.user_id,
        },
    )  # fmt: skip


async def _load(conn: AsyncConnection, project_id: uuid.UUID, key: str) -> common.StoryRow:
    row = await common.story(conn, project_id, key)
    if row is None:
        raise not_found("story")
    return row


async def _check_links(conn: AsyncConnection, project_id: uuid.UUID, links: list[str]) -> None:
    known = set(await common.rule_keys(conn, project_id))
    unknown = sorted(set(links) - known)
    if unknown:
        raise ProblemError(422, "unknown_link", f"Unknown spec elements: {', '.join(unknown)}.")


async def _next_key(conn: AsyncConnection, project_id: uuid.UUID) -> str:
    keys: list[str] = list(
        (await conn.execute(text("SELECT key FROM user_story WHERE project_id = :p"), {"p": project_id})).scalars()
    )
    numbers = [int(k.split("-")[1]) for k in keys]
    return f"US-{max(numbers, default=0) + 1:03d}"


async def _create(conn: AsyncConnection, auth: Authorized, project_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    key = await _next_key(conn, project_id)
    story_id: uuid.UUID = (
        await conn.execute(
            text("INSERT INTO user_story (tenant_id, project_id, key) VALUES (:t, :p, :k) RETURNING id"),
            {"t": auth.tenant_id, "p": project_id, "k": key},
        )
    ).scalar_one()
    return key, story_id


# -- rules -------------------------------------------------------------------------------------------------------
@router.get("/spec/rules", response_model=list[RuleOut])
async def list_rules(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[RuleOut]:
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (key) key, version, status, data, origin, created_at FROM spec_element "
                    "WHERE project_id = :p AND element_type = 'rule' ORDER BY key, version DESC"
                ),
                {"p": project_id},
            )
        ).mappings()
        return [RuleOut.model_validate(dict(r)) for r in rows]


@router.get("/spec/rules/{key}/versions", response_model=list[RuleOut])
async def rule_versions(request: Request, project_id: uuid.UUID, key: str, auth: ViewProject) -> list[RuleOut]:
    async with transaction(request, auth) as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT key, version, status, data, origin, created_at FROM spec_element WHERE project_id = :p "
                        "AND element_type = 'rule' AND key = :k ORDER BY version DESC"
                    ),
                    {"p": project_id, "k": key},
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        raise not_found("rule")
    return [RuleOut.model_validate(dict(r)) for r in rows]


# -- stories -----------------------------------------------------------------------------------------------------
@router.get("/stories", response_model=list[StoryOut])
async def list_stories(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[StoryOut]:
    async with transaction(request, auth) as conn:
        return [await _story_out(conn, project_id, s) for s in await common.stories(conn, project_id)]


@router.get("/stories/{key}/versions", response_model=list[StoryOut])
async def story_versions(request: Request, project_id: uuid.UUID, key: str, auth: ViewProject) -> list[StoryOut]:
    async with transaction(request, auth) as conn:
        current = await _load(conn, project_id, key)
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT s.id, s.key, v.version, v.feature, v.title, v.narrative, v.criteria, v.links, "
                        "v.priority, v.estimate, v.status, v.origin, v.out_of_scope, v.merged_into, v.reason, "
                        "v.action, v.created_by, u.display_name AS created_by_name, v.created_at "
                        "FROM user_story s JOIN user_story_version v ON "
                        "v.story_id = s.id LEFT JOIN app_user u ON u.id = v.created_by WHERE s.id = :i "
                        "ORDER BY v.version DESC"
                    ),
                    {"i": current.id},
                )
            )
            .mappings()
            .all()
        )
        return [await _story_out(conn, project_id, common.StoryRow(**dict(r))) for r in rows]


@router.post("/stories", response_model=StoryOut, status_code=201)
async def create_story(request: Request, project_id: uuid.UUID, body: StoryIn, auth: EditStories) -> StoryOut:
    """A story written by a person. Without links it is listed as untraced (7.7)."""
    require_valid(body.criteria)
    async with transaction(request, auth) as conn:
        await _check_links(conn, project_id, body.links)
        key, story_id = await _create(conn, auth, project_id)
        await _new_version(conn, auth, None, story_id, {**body.model_dump(), "status": "review", "origin": "person"},
                           "create")  # fmt: skip
        await audit(conn, auth, "story.create", f"project:{project_id}", {"story": key, "links": body.links})
        return await _story_out(conn, project_id, await _load(conn, project_id, key))


@router.put("/stories/{key}", response_model=StoryOut)
async def edit_story(request: Request, project_id: uuid.UUID, key: str, body: StoryIn, auth: EditStories) -> StoryOut:
    """A new version; an approved story goes back to review (after C1 every change is a change of scope, 7.7)."""
    require_valid(body.criteria)
    async with transaction(request, auth) as conn:
        current = await _load(conn, project_id, key)
        if not current.active:
            raise ProblemError(409, "story_inactive", "Restore the story before editing it.")
        await _check_links(conn, project_id, body.links)
        await _new_version(conn, auth, current, current.id, {**body.model_dump(), "status": "review"}, "edit")
        await audit(conn, auth, "story.edit", f"project:{project_id}", {"story": key, "version": current.version + 1})
        return await _story_out(conn, project_id, await _load(conn, project_id, key))


@router.post("/stories/{key}:split", response_model=list[StoryOut])
async def split_story(
    request: Request, project_id: uuid.UUID, key: str, body: SplitIn, auth: EditStories
) -> list[StoryOut]:
    """The chosen criteria and links move to a new story; both go back to review; dependencies are copied."""
    async with transaction(request, auth) as conn:
        current = await _load(conn, project_id, key)
        if not current.active:
            raise ProblemError(409, "story_inactive", "Only an active story can be split.")
        moving = sorted(set(body.criteria))
        if any(i < 0 or i >= len(current.criteria) for i in moving) or set(body.links) - set(current.links):
            raise ProblemError(422, "invalid_split", "Choose criteria and links of the story.")
        if not moving and not body.links:
            raise ProblemError(422, "invalid_split", "Move at least one criterion or link.")
        new_criteria = [current.criteria[i] for i in moving]
        kept = [c for i, c in enumerate(current.criteria) if i not in moving]
        require_valid(new_criteria)
        new_key, new_id = await _create(conn, auth, project_id)
        await _new_version(conn, auth, None, new_id, {
            "feature": current.feature, "title": body.title, "narrative": current.narrative, "criteria": new_criteria,
            "links": body.links, "priority": current.priority, "estimate": max(1, current.estimate // 2),
            "status": "review", "origin": current.origin,
        }, "split")  # fmt: skip
        await _new_version(conn, auth, current, current.id, {
            "criteria": kept, "links": [link for link in current.links if link not in body.links], "status": "review",
        }, "split")  # fmt: skip
        await conn.execute(
            text(
                "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason, origin, created_by) "
                "SELECT tenant_id, :n, depends_on, strength, reason, 'person', :by FROM story_dependency "
                "WHERE story_id = :o ON CONFLICT DO NOTHING"
            ),
            {"n": new_id, "o": current.id, "by": auth.user_id},
        )
        await audit(conn, auth, "story.split", f"project:{project_id}", {"story": key, "new_story": new_key})
        return [await _story_out(conn, project_id, await _load(conn, project_id, k)) for k in (key, new_key)]


@router.post("/stories/{key}:merge", response_model=StoryOut)
async def merge_story(request: Request, project_id: uuid.UUID, key: str, body: MergeIn, auth: EditStories) -> StoryOut:
    """`key` is absorbed by `into`: criteria, links and dependencies go to it; who depended on `key` now depends on
    `into`; `key` stays as merged (7.7)."""
    if body.into == key:
        raise ProblemError(422, "invalid_merge", "A story cannot be merged into itself.")
    async with transaction(request, auth) as conn:
        absorbed = await _load(conn, project_id, key)
        target = await _load(conn, project_id, body.into)
        if not absorbed.active or not target.active:
            raise ProblemError(409, "story_inactive", "Both stories must be active.")
        names = {gherkin.scenario_name(c) for c in target.criteria}
        criteria = target.criteria + [c for c in absorbed.criteria if gherkin.scenario_name(c) not in names]
        links = target.links + [link for link in absorbed.links if link not in target.links]
        await _new_version(conn, auth, target, target.id, {
            "criteria": criteria, "links": links, "status": "review",
            "estimate": min(100, target.estimate + absorbed.estimate),
        }, "merge")  # fmt: skip
        await _new_version(conn, auth, absorbed, absorbed.id, {"status": "merged", "merged_into": target.id}, "merge")
        for sql in (
            "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason, origin, created_by) "
            "SELECT tenant_id, :t, depends_on, strength, reason, origin, :by FROM story_dependency "
            "WHERE story_id = :a AND depends_on <> :t ON CONFLICT DO NOTHING",
            "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason, origin, created_by) "
            "SELECT tenant_id, story_id, :t, strength, reason, origin, :by FROM story_dependency "
            "WHERE depends_on = :a AND story_id <> :t ON CONFLICT DO NOTHING",
            "DELETE FROM story_dependency WHERE story_id = :a OR depends_on = :a",
        ):
            await conn.execute(text(sql), {"t": target.id, "a": absorbed.id, "by": auth.user_id})
        await audit(conn, auth, "story.merge", f"project:{project_id}", {"story": key, "into": body.into})
        return await _story_out(conn, project_id, await _load(conn, project_id, body.into))


@router.post("/stories/{key}:discard", response_model=StoryOut)
async def discard_story(
    request: Request, project_id: uuid.UUID, key: str, body: DiscardIn, auth: EditStories
) -> StoryOut:
    """With a reason. Its rules become a coverage gap unless it is out of scope (they migrate as they are)."""
    async with transaction(request, auth) as conn:
        current = await _load(conn, project_id, key)
        if not current.active:
            raise ProblemError(409, "story_inactive", "The story is not active.")
        await _new_version(conn, auth, current, current.id,
                           {"status": "discarded", "reason": body.reason, "out_of_scope": body.out_of_scope},
                           "discard")  # fmt: skip
        await audit(conn, auth, "story.discard", f"project:{project_id}",
                    {"story": key, "out_of_scope": body.out_of_scope})  # fmt: skip
        return await _story_out(conn, project_id, await _load(conn, project_id, key))


@router.post("/stories/{key}:restore", response_model=StoryOut)
async def restore_story(request: Request, project_id: uuid.UUID, key: str, auth: EditStories) -> StoryOut:
    async with transaction(request, auth) as conn:
        current = await _load(conn, project_id, key)
        if current.status != "discarded":
            raise ProblemError(409, "story_not_discarded", "Only a discarded story can be restored.")
        await _new_version(conn, auth, current, current.id,
                           {"status": "review", "reason": None, "out_of_scope": False}, "restore")  # fmt: skip
        await audit(conn, auth, "story.restore", f"project:{project_id}", {"story": key})
        return await _story_out(conn, project_id, await _load(conn, project_id, key))


# -- dependencies (the plan owners add or remove them) -------------------------------------------------------------
@router.post("/stories/{key}/dependencies", response_model=StoryOut, status_code=201)
async def add_dependency(
    request: Request, project_id: uuid.UUID, key: str, body: DependencyIn, auth: EditPlan
) -> StoryOut:
    if body.on == key:
        raise ProblemError(422, "invalid_dependency", "A story cannot depend on itself.")
    async with transaction(request, auth) as conn:
        story = await _load(conn, project_id, key)
        other = await _load(conn, project_id, body.on)
        await conn.execute(
            text(
                "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason, origin, created_by) "
                "VALUES (:t, :s, :o, :st, :r, 'person', :by) ON CONFLICT (story_id, depends_on) DO NOTHING"
            ),
            {"t": auth.tenant_id, "s": story.id, "o": other.id, "st": body.strength, "r": body.reason,
             "by": auth.user_id},
        )  # fmt: skip
        await audit(conn, auth, "story.dependency_add", f"project:{project_id}",
                    {"story": key, "on": body.on, "strength": body.strength})  # fmt: skip
        return await _story_out(conn, project_id, story)


@router.delete("/stories/{key}/dependencies/{on}", response_model=StoryOut)
async def remove_dependency(request: Request, project_id: uuid.UUID, key: str, on: str, auth: EditPlan) -> StoryOut:
    async with transaction(request, auth) as conn:
        story = await _load(conn, project_id, key)
        other = await _load(conn, project_id, on)
        result = await conn.execute(
            text("DELETE FROM story_dependency WHERE story_id = :s AND depends_on = :o"), {"s": story.id, "o": other.id}
        )
        if not result.rowcount:
            raise not_found("dependency")
        await audit(conn, auth, "story.dependency_remove", f"project:{project_id}", {"story": key, "on": on})
        return await _story_out(conn, project_id, story)


# -- coverage and C1 readiness -------------------------------------------------------------------------------------
@router.get("/coverage", response_model=CoverageOut)
async def get_coverage(request: Request, project_id: uuid.UUID, auth: ViewProject) -> CoverageOut:
    async with transaction(request, auth) as conn:
        elements = await common.rule_keys(conn, project_id)
        result = common.coverage(await common.stories(conn, project_id), elements)
    return CoverageOut(
        elements=len(elements), covered=result.covered, gaps=result.gaps, out_of_scope=result.out_of_scope,
        untraced_stories=result.untraced_stories, complete=result.complete,
    )  # fmt: skip


@router.get("/c1-check", response_model=C1CheckOut)
async def c1_check(request: Request, project_id: uuid.UUID, auth: ViewProject) -> C1CheckOut:
    async with transaction(request, auth) as conn:
        blockers = await common.c1_blockers(conn, project_id)
    return C1CheckOut(can_approve=not blockers, blockers=blockers)
