"""The bug cycle (spec 7.6, ADR-0019): for a bug the verdict opened, the developer agent proposes a correction of the
service in the pack's sandbox, code re-runs the tests, and the cycle always ends with a person: a correction that
passes is kept as a draft and the bug goes to review; one that does not after the project's maximum of iterations is
escalated. Nothing is applied to the generated code and no verdict changes here: the next verification decides."""

import hashlib
import io
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_agents import prompt
from nexti_core.audit import AuditEvent, record
from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore
from nexti_core.spec.design import Design
from nexti_integrations.backlog import BacklogTracker, Created
from nexti_model_gateway.gateway import CallContext
from nexti_model_gateway.service import GatewayService
from nexti_orchestration.packs import backend_pack
from nexti_sandbox import Sandbox

DEVELOPER = "backend-dev"
ACTOR = "bug-cycle"


def _db(engine: AsyncEngine, tenant_id: uuid.UUID) -> Any:
    return scoped_connection(engine, DbScope(tenant_id=tenant_id))


async def _project(engine: AsyncEngine, objects: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID
                   ) -> tuple[dict[str, Any], Design | None, dict[str, str], int]:  # fmt: skip
    """The project's target and iteration limit, its design and its newest generated files."""
    async with _db(engine, tenant_id) as conn:
        config = (
            await conn.execute(text("SELECT target, max_iterations FROM project_config WHERE project_id = :p "
                                    "ORDER BY version DESC LIMIT 1"), {"p": project_id})
        ).mappings().first()  # fmt: skip
        rows = (
            await conn.execute(
                text("SELECT DISTINCT ON (path) path, object_key FROM generated_artifact WHERE project_id = :p "
                     "AND path NOT LIKE 'characterization/%' AND path NOT LIKE 'frontend/%' "
                     "AND path NOT LIKE 'inputs/%' ORDER BY path, created_at DESC"), {"p": project_id})
        ).mappings().all()  # fmt: skip
    files = {r["path"]: b"".join(await objects.read(r["object_key"])).decode("utf-8") for r in rows}
    design_json = files.pop("design/design.json", None)
    design = Design.model_validate_json(design_json) if design_json else None
    target = dict(config["target"]) if config else {}
    return target, design, files, int(config["max_iterations"]) if config else 3


async def fix_bugs(
    engine: AsyncEngine, objects: ObjectStore, gateway: GatewayService, sandboxes: Callable[[str], Sandbox],
    tracker: BacklogTracker, tenant_id: uuid.UUID, project_id: uuid.UUID, integration_id: uuid.UUID,
) -> str:  # fmt: skip
    """Runs the cycle for every open bug that has none yet; returns a summary."""
    async with _db(engine, tenant_id) as conn:
        bugs = (
            await conn.execute(
                text("SELECT l.element, l.title, l.external_id, l.external_key, l.url FROM work_item_link l "
                     "WHERE l.project_id = :p AND l.integration_id = :i AND l.kind = 'bug' AND l.state = 'open' "
                     "AND NOT EXISTS (SELECT 1 FROM bug_fix f WHERE f.project_id = l.project_id "
                     "AND f.element = l.element AND f.status IN ('proposed', 'escalated'))"),
                {"p": project_id, "i": integration_id},
            )
        ).mappings().all()  # fmt: skip
    if not bugs:
        return "no open bug to fix"
    target, design, files, max_iterations = await _project(engine, objects, tenant_id, project_id)
    pack = backend_pack(target)
    if pack is None or design is None or not files:
        return "there is no generated project to fix"
    sandbox = sandboxes(pack.image)
    outcomes = []
    for bug in bugs:
        item = Created(bug["external_id"], bug["external_key"], bug["url"])
        outcome = await _cycle(engine, objects, gateway, sandbox, pack, design, files, tracker, item, tenant_id,
                               project_id, integration_id, bug["element"], max_iterations)  # fmt: skip
        outcomes.append(outcome)
    return "; ".join(outcomes)


