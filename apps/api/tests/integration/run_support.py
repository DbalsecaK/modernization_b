"""Helpers for the tests of runs: a configuration version, a run, and the worker's runtime on the throwaway database.
The worker is a separate application; these tests exercise the API and the worker together, as they run."""

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
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
    team: Mapping[str, str] | None = None,
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
        for key, agent_version in (team or TEAM).items():
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


LEGACY_SOURCE = (
    Path(__file__).resolve().parents[4] / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp"
)
SERVICE_JAVA = """package demo.application;

/** Pays one order. */
public class PayOrderService {
    // RULE-001: only current, savings and virtual accounts
    public boolean debitable(String type) {
        return "CTE".equals(type) || "AHO".equals(type) || "VIR".equals(type);
    }
}
"""


async def seed_validation(owner: AsyncEngine, store: Any, tenant_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    """On a project seeded with `seed_spec`: the legacy archive, one generated file tracing RULE-001 and a verdict
    with its proof pack (a golden case for RULE-001 that matched). Returns the verdict id."""
    import hashlib
    import io
    import zipfile

    from nexti_core.object_store import input_key
    from nexti_core.spec.model import Rule
    from nexti_verification import CaseOutcome, build_proof_pack, compute, trace_rules
    from nexti_verification import verdict as checks

    version = await make_config(owner, tenant_id, project_id)
    run_id = await make_run(owner, tenant_id, project_id, version, kind="pipeline")
    source = LEGACY_SOURCE.read_bytes()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("sp/sp_pago_orden.sp", source)
    data = archive.getvalue()
    input_id = uuid.uuid4()
    await store.put(input_key(tenant_id, project_id, input_id), io.BytesIO(data), len(data), "application/zip")
    java = SERVICE_JAVA.encode("utf-8")
    java_key = f"tenants/{tenant_id}/projects/{project_id}/runs/{run_id}/files/PayOrderService.java"
    await store.put(java_key, io.BytesIO(java), len(java), "text/plain; charset=utf-8")
    rule = Rule.model_validate({
        "id": "RULE-001", "name": "Rule 1", "category": "validation", "priority": "P1",
        "statement": "The statement of rule number 1.",
        "sources": [{"file": "sp_pago_orden.sp", "line_start": 40, "line_end": 42}],
    })  # fmt: skip
    golden = [CaseOutcome("case_one", ["RULE-001"])]
    verdict = compute("PayOrder", [checks.tests_ran(7, 0, True), checks.same_behaviour(golden, [])], ["a note"])
    pack = build_proof_pack(verdict, golden, None, trace_rules([rule], golden, {}), "<testsuite/>")
    pack_key = f"tenants/{tenant_id}/projects/{project_id}/runs/{run_id}/verification/PayOrder/proof-pack.zip"
    await store.put(pack_key, io.BytesIO(pack), len(pack), "application/zip")
    async with owner.begin() as conn:
        await conn.execute(
            text("INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, "
                 "size_bytes, sha256, content_type) VALUES (:i, :t, :p, 'source_archive', 'code.zip', 1, 'accepted', "
                 ":k, :s, :h, 'application/zip')"),
            {"i": input_id, "t": tenant_id, "p": project_id, "k": input_key(tenant_id, project_id, input_id),
             "s": len(data), "h": hashlib.sha256(data).hexdigest()},
        )  # fmt: skip
        await conn.execute(
            text("INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, sha256, "
                 "size_bytes, rules) VALUES (:t, :p, :r, 'domain', 'src/main/java/demo/PayOrderService.java', :k, :h, "
                 ":s, CAST('[\"RULE-001\"]' AS jsonb))"),
            {"t": tenant_id, "p": project_id, "r": run_id, "k": java_key, "h": hashlib.sha256(java).hexdigest(),
             "s": len(java)},
        )  # fmt: skip
        verdict_id: uuid.UUID = (
            await conn.execute(
                text("INSERT INTO verdict (tenant_id, project_id, run_id, module, verdict, checks, not_proven, "
                     "proof_pack_key) VALUES (:t, :p, :r, 'PayOrder', :v, CAST(:c AS jsonb), CAST(:n AS jsonb), :k) "
                     "RETURNING id"),
                {"t": tenant_id, "p": project_id, "r": run_id, "v": verdict.verdict, "k": pack_key,
                 "c": json.dumps([{"key": c.key, "title": c.title, "status": c.status, "detail": c.detail}
                                  for c in verdict.checks]),
                 "n": json.dumps(verdict.not_proven)},
            )
        ).scalar_one()  # fmt: skip
    return verdict_id


BMS_SOURCE = Path(__file__).resolve().parents[4] / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
PROTOTYPE_TSX = "export default function Prototype() { return null }\n"


async def seed_screens(owner: AsyncEngine, store: Any, tenant_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    """The screens of the fictitious BMS application, the NexTI base design system and version 1 of the prototype
    of SCR-PAGOORD with its page in the object store. Returns the prototype id."""
    import io

    from nexti_adapter_bms import BmsAdapter
    from nexti_core.adapters import SourceFile
    from nexti_ui import PrototypeBuild, base_tokens, page

    screens = BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS_SOURCE.read_text(encoding="utf-8"))])
    document = page(PrototypeBuild(True, js="document.body.dataset.ready = '1'", css=".nx-root{}"), "PAGOORD")
    source_key = f"tenants/{tenant_id}/projects/{project_id}/prototypes/SCR-PAGOORD/v1/Screen.tsx"
    page_key = f"tenants/{tenant_id}/projects/{project_id}/prototypes/SCR-PAGOORD/v1/index.html"
    for key, content, media in ((source_key, PROTOTYPE_TSX, "text/plain"), (page_key, document, "text/html")):
        data = content.encode("utf-8")
        await store.put(key, io.BytesIO(data), len(data), media)
    async with owner.begin() as conn:
        for screen in screens:
            await conn.execute(
                text("INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data) "
                     "VALUES (:t, :p, 'screen', :k, 1, 'review', CAST(:d AS jsonb))"),
                {"t": tenant_id, "p": project_id, "k": screen.id, "d": screen.model_dump_json()},
            )  # fmt: skip
        await conn.execute(
            text("INSERT INTO design_system (tenant_id, project_id, version, source, tokens) "
                 "VALUES (:t, :p, 1, 'nexti-base', CAST(:k AS jsonb))"),
            {"t": tenant_id, "p": project_id, "k": json.dumps(base_tokens())},
        )  # fmt: skip
        prototype_id: uuid.UUID = (
            await conn.execute(
                text("INSERT INTO prototype (tenant_id, project_id, screen_key, version, origin, source_key, "
                     "bundle_key, bundle_sha256) VALUES (:t, :p, 'SCR-PAGOORD', 1, 'generated', :sk, :bk, :h) "
                     "RETURNING id"),
                {"t": tenant_id, "p": project_id, "sk": source_key, "bk": page_key,
                 "h": __import__("hashlib").sha256(document.encode("utf-8")).hexdigest()},
            )
        ).scalar_one()  # fmt: skip
    return prototype_id


