"""Helpers for the tests of runs: a configuration version, a run, and the worker's runtime on the throwaway database.
The worker is a separate application; these tests exercise the API and the worker together, as they run."""

import json
import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_sandbox import Limits, SandboxResult
from nexti_worker.runner import Runtime

TARGET = {
    "architecture": "modular-monolith",
    "backend": "spring-boot",
    "frontend": "react",
    "database": "postgresql",
    "cloud": "aws",
}
# A small but complete team for the modernization flow (every agent_required phase covered).
TEAM = {
    "legacy-analyst": "1.4.0",
    "rules-extractor": "2.1.0",
    "solution-architect": "1.3.0",
    "backend-dev": "1.5.0",
    "equivalence-validator": "1.4.0",
}


class FakeSandbox:
    """Answers like the sandbox without running anything (the Docker sandbox has its own tests)."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self, command: list[str], files: Mapping[str, bytes] | None = None, limits: Limits | None = None
    ) -> SandboxResult:
        self.calls += 1
        files = files or {}
        if "module.py" in files:
            ok = b"+ 0\n" in files["module.py"]
            return SandboxResult(0 if ok else 1, "1 passed" if ok else "", "" if ok else "AssertionError", False, 5)
        return SandboxResult(0, "{}", "", False, 5)


def psycopg_dsn(app_url: URL) -> str:
    return app_url.set(drivername="postgresql").render_as_string(hide_password=False)


def runtime(app_engine: AsyncEngine, app_url: URL, http: httpx.AsyncClient, sandbox: Any = None) -> Runtime:
    return Runtime(engine=app_engine, dsn=psycopg_dsn(app_url), sandbox=sandbox or FakeSandbox(), http=http)


async def make_project(owner: AsyncEngine, tenant_id: uuid.UUID) -> uuid.UUID:
    """A project of its own per test: runs, inputs and configurations of other tests never mix in."""
    async with owner.begin() as conn:
        project_id: uuid.UUID = (
            await conn.execute(
                text("INSERT INTO project (tenant_id, name) VALUES (:t, :n) RETURNING id"),
                {"t": tenant_id, "n": f"Run test {uuid.uuid4().hex[:8]}"},
            )
        ).scalar_one()
    return project_id


async def make_config(
    owner: AsyncEngine,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    template: str = "internalAgile",
    autonomy: str = "balanced",
    max_iterations: int = 3,
) -> int:
    async with owner.begin() as conn:
        version: int = (
            await conn.execute(
                text("SELECT COALESCE(max(version), 0) + 1 FROM project_config WHERE project_id = :p"),
                {"p": project_id},
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO project_config (tenant_id, project_id, version, sources, target, pipeline_template, "
                "autonomy, max_iterations, sampling_pct) VALUES (:t, :p, :v, ARRAY['cobol'], "
                "CAST(:target AS jsonb), :template, :autonomy, :max_iterations, 10)"
            ),
            {
                "t": tenant_id, "p": project_id, "v": version, "target": json.dumps(TARGET),
                "template": template, "autonomy": autonomy, "max_iterations": max_iterations,
            },
        )  # fmt: skip
        for key, agent_version in TEAM.items():
            await conn.execute(
                text(
                    "INSERT INTO project_agent (tenant_id, project_id, config_version, agent_key, agent_version) "
                    "VALUES (:t, :p, :v, :k, :av)"
                ),
                {"t": tenant_id, "p": project_id, "v": version, "k": key, "av": agent_version},
            )
    return int(version)


async def make_run(
    owner: AsyncEngine,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    version: int,
    *,
    kind: str = "demo",
    options: dict[str, Any] | None = None,
    started_by: uuid.UUID | None = None,
    autonomy: str = "balanced",
    max_iterations: int = 3,
) -> uuid.UUID:
    async with owner.begin() as conn:
        run_id: uuid.UUID = (
            await conn.execute(
                text(
                    "INSERT INTO run (tenant_id, project_id, config_version, kind, autonomy, max_iterations, options, "
                    "started_by) VALUES (:t, :p, :v, :kind, :autonomy, :max_iterations, CAST(:options AS jsonb), :by) "
                    "RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "p": project_id,
                    "v": version,
                    "kind": kind,
                    "autonomy": autonomy,
                    "max_iterations": max_iterations,
                    "options": json.dumps(options or {}),
                    "by": started_by,
                },
            )
        ).scalar_one()
    return uuid.UUID(str(run_id))


async def fetch(owner: AsyncEngine, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with owner.begin() as conn:
        return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]


async def execute(owner: AsyncEngine, sql: str, **params: Any) -> None:
    async with owner.begin() as conn:
        await conn.execute(text(sql), params)


VALID_CRITERION = "Scenario: Pay\n  Given a pending order\n  When it is paid\n  Then it is marked A"


async def seed_spec(owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Three rules, three stories (US-002 depends hard on US-001, US-003 soft on US-002) and plan version 1."""
    async with owner.begin() as conn:
        for number in (1, 2, 3):
            data = {
                "id": f"RULE-00{number}", "name": f"Rule {number}", "category": "validation", "priority": "P1",
                "statement": f"The statement of rule number {number}.",
                "sources": [{"file": "sp_pago_orden.sp", "line_start": 30 + number * 10, "line_end": 32 + number * 10}],
            }  # fmt: skip
            await conn.execute(
                text(
                    "INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data) "
                    "VALUES (:t, :p, 'rule', :k, 1, 'review', CAST(:d AS jsonb))"
                ),
                {"t": tenant_id, "p": project_id, "k": f"RULE-00{number}", "d": json.dumps(data)},
            )
        ids: dict[str, uuid.UUID] = {}
        for number in (1, 2, 3):
            key = f"US-00{number}"
            story_id: uuid.UUID = (
                await conn.execute(
                    text("INSERT INTO user_story (tenant_id, project_id, key) VALUES (:t, :p, :k) RETURNING id"),
                    {"t": tenant_id, "p": project_id, "k": key},
                )
            ).scalar_one()
            ids[key] = story_id
            await conn.execute(
                text(
                    "INSERT INTO user_story_version (tenant_id, story_id, version, title, criteria, links, status) "
                    "VALUES (:t, :s, 1, :ti, CAST(:c AS jsonb), CAST(:l AS jsonb), 'review')"
                ),
                {"t": tenant_id, "s": story_id, "ti": f"Story {number}", "c": json.dumps([VALID_CRITERION]),
                 "l": json.dumps([f"RULE-00{number}"])},
            )  # fmt: skip
        for story, on, strength in (("US-002", "US-001", "hard"), ("US-003", "US-002", "soft")):
            await conn.execute(
                text(
                    "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason) "
                    "VALUES (:t, :s, :o, :st, 'shares a table')"
                ),
                {"t": tenant_id, "s": ids[story], "o": ids[on], "st": strength},
            )
        waves = json.dumps([["US-001"], ["US-002"], ["US-003"]])
        await conn.execute(
            text(
                "INSERT INTO migration_plan (tenant_id, project_id, version, waves, suggested) "
                "VALUES (:t, :p, 1, CAST(:w AS jsonb), CAST(:w AS jsonb))"
            ),
            {"t": tenant_id, "p": project_id, "w": waves},
        )
