"""Reading the spec, the user stories and the plan of a project (current versions), shared by the routers of this
package and by the C1 gate check. Everything is computed by code (spec 7.7): coverage, Gherkin validity, the plan's
dependency check."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_core.spec import gherkin
from nexti_core.spec.coverage import ACTIVE, Coverage, StoryLinks, compute
from nexti_core.spec.plan import Dependency, PlanCheck, validate


@dataclass
class StoryRow:
    id: uuid.UUID
    key: str
    version: int
    feature: str
    title: str
    narrative: str
    criteria: list[str]
    links: list[str]
    priority: str
    estimate: int
    status: str
    origin: str
    out_of_scope: bool
    merged_into: uuid.UUID | None
    reason: str | None
    action: str
    created_by: uuid.UUID | None
    created_by_name: str | None
    created_at: Any

    @property
    def active(self) -> bool:
        return self.status in ACTIVE


CURRENT_STORIES = text("""
    SELECT DISTINCT ON (s.id) s.id, s.key, v.version, v.feature, v.title, v.narrative, v.criteria, v.links,
           v.priority, v.estimate, v.status, v.origin, v.out_of_scope, v.merged_into, v.reason, v.action,
           v.created_by, u.display_name AS created_by_name, v.created_at
      FROM user_story s
      JOIN user_story_version v ON v.story_id = s.id
      LEFT JOIN app_user u ON u.id = v.created_by
     WHERE s.project_id = :p
     ORDER BY s.id, v.version DESC
""")


async def stories(conn: AsyncConnection, project_id: uuid.UUID) -> list[StoryRow]:
    rows = (await conn.execute(CURRENT_STORIES, {"p": project_id})).mappings().all()
    return sorted((StoryRow(**dict(r)) for r in rows), key=lambda s: s.key)


async def story(conn: AsyncConnection, project_id: uuid.UUID, key: str) -> StoryRow | None:
    return next((s for s in await stories(conn, project_id) if s.key == key), None)


async def rule_keys(conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT ON (key) key, status FROM spec_element WHERE project_id = :p "
                "AND element_type = 'rule' ORDER BY key, version DESC"
            ),
            {"p": project_id},
        )
    ).all()
    return [r.key for r in rows if r.status != "obsolete"]


async def dependencies(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT a.key AS story, b.key AS on_key, d.strength, d.reason, d.origin FROM story_dependency d "
                "JOIN user_story a ON a.id = d.story_id JOIN user_story b ON b.id = d.depends_on "
                "WHERE a.project_id = :p ORDER BY a.key, b.key"
            ),
            {"p": project_id},
        )
    ).mappings()
    return [dict(r) for r in rows]


def dependency_list(rows: list[dict[str, Any]]) -> list[Dependency]:
    return [Dependency(r["story"], r["on_key"], r["strength"], r["reason"]) for r in rows]


async def plan(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT m.version, m.waves, m.suggested, m.warnings, m.change_note, m.created_at, m.created_by, "
                    "u.display_name AS created_by_name FROM migration_plan m "
                    "LEFT JOIN app_user u ON u.id = m.created_by WHERE m.project_id = :p "
                    "ORDER BY m.version DESC LIMIT 1"
                ),
                {"p": project_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def planned_stories(all_stories: list[StoryRow]) -> list[str]:
    """The stories a plan must place: the active ones (discarded and merged stories leave the plan)."""
    return [s.key for s in all_stories if s.active]


def clean_waves(waves: list[list[str]], keys: list[str]) -> list[list[str]]:
    """The plan without stories that left it, plus active stories it does not have yet (appended to the last wave)."""
    known = set(keys)
    cleaned = [[k for k in wave if k in known] for wave in waves]
    placed = {k for wave in cleaned for k in wave}
    missing = [k for k in keys if k not in placed]
    if missing:
        if not cleaned:
            cleaned = [[]]
        cleaned[-1] = cleaned[-1] + missing
    return [w for w in cleaned if w]


def check_plan(waves: list[list[str]], all_stories: list[StoryRow], deps: list[dict[str, Any]]) -> PlanCheck:
    keys = planned_stories(all_stories)
    active_deps = [d for d in dependency_list(deps) if d.story in keys and d.on in keys]
    return validate(waves, active_deps, keys)


def coverage(all_stories: list[StoryRow], elements: list[str]) -> Coverage:
    return compute(
        elements,
        [StoryLinks(s.key, s.status, frozenset(s.links), s.out_of_scope) for s in all_stories],  # type: ignore[arg-type]
    )


async def c1_blockers(conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    """Why C1 cannot be approved (7.7): stories with open questions, without criteria, with invalid Gherkin, or a plan
    with broken hard dependencies. Empty when C1 may be approved."""
    all_stories = await stories(conn, project_id)
    active = [s for s in all_stories if s.active]
    reasons: list[str] = []
    if not active:
        reasons.append("There are no user stories to approve.")
    open_questions: list[list[str]] = list(
        (
            await conn.execute(
                text("SELECT affects FROM question WHERE project_id = :p AND status = 'open'"), {"p": project_id}
            )
        ).scalars()
    )
    asked = {str(a) for affects in open_questions for a in affects}
    for s in active:
        if s.status == "question" or set(s.links) & asked:
            reasons.append(f"{s.key} has open questions.")
        if not s.criteria:
            reasons.append(f"{s.key} has no acceptance criteria.")
        elif gherkin.validate_criteria(s.criteria):
            reasons.append(f"{s.key} has invalid Gherkin criteria.")
    current = await plan(conn, project_id)
    if current is None:
        reasons.append("There is no migration plan.")
    else:
        check = check_plan(clean_waves(current["waves"], planned_stories(all_stories)), all_stories,
                           await dependencies(conn, project_id))  # fmt: skip
        reasons += [p.message for p in check.errors]
    return reasons
