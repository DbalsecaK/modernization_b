"""Acceptance of M6 (plan section 3) with the fictitious COBOL/CICS application: the whole modernization pipeline
from the uploaded archive (programs, copybooks, CICS definitions, BMS maps and the traces exported from the test
region) to a verdict computed by code. The COBOL adapter inventories Transaction -> Program -> Map; rules are
extracted and reviewed by agents; the UI phase designs the screens; C1 is approved through the API; the design (C3)
is proposed; the golden master comes from the recorded traces (the legacy does not run here, ADR-0015); Java is
generated and compiled in the sandbox and independently verified. The verdict cannot pass PARTLY PROVEN, and the
extracted rules are measured against the CICS reference spec.

CI replays what real models answered (ADR-0012) with the real Java and web sandboxes. Recording is on demand, with a
budget: NEXTI_RECORD_M6=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) and writes the recordings next to this
test. Skipped without Docker or the images, and in replay when nothing has been recorded yet."""

import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_core.spec.model import Rule
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_spring_boot import IMAGE as JAVA_IMAGE
from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE as WEB_IMAGE
from nexti_verification.evaluation import evaluate, load_reference
from nexti_worker.project import WorkerProjectPort
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import CICS_FIXTURES, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import (
    FULL_TEAM,
    _api_key,
    _context,
    _image,
    model_for,
    object_store,
    spending_cap,
    state,
    upload_source,
)
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m6"
MODEL = "anthropic/claude-sonnet-5.5"  # the model of test_acceptance_m4.model_for
BUDGET_USD = Decimal("4.00")  # of the 10 USD the approver gave M6, M6b and M6c together
TEAM = {**FULL_TEAM, "ux-designer": "0.8.0"}
RECORD = os.environ.get("NEXTI_RECORD_M6") == "1"
SUFFIXES = (".cbl", ".cpy", ".csd", ".bms", ".json")


def sources() -> dict[str, bytes]:
    return {p.relative_to(CICS_FIXTURES).as_posix(): p.read_bytes() for p in sorted(CICS_FIXTURES.rglob("*"))
            if p.suffix in SUFFIXES and not p.name.startswith("reference_")}  # fmt: skip


@pytest.fixture(scope="module")
def ready() -> None:
    for image in (JAVA_IMAGE, WEB_IMAGE):
        if not _image(image):
            pytest.skip(f"Docker or the image {image} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M6=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_the_fictitious_cics_application_reaches_a_verdict_capped_at_partly_proven(
    ready: None,
    api: TestClient,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    fga: OpenFga,
    world: World,
    databases: Databases,
) -> None:
    mode: Literal["record", "replay"] = "record" if RECORD else "replay"
    store = object_store()
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM)
    await upload_source(owner_engine, store, world.tenant_a, project_id, sources())
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        runtime = Runtime(
            engine=app_engine,
            dsn=psycopg_dsn(databases.app_url),
            sandbox=FakeSandbox(),
            http=http,
            objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway,
            sandboxes=lambda image: DockerSandbox(image=image),
            legacy=None,  # the archive has traces: the worker takes the golden master from them
        )
        try:
            for _ in range(30):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    (gate,) = await fetch(
                        owner_engine,
                        "SELECT gate FROM gate WHERE run_id = :r AND status = 'pending' ORDER BY gate LIMIT 1",
                        r=run_id,
                    )
                    if gate["gate"] == "C1":
                        check = api.get(f"{base}/c1-check", headers=headers).json()
                        assert check["canApprove"], check["blockers"]
                    approved = api.post(f"{base}/runs/{run_id}/gates/{gate['gate']}:approve", json={}, headers=headers)
                    assert approved.status_code == 200, approved.text
                    decided.append(gate["gate"])
                elif run["waiting_reason"] == "question":
                    asked = await fetch(
                        owner_engine,
                        "SELECT id, phase, recommended->>'key' AS option FROM question WHERE run_id = :r "
                        "AND status = 'open'",
                        r=run_id,
                    )
                    assert asked, "the run waits for a question that is not open"
                    for question in asked:  # a person takes each recommendation
                        answered = api.post(f"{base}/questions/{question['id']}:answer",
                                            json={"option": question["option"]}, headers=headers)  # fmt: skip
                        assert answered.status_code == 200, answered.text
                    decided.append("questions")
                else:
                    break  # a phase this version does not have yet (hardening, delivery)
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                async with owner_engine.begin() as conn:
                    await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})

    events = await fetch(
        owner_engine, "SELECT phase, kind, message FROM activity_event WHERE run_id = :r ORDER BY id", r=run_id
    )
    run = await state(owner_engine, run_id)
    assert (run["status"], run["waiting_reason"], run["current_phase"]) == (
        "waiting",
        "phaseUnavailable",
        "hardening",
    ), (run, [e for e in events if e["kind"] in ("failed", "escalated", "verificationFailed")][-5:])
    assert {"C1", "C4"} <= set(decided)

    (inventory,) = [e for e in events if e["phase"] == "inventory" and e["kind"] == "completed"][-1:]
    assert "2 transaction(s), 3 program(s)" in inventory["message"]
    (master,) = await fetch(owner_engine, "SELECT path FROM generated_artifact WHERE run_id = :r "
                            "AND path = 'characterization/golden_master.json'", r=run_id)  # fmt: skip
    assert master
    (verdict,) = await fetch(
        owner_engine,
        "SELECT module, verdict, checks, not_proven, proof_pack_key FROM verdict WHERE run_id = :r",
        r=run_id,
    )
    checks = {c["key"]: c["status"] for c in verdict["checks"]}
    assert verdict["verdict"] == "PARTLY PROVEN", (verdict["verdict"], verdict["checks"])
    assert checks["fresh_inputs"] == "not_checked"
    assert any("recorded traces" in note for note in verdict["not_proven"])
    assert verdict["proof_pack_key"]

    port = WorkerProjectPort(app_engine, (await _context(app_engine, run_id, world.tenant_a)), gateway, None, None)
    rules: list[Rule] = await port.load_rules()
    evaluation = evaluate(load_reference(CICS_FIXTURES / "reference_spec.json"), rules)
    await port.save_evaluation(evaluation)
    (cost,) = await fetch(
        owner_engine,
        "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls FROM usage_ledger WHERE project_id = :p",
        p=project_id,
    )
    report: dict[str, Any] = {
        "model": MODEL,
        "mode": mode,
        "verdict": verdict["verdict"],
        "checks": checks,
        "details": {c["key"]: c["detail"] for c in verdict["checks"]},
        "not_proven": verdict["not_proven"],
        "evaluation": {k: v for k, v in evaluation.metrics().items() if k != "matched"},
        "model_calls": cost["calls"],
        "cost_usd": str(cost["usd"]),
        "decisions": decided,
    }
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        assert (report["verdict"], report["checks"], report["evaluation"]) == (
            recorded["verdict"],
            recorded["checks"],
            recorded["evaluation"],
        )
    assert evaluation.reference_rules == 10
