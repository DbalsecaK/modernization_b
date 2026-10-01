"""Acceptance of M8b (plan, ADR-0021): the fictitious application of M4 migrated to Spring Boot on Oracle, with its
infrastructure for AWS. It is the whole M4 pipeline with the target's database and cloud changed: inventory,
rules, C1, design and characterization exactly as in M4 (those answers come from M4's recordings, since the target
does not change them); then the Spring Boot pack on Oracle generates the project, each piece built and tested in the
Oracle sandbox (Oracle Database Free 23ai), the deployment pack writes the OpenTofu for AWS, and the independent
verification replays the golden master and the fresh inputs on Oracle, runs the canary, checks the legacy is intact
and gives the IaC its own verdict (`tofu validate` without credentials and the fitness functions).

CI replays what real models answered (ADR-0012) with the real sandboxes; the legacy's behaviour is M4's recorded
golden master. Recording is on demand, with a budget: NEXTI_RECORD_M8B=1 calls OpenRouter
(OPENROUTER_API_KEY_FOR_TESTS) for what M4 did not record and writes it next to this test. Skipped without Docker or
the images, and in replay when nothing has been recorded yet."""

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

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_iac import IMAGE as IAC_IMAGE
from nexti_pack_spring_boot.oracle import IMAGE
from nexti_sandbox import DockerSandbox
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import TARGET, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import FULL_TEAM, _api_key, _image, model_for, object_store, spending_cap, state, upload_source
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m8b"
M4 = Path(__file__).parent / "recordings" / "m4"
MODEL = "anthropic/claude-sonnet-5.5"  # the model of test_acceptance_m4.model_for
BUDGET_USD = Decimal("2.00")  # approved for the recording of M8b
TARGET_ORACLE = {**TARGET, "backend": "spring-boot", "frontend": "none", "database": "oracle", "cloud": "aws"}
RECORD = os.environ.get("NEXTI_RECORD_M8B") == "1"
CHECKS = ["tests_ran", "rules_traced", "same_behaviour", "fresh_inputs", "canary", "source_intact"]


@pytest.fixture(scope="module")
def ready() -> None:
    for image in (IMAGE, IAC_IMAGE):
        if not _image(image):
            pytest.skip(f"Docker or the image {image} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M8B=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_the_fictitious_application_reaches_a_verdict_on_oracle_with_its_aws_infrastructure(
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
    version = await make_config(owner_engine, world.tenant_a, project_id, team=FULL_TEAM, target=TARGET_ORACLE)
    await upload_source(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []
    golden = RecordedRunner(M4 / "golden", "replay", None)

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode),
                                 shared_cassettes=(M4 / "models",))  # fmt: skip
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        runtime = Runtime(
            engine=app_engine, dsn=psycopg_dsn(databases.app_url), sandbox=FakeSandbox(), http=http, objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway, sandboxes=lambda image: DockerSandbox(image=image), legacy=lambda: golden,
        )  # fmt: skip
        try:
            for _ in range(30):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    (gate,) = await fetch(owner_engine, "SELECT gate FROM gate WHERE run_id = :r "
                                          "AND status = 'pending' ORDER BY gate LIMIT 1", r=run_id)  # fmt: skip
                    approved = api.post(f"{base}/runs/{run_id}/gates/{gate['gate']}:approve", json={}, headers=headers)
                    assert approved.status_code == 200, approved.text
                    decided.append(gate["gate"])
                elif run["waiting_reason"] == "question":
                    asked = await fetch(owner_engine, "SELECT id, recommended->>'key' AS option FROM question "
                                        "WHERE run_id = :r AND status = 'open'", r=run_id)  # fmt: skip
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

    run = await state(owner_engine, run_id)
    events = await fetch(owner_engine, "SELECT kind, message FROM activity_event WHERE run_id = :r ORDER BY id",
                         r=run_id)  # fmt: skip
    assert (run["status"], run["waiting_reason"], run["current_phase"]) == ("waiting", "phaseUnavailable",
                                                                           "hardening"), (
        run, [e for e in events if e["kind"] in ("failed", "escalated", "verificationFailed")][-5:])  # fmt: skip
    assert {"C1", "C4"} <= set(decided)
    rows = await fetch(owner_engine, "SELECT module, verdict, checks, proof_pack_key FROM verdict WHERE run_id = :r",
                       r=run_id)  # fmt: skip
    verdicts = {v["module"]: v for v in rows}
    verdict, iac = verdicts["PayOrder"], verdicts["iac-aws"]
    files = {f["path"] for f in await fetch(owner_engine, "SELECT path FROM generated_artifact WHERE run_id = :r",
                                            r=run_id)}  # fmt: skip
    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                          "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    report: dict[str, Any] = {
        "model": MODEL, "mode": mode, "verdict": verdict["verdict"],
        "checks": {c["key"]: c["status"] for c in verdict["checks"]},
        "details": {c["key"]: c["detail"] for c in verdict["checks"]},
        "iac": {"verdict": iac["verdict"], "checks": {c["key"]: c["status"] for c in iac["checks"]}},
        "model_calls": cost["calls"], "cost_usd": str(cost["usd"]), "decisions": decided,
    }  # fmt: skip
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        assert (report["verdict"], report["checks"], report["iac"]) == (recorded["verdict"], recorded["checks"],
                                                                        recorded["iac"])  # fmt: skip
    assert [c["key"] for c in verdict["checks"]] == CHECKS
    assert verdict["proof_pack_key"]
    assert iac["proof_pack_key"]
    assert iac["verdict"] == "PROVEN", iac["checks"]
    assert set(verdicts) == {"PayOrder", "iac-aws"}
    assert {"infra/aws/main.tf", "infra/aws/variables.tf", "infra/aws/outputs.tf", "infra/aws/README.md"} <= files
    assert any(p.endswith("/JdbcAccountRepository.java") for p in files)
