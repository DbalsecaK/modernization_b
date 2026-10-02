"""Acceptance of M11 (plan M11, ADR-0026) with the fictitious application: Flow 3 adds a query of a payment order's
status to BillPay, an existing Spring Boot application with its own tests. The worker reads the application by code
and runs its tests (the baseline), the request document becomes stories (C1), the delta is designed against the
inventory (C3), generated with every test in the Java sandbox and validated by code with EXTEND_CHECKS (C4).

CI replays what the models answered (ADR-0012). Recording is on demand, with a budget: NEXTI_RECORD_M11=1 calls
OpenRouter (OPENROUTER_API_KEY_FOR_TESTS). Skipped without Docker or the Java image, and in replay when nothing has
been recorded yet."""

import hashlib
import io
import json
import os
import uuid
import zipfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, input_key
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_spring_boot.build import IMAGE
from nexti_sandbox import DockerSandbox
from nexti_verification.verdict import EXTEND_CHECKS
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import TARGET, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap, state
from .test_runs_api import grant, sign_in

FIXTURES = Path(__file__).resolve().parents[4] / "packages/orchestration/tests/fixtures"
APP = FIXTURES / "billpay_app"
REQUEST = FIXTURES / "billpay_request" / "pedido.md"
RECORDINGS = Path(__file__).parent / "recordings" / "m11"
BUDGET_USD = Decimal("2.00")
TARGET_EXTEND = {**TARGET, "backend": "spring-boot", "frontend": "none", "database": "postgresql"}
TEAM = {
    "functional-analyst": "0.10.0",
    "rules-verifier": "1.3.0",
    "solution-architect": "1.3.0",
    "test-engineer": "1.6.0",
    "backend-dev": "1.5.0",
    "acceptance-judge": "1.0.0",
    "equivalence-validator": "1.4.0",
}
RECORD = os.environ.get("NEXTI_RECORD_M11") == "1"


@pytest.fixture(scope="module")
def ready() -> None:
    if not _image(IMAGE):
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M11=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def upload_inputs(owner: AsyncEngine, store: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """The application's code as the source archive and the request as an accepted document."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in sorted(p for p in APP.rglob("*") if p.is_file()):
            zipped.writestr(path.relative_to(APP).as_posix(), path.read_bytes())
    inputs = [("source_archive", "billpay.zip", archive.getvalue(), "application/zip"),
              ("document", "pedido.md", REQUEST.read_bytes(), "text/markdown")]  # fmt: skip
    async with owner.begin() as conn:
        for kind, name, data, content_type in inputs:
            input_id = uuid.uuid4()
            key = input_key(tenant_id, project_id, input_id)
            await store.put(key, io.BytesIO(data), len(data), content_type)
            await conn.execute(
                text("INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, "
                     "size_bytes, sha256, content_type) VALUES (:i, :t, :p, :kind, :n, 1, 'accepted', :k, :s, :h, :c)"),
                {"i": input_id, "t": tenant_id, "p": project_id, "kind": kind, "n": name, "k": key, "s": len(data),
                 "h": hashlib.sha256(data).hexdigest(), "c": content_type},
            )  # fmt: skip
        await conn.execute(text("UPDATE project SET flow = 'extendExisting' WHERE id = :p"), {"p": project_id})


async def test_a_functionality_is_added_to_an_existing_application(
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
    version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM, target=TARGET_EXTEND)
    await upload_inputs(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await grant(owner_engine, world, world.a_user, "architect", project_id)
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
            engine=app_engine, dsn=psycopg_dsn(databases.app_url), sandbox=FakeSandbox(), http=http, objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway, sandboxes=lambda image: DockerSandbox(image=image),
        )  # fmt: skip
        try:
            for _ in range(40):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    pending = "SELECT gate FROM gate WHERE run_id = :r AND status = 'pending' ORDER BY gate LIMIT 1"
                    (gate,) = await fetch(owner_engine, pending, r=run_id)
                    if gate["gate"] == "C3":  # the architect looks at the delta before approving it
                        delta = api.get(f"{base}/delta", headers=headers).json()
                        assert delta["baseline"]["passed"], delta["baseline"]
                        assert delta["design"]["changes"], delta["design"]
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
                    break
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                async with owner_engine.begin() as conn:
                    await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})

    run = await state(owner_engine, run_id)
    events = await fetch(owner_engine, "SELECT kind, message FROM activity_event WHERE run_id = :r ORDER BY id",
                         r=run_id)  # fmt: skip
    assert run["status"] == "succeeded", (run, [e for e in events if e["kind"] in ("failed", "escalated")][-5:])
    assert [d for d in decided if d != "questions"] == ["C1", "C3", "C4"]
    (verdict,) = await fetch(owner_engine, "SELECT module, verdict, checks, proof_pack_key FROM verdict "
                             "WHERE run_id = :r", r=run_id)  # fmt: skip
    assert verdict["module"] == "delta-billpayapplication"
    assert [c["key"] for c in verdict["checks"]] == [k for k, _ in EXTEND_CHECKS]
    statuses = {c["key"]: c["status"] for c in verdict["checks"]}
    for key in ("regression", "contract_kept", "fitness"):  # what worked keeps working, whatever the delta is
        assert statuses[key] == "passed", verdict["checks"]
    delta = api.get(f"{base}/delta", headers=headers).json()
    assert delta["added"]
    assert not any(p.startswith("src/test/") for p in delta["changed"])  # existing tests stay as they are
    assert f"**{verdict['verdict']}**" in delta["report"]
    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                          "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    report = {
        "mode": mode, "verdict": verdict["verdict"], "checks": statuses,
        "details": {c["key"]: c["detail"] for c in verdict["checks"]},
        "added": delta["added"], "changed": delta["changed"],
        "model_calls": cost["calls"], "cost_usd": str(cost["usd"]), "decisions": decided,
    }  # fmt: skip
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        assert (report["verdict"], report["checks"]) == (recorded["verdict"], recorded["checks"])