async def seed_proposal(owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    """A change asked through the chat of SCR-PAGOORD and the designer's proposal to add a field (EMAIL) the screen
    spec does not have; the proposed prototype points to the stored version 1. Returns the proposal message id."""
    prefix = f"tenants/{tenant_id}/projects/{project_id}/prototypes/SCR-PAGOORD/v1"
    proposal = {"fields": ["EMAIL"], "change": "Agregar el correo del cliente", "source_key": f"{prefix}/Screen.tsx",
                "bundle_key": f"{prefix}/index.html", "bundle_sha256": "0" * 64}  # fmt: skip
    async with owner.begin() as conn:
        await conn.execute(
            text("INSERT INTO ui_chat_message (tenant_id, project_id, screen_key, role, body, status) "
                 "VALUES (:t, :p, 'SCR-PAGOORD', 'user', 'Agregar el correo del cliente', 'done')"),
            {"t": tenant_id, "p": project_id},
        )  # fmt: skip
        message_id: uuid.UUID = (
            await conn.execute(
                text("INSERT INTO ui_chat_message (tenant_id, project_id, screen_key, role, body, status, proposal) "
                     "VALUES (:t, :p, 'SCR-PAGOORD', 'agent', 'Adds EMAIL', 'proposal', CAST(:pr AS jsonb)) "
                     "RETURNING id"),
                {"t": tenant_id, "p": project_id, "pr": json.dumps(proposal)},
            )
        ).scalar_one()  # fmt: skip
    return message_id