async def _cycle(
    engine: AsyncEngine, objects: ObjectStore, gateway: GatewayService, sandbox: Sandbox, pack: Any, design: Design,
    files: dict[str, str], tracker: BacklogTracker, item: Created, tenant_id: uuid.UUID, project_id: uuid.UUID,
    integration_id: uuid.UUID, element: str, max_iterations: int,
) -> str:  # fmt: skip
    baseline = await pack.compile_and_test(sandbox, files)
    if baseline.ok and baseline.passed:
        await _record(engine, tenant_id, project_id, element, 1, "proposed", "the tests pass in the sandbox again",
                      None)  # fmt: skip
        await _review(engine, tracker, item, tenant_id, project_id, integration_id, element,
                      f"Re-test: {baseline.passed} test(s) pass in a clean build. A person reviews it.")  # fmt: skip
        return f"{element}: passes on re-test, in review"
    failing = [t.name for t in baseline.tests if t.status == "failed"]
    use_case = next((u for u in design.use_cases if any(u.name in name for name in failing)), design.use_cases[0])
    service_path = pack.service_path(design, use_case)
    test_path = pack.test_path(design, use_case)
    base = [
        {"role": "system", "content": prompt(pack.developer_prompt)},
        {"role": "user", "content": (
            f"A bug was opened because the generated project fails its tests. Fix the application service of "
            f"{use_case.name} so every test passes, without changing what the tests expect.\n\nDesign:\n"
            f"{design.model_dump_json(indent=1)}\n\nExisting files:\n{pack.existing(files, design)}\n\n"
            f"The tests it must pass:\n{files.get(test_path, '')}\n\nCurrent service:\n{files.get(service_path, '')}"
            f"\n\nWhat fails:\n{baseline.diagnostic(3000)}")},
    ]  # fmt: skip
    feedback = ""
    for iteration in range(1, max_iterations + 1):
        messages = list(base)
        if feedback:
            messages.append({"role": "user", "content": f"The previous correction failed:\n{feedback}\nFix it."})
        ctx = CallContext(tenant_id, project_id, "validation", DEVELOPER, None, iteration)
        reply = await gateway.complete(ctx, messages)
        try:
            code = pack.code_block(reply.content)
        except ValueError as exc:
            feedback = str(exc)
            await _record(engine, tenant_id, project_id, element, iteration, "failed", feedback, None)
            continue
        candidate = {**files, service_path: code}
        candidate.update(pack.probe(design, service_path))
        build = await pack.compile_and_test(sandbox, candidate)
        if build.ok and build.passed:
            key = await _keep(objects, tenant_id, project_id, element, iteration, service_path, code)
            await _record(engine, tenant_id, project_id, element, iteration, "proposed",
                          f"{build.passed} test(s) pass with the correction of {service_path}", key)  # fmt: skip
            await _review(engine, tracker, item, tenant_id, project_id, integration_id, element,
                          f"The developer agent proposed a correction of {service_path}: {build.passed} test(s) pass "
                          "in a clean build in the sandbox. It is a draft: a person reviews it.")  # fmt: skip
            return f"{element}: correction proposed after {iteration} iteration(s), in review"
        feedback = build.diagnostic(3000)
        await _record(engine, tenant_id, project_id, element, iteration, "failed", feedback[:2000], None)
    await _record(engine, tenant_id, project_id, element, max_iterations + 1, "escalated",
                  f"no correction passed after {max_iterations} iteration(s)", None)  # fmt: skip
    await tracker.comment(item, f"The developer agent could not fix it in {max_iterations} iteration(s); the last "
                                f"result:\n\n{feedback[:1500]}\n\nEscalated to a person.")  # fmt: skip
    await _audit(engine, tenant_id, project_id, "backlog.bug_escalated", element, item.external_key)
    return f"{element}: escalated after {max_iterations} iteration(s)"


async def _keep(objects: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID, element: str, iteration: int,
                path: str, code: str) -> str:  # fmt: skip
    digest = hashlib.sha256(element.encode()).hexdigest()[:16]
    key = f"tenants/{tenant_id}/projects/{project_id}/bugfixes/{digest}/{iteration}/{path}"
    data = code.encode("utf-8")
    await objects.put(key, io.BytesIO(data), len(data), "text/plain; charset=utf-8")
    return key


async def _record(engine: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, element: str, iteration: int,
                  status: str, detail: str, files_key: str | None) -> None:  # fmt: skip
    async with _db(engine, tenant_id) as conn:
        await conn.execute(
            text("INSERT INTO bug_fix (tenant_id, project_id, element, iteration, status, detail, files_key) "
                 "VALUES (:t, :p, :e, :n, :s, :d, :k) ON CONFLICT (project_id, element, iteration) DO NOTHING"),
            {"t": tenant_id, "p": project_id, "e": element, "n": iteration, "s": status, "d": detail[:4000],
             "k": files_key},
        )  # fmt: skip


async def _review(engine: AsyncEngine, tracker: BacklogTracker, item: Created, tenant_id: uuid.UUID,
                  project_id: uuid.UUID, integration_id: uuid.UUID, element: str, note: str) -> None:  # fmt: skip
    await tracker.transition(item, "review")
    await tracker.comment(item, note)
    async with _db(engine, tenant_id) as conn:
        await conn.execute(text("UPDATE work_item_link SET state = 'review', updated_at = now() WHERE project_id = :p "
                                "AND integration_id = :i AND element = :e"),
                           {"p": project_id, "i": integration_id, "e": element})  # fmt: skip
    await _audit(engine, tenant_id, project_id, "backlog.bug_in_review", element, item.external_key)


async def _audit(engine: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, action: str, element: str,
                 key: str) -> None:  # fmt: skip
    async with _db(engine, tenant_id) as conn:
        await record(conn, AuditEvent(action=action, outcome="success", actor_kind="system", actor_label=ACTOR,
                                      target=f"project:{project_id}", tenant_id=tenant_id,
                                      details={"element": element, "external_key": key}))  # fmt: skip
