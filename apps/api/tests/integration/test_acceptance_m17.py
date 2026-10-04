"""Acceptance of M17 step 3 (ADR-0032) with the fictitious stored procedure: a run with the option `deep_inventory`
goes through the inventory, the classification and the rule extraction to gate C1, and on the way the legacy analyst
describes the unit and each of its blocks and writes the architect's observations, and the analyst proposes the
business flows as scenarios whose steps point at nodes of the graph. The test stops at C1 (nothing after it changes)
and reads the insights through GET /graph/insights.

CI replays what the models answered: the calls M4 already has come from its recordings (the run without the option
asks exactly the same), only the new calls were recorded for M17, with a budget: NEXTI_RECORD_M17=1 calls OpenRouter
(OPENROUTER_API_KEY_FOR_TESTS) for the calls nobody has an answer for. Never record customer code here."""

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
from nexti_core.adapters import SourceFile
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_orchestration import insights
from nexti_orchestration.modernization import pick_adapter
from nexti_sandbox import DockerSandbox
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import NO_FRONTEND, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import (
    FIXTURES,
    FULL_TEAM,
    _api_key,
    model_for,
    object_store,
    spending_cap,
    state,
    upload_source,
)
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m17"
M4 = Path(__file__).parent / "recordings" / "m4"
BUDGET_USD = Decimal("2.00")
RECORD = os.environ.get("NEXTI_RECORD_M17") == "1"


@pytest.fixture(scope="module")
def ready() -> None:
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M17=1")
    if not any((M4 / "models").glob("*.json")):
        pytest.skip("the M4 recordings are missing")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_a_deep_inventory_describes_blocks_observes_and_proposes_scenarios_before_c1(
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
    # The team of M4, so every call M4 made is asked again word for word and answered from its recordings.
    version = await make_config(owner_engine, world.tenant_a, project_id, team=FULL_TEAM, target=NO_FRONTEND)
    await upload_source(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline",
                            options={"deep_inventory": True})  # fmt: skip
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
                    break  # C1: the business review of the rules and scenarios; nothing after it changes in M17
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

    found = api.get(f"{base}/graph/insights", headers=headers)
    assert found.status_code == 200, found.text
    deep = found.json()
    files = [SourceFile("sp/sp_pago_orden.sp", (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
    inventory = pick_adapter(files).inventory(files)
    ((unit, blocks),) = insights.units_of(inventory)
    expected = [unit.key, *(b.key for b in blocks)]
    # Every unit and block has its description, written by a model, short.
    assert sorted(deep["descriptions"]) == sorted(expected)
    assert all(0 < len(d) <= insights.MAX_DESCRIPTION for d in deep["descriptions"].values())
    assert insights.MIN_OBSERVATIONS <= len(deep["observations"]) <= insights.MAX_OBSERVATIONS
    # The scenarios: two or more, their steps on nodes of the graph and their rules among the extracted ones.
    scenarios = deep["scenarios"]
    assert len(scenarios) >= 2
    nodes = insights.graph_nodes(inventory)
    rules_sql = "SELECT DISTINCT key FROM spec_element WHERE project_id = :p AND element_type = 'rule'"
    rule_ids = {r["key"] for r in await fetch(owner_engine, rules_sql, p=project_id)}
    for scenario in scenarios:
        assert all(scenario[k] for k in ("name", "persona", "summary")), scenario
        assert len(scenario["steps"]) >= 2
        assert all(n in nodes for step in scenario["steps"] for n in step["nodes"]), scenario
        assert set(scenario["rules"]) <= rule_ids, scenario

    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                                        "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    asked = await fetch(owner_engine, "SELECT phase, agent_key, shard, cost_usd FROM agent_invocation WHERE "
                                      "run_id = :r AND (shard LIKE 'describe:%' OR shard IN "
                                      "('observations', 'scenarios'))", r=run_id)  # fmt: skip
    report = {
        "mode": mode,
        "blocks": len(blocks),
        "descriptions": len(deep["descriptions"]),
        "observations": len(deep["observations"]),
        "scenarios": [{"name": s["name"], "steps": len(s["steps"]), "rules": s["rules"]} for s in scenarios],
        "insight_invocations": sorted(f"{a['phase']}/{a['agent_key']}/{a['shard']}" for a in asked),
        "new_recordings": len(list((RECORDINGS / "models").glob("*.json"))),
        # What the new calls cost (in record mode, the real spend: M4's answers come from its recordings).
        "insights_cost_usd": str(sum((Decimal(a["cost_usd"] or 0) for a in asked), Decimal(0))),
        "model_calls": cost["calls"],
        "cost_usd": str(cost["usd"]),
        "decisions": decided,
    }
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        keys = ("blocks", "descriptions", "observations", "scenarios", "insight_invocations")
        assert {k: report[k] for k in keys} == {k: recorded[k] for k in keys}
