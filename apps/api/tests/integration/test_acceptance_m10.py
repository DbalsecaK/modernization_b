"""Acceptance of M10 (plan M10, ADR-0025) with the fictitious application: Flow 4 validates BillPay, a third party's
migration of the stored procedure, against the legacy. The rules of the legacy are extracted and reviewed (C1), the
legacy is characterized, the target is taken in with its vendor's mapping, which a person checks through the API and
approves (C2), the target's rules are read and compared, and the golden master runs on the target in the Java sandbox:
the verdict is computed by code with the IV&V checks and the report is written.

CI replays what the models answered (the legacy side shares the recordings of M4) and what Sybase did (the golden
master of M4); only the target's rules were recorded for M10, with a budget: NEXTI_RECORD_M10=1 calls OpenRouter
(OPENROUTER_API_KEY_FOR_TESTS) for the calls M4 has no answer for. Skipped without Docker or the Java images."""

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

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, input_key
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_ivv.runner import IMAGE as IVV_IMAGE
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_spring_boot import IMAGE
from nexti_sandbox import DockerSandbox
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import IVV_TARGET, NO_FRONTEND, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap, state, upload_source
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m10"
M4 = Path(__file__).parent / "recordings" / "m4"
BUDGET_USD = Decimal("2.00")
TEAM = {
    "legacy-analyst": "1.5.0",
    "rules-extractor": "2.2.0",
    "rules-verifier": "1.3.0",
    "test-engineer": "1.6.0",
    "equivalence-validator": "1.4.0",
}
RECORD = os.environ.get("NEXTI_RECORD_M10") == "1"
CHECKS = ["target_runs", "contract_mapped", "same_behaviour", "fresh_inputs", "rules_covered", "source_intact"]


@pytest.fixture(scope="module")
def ready() -> None:
    for image in (IMAGE, IVV_IMAGE):
        if not _image(image):
            pytest.skip(f"Docker or the image {image} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M10=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def upload_target(owner: AsyncEngine, store: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """BillPay as its vendor delivers it: the sources and the vendor's ivv-mapping.yaml, in one archive."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in sorted(p for p in IVV_TARGET.rglob("*") if p.is_file()):
            zipped.writestr(path.relative_to(IVV_TARGET).as_posix(), path.read_bytes())
    data = archive.getvalue()
    input_id = uuid.uuid4()
    key = input_key(tenant_id, project_id, input_id)
    await store.put(key, io.BytesIO(data), len(data), "application/zip")
    async with owner.begin() as conn:
        await conn.execute(
            text("INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, "
                 "size_bytes, sha256, content_type) VALUES (:i, :t, :p, 'target_archive', 'billpay.zip', 1, "
                 "'accepted', :k, :s, :h, 'application/zip')"),
            {"i": input_id, "t": tenant_id, "p": project_id, "k": key, "s": len(data),
             "h": hashlib.sha256(data).hexdigest()},
        )  # fmt: skip


async def test_a_third_party_target_is_validated_against_the_legacy(
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
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE project SET flow = 'independentValidation' WHERE id = :p"), {"p": project_id})
    version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM, target=NO_FRONTEND)
    await upload_source(owner_engine, store, world.tenant_a, project_id)
    await upload_target(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode),
                                 shared_cassettes=(M4 / "models",))  # fmt: skip
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        legacy = RecordedRunner(M4 / "golden", "replay", None)
        runtime = Runtime(
            engine=app_engine,
            dsn=psycopg_dsn(databases.app_url),
            sandbox=FakeSandbox(),
            http=http,
            objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway,
            sandboxes=lambda image: DockerSandbox(image=image),
            legacy=lambda: legacy,
        )
        try:
            for _ in range(30):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    pending = "SELECT gate FROM gate WHERE run_id = :r AND status = 'pending' ORDER BY gate LIMIT 1"
                    (gate,) = await fetch(owner_engine, pending, r=run_id)
                    if gate["gate"] == "C1":
                        check = api.get(f"{base}/c1-check", headers=headers).json()
                        assert check["canApprove"], check["blockers"]
                    if gate["gate"] == "C2":  # the approver checks the mapping first
                        ivv = api.get(f"{base}/ivv", headers=headers).json()
                        assert ivv["inventory"]["stack"] == "spring-boot"
                        assert ivv["problems"] == [], ivv["problems"]
                    approved = api.post(f"{base}/runs/{run_id}/gates/{gate['gate']}:approve", json={}, headers=headers)
                    assert approved.status_code == 200, approved.text
                    decided.append(gate["gate"])
                elif run["waiting_reason"] == "question":
                    asked = await fetch(owner_engine, "SELECT id, recommended->>'key' AS option FROM question "
                                                      "WHERE run_id = :r AND status = 'open'", r=run_id)  # fmt: skip
                    assert asked, "the run waits for a question that is not open"
                    for question in asked:
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

    events = await fetch(owner_engine, "SELECT phase, kind, message FROM activity_event WHERE run_id = :r ORDER BY id",
                         r=run_id)  # fmt: skip
    run = await state(owner_engine, run_id)
    assert run["status"] == "succeeded", (
        run,
        [e for e in events if e["kind"] in ("failed", "escalated", "verificationFailed")][-5:],
    )
    assert [d for d in decided if d != "questions"] == ["C1", "C2", "C4"]
    (verdict,) = await fetch(owner_engine, "SELECT module, verdict, checks, proof_pack_key FROM verdict "
                                           "WHERE run_id = :r", r=run_id)  # fmt: skip
    assert verdict["module"] == "ivv-sp_pago_orden"
    assert [c["key"] for c in verdict["checks"]] == CHECKS
    statuses = {c["key"]: c["status"] for c in verdict["checks"]}
    # BillPay is a faithful migration: every golden case and every fresh input is reproduced (ADR-0025).
    assert (verdict["verdict"], statuses) == ("PROVEN", dict.fromkeys(CHECKS, "passed")), verdict["checks"]
    assert verdict["proof_pack_key"]
    ivv = api.get(f"{base}/ivv", headers=headers).json()
    assert f"**{verdict['verdict']}**" in ivv["report"]
    assert ivv["comparison"] is not None
    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                                        "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    report = {
        "mode": mode,
        "verdict": verdict["verdict"],
        "checks": statuses,
        "details": {c["key"]: c["detail"] for c in verdict["checks"]},
        "rules_compared": {k: len(v) for k, v in ivv["comparison"].items()},
        "model_calls": cost["calls"],
        "cost_usd": str(cost["usd"]),
        "decisions": decided,
    }
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        assert (report["verdict"], report["checks"]) == (recorded["verdict"], recorded["checks"])
