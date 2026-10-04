"""Acceptance of M18 (ADR-0033) with the fictitious stored procedure: a run with the option `guided_extraction` goes
through the inventory, the classification and the rule extraction to gate C1. The procedure is small, so it is read
whole with the map of its blocks; the rules are consolidated by meaning, reviewed with the lines around their
citation and, the P0 ones, through two lenses. The rules at C1 are evaluated against the reference spec, like M4's,
so the report compares guided and plain extraction on the same procedure.

CI replays what the models answered: the calls M4 already has come from its recordings, the new ones were recorded for
M18 with a budget: NEXTI_RECORD_M18=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) for the calls nobody has an
answer for. Never record customer code here."""

import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_core.spec.model import Rule
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_sandbox import DockerSandbox
from nexti_verification.evaluation import evaluate, load_reference
from nexti_worker.project import WorkerProjectPort
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import NO_FRONTEND, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import (
    FIXTURES,
    FULL_TEAM,
    _api_key,
    _context,
    model_for,
    object_store,
    spending_cap,
    state,
    upload_source,
)
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m18"
M4 = Path(__file__).parent / "recordings" / "m4"
BUDGET_USD = Decimal("2.00")
RECORD = os.environ.get("NEXTI_RECORD_M18") == "1"


@pytest.fixture(scope="module")
def ready() -> None:
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M18=1")
    if not any((M4 / "models").glob("*.json")):
        pytest.skip("the M4 recordings are missing")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_guided_extraction_reads_the_procedure_whole_and_reaches_c1_with_checked_rules(
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
    version = await make_config(owner_engine, world.tenant_a, project_id, team=FULL_TEAM, target=NO_FRONTEND)
    await upload_source(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline",
                            options={"guided_extraction": True})  # fmt: skip
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []
    at_c1 = False

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode),
                                 shared_cassettes=(M4 / "models",))  # fmt: skip
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
            legacy=lambda: RecordedRunner(M4 / "golden", "replay", None),
        )
        try:
            for _ in range(20):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    pending = "SELECT gate FROM gate WHERE run_id = :r AND status = 'pending' ORDER BY gate LIMIT 1"
                    (gate,) = await fetch(owner_engine, pending, r=run_id)
                    at_c1 = gate["gate"] == "C1"
                    break  # C1: the business review of the rules; nothing after it changes in M18
                if run["waiting_reason"] != "question":
                    break
                asked = await fetch(owner_engine, "SELECT id, recommended->>'key' AS option FROM question "
                                                  "WHERE run_id = :r AND status = 'open'", r=run_id)  # fmt: skip
                assert asked, "the run waits for a question that is not open"
                for question in asked:  # a person takes each recommendation
                    answered = api.post(f"{base}/questions/{question['id']}:answer",
                                        json={"option": question["option"]}, headers=headers)  # fmt: skip
                    assert answered.status_code == 200, answered.text
                decided.append("questions")
            port = WorkerProjectPort(app_engine, (await _context(app_engine, run_id, world.tenant_a)), gateway, None,
                                     None)  # fmt: skip
            rules: list[Rule] = await port.load_rules()
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                async with owner_engine.begin() as conn:
                    await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})
            async with owner_engine.begin() as conn:  # the run ends here: it does not wait at C1 for ever
                await conn.execute(text("UPDATE run SET status = 'cancelled' WHERE id = :r"), {"r": run_id})

    events = await fetch(owner_engine, "SELECT phase, kind, message FROM activity_event WHERE run_id = :r ORDER BY id",
                         r=run_id)  # fmt: skip
    assert at_c1, [e for e in events if e["kind"] in ("failed", "escalated", "verificationFailed")][-5:]

    # One extraction of the whole procedure (172 lines), one consolidation, rules citing lines with code.
    invoked = await fetch(owner_engine, "SELECT agent_key, shard, cost_usd FROM agent_invocation WHERE run_id = :r "
                                        "AND phase = 'ruleExtraction'", r=run_id)  # fmt: skip
    shards = sorted({str(i["shard"]) for i in invoked if i["shard"]})
    assert "dbo.sp_pago_orden#whole" in shards, shards
    assert "consolidate" in shards, shards
    source = (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8").splitlines()
    assert rules
    for rule in rules:
        for ref in rule.sources:
            assert ref.line_end <= len(source), rule.id
            assert "".join(source[ref.line_start - 1 : ref.line_end]).strip(), rule.id
    evaluation = evaluate(load_reference(FIXTURES / "reference_spec.json"), rules)
    assert evaluation.reference_rules == 9

    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                                        "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    m4 = json.loads((M4 / "report.json").read_text(encoding="utf-8"))["evaluation"]
    report = {
        "mode": mode,
        "rules": len(rules),
        "p0": sum(1 for r in rules if r.priority == "P0"),
        "extraction_shards": shards,
        "evaluation": {k: v for k, v in evaluation.metrics().items() if k != "matched"},
        # The same procedure extracted without the option (M4's recorded run), for comparison.
        "plain_extraction": {k: m4.get(k) for k in ("found_rules", "omissions", "omissions_p0", "hallucinations")},
        "extraction_cost_usd": str(sum((Decimal(i["cost_usd"] or 0) for i in invoked), Decimal(0))),
        "model_calls": cost["calls"],
        "cost_usd": str(cost["usd"]),
        "decisions": decided,
    }
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        keys = ("rules", "p0", "extraction_shards", "evaluation")
        assert {k: report[k] for k in keys} == {k: recorded[k] for k in keys}
