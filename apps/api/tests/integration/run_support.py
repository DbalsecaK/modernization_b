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
