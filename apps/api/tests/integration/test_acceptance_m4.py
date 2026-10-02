"""Acceptance of M4 (plan section 4) with the fictitious application: the whole modernization pipeline, from the
uploaded stored procedure to a verdict computed by code. Rules are extracted and reviewed by agents, stories derived,
C1 approved through the API, the design (C3) proposed, the legacy characterized in Sybase, Java generated and
compiled in the sandbox, then independently verified; the extracted rules are evaluated against the reference spec.

CI replays what real models answered and what Sybase did (ADR-0012), with the real Java sandbox. Recording is on
demand, with a budget: NEXTI_RECORD_M4=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) and a live Sybase ASE
(image datagrip/sybase:16.0), and writes the recordings next to this test. Skipped without Docker or the Java image,
and in replay when nothing has been recorded yet."""

import hashlib
import io
import json
import os
import subprocess
import uuid
import zipfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_adapter_sybase.ase import AseRunner, RecordedRunner
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import (
    Budget,
    ModelAssignment,
    ModelFamily,
    ModelOffering,
    ModelProfile,
    ModelVersion,
    PriceVersion,
    ProviderConnection,
)
from nexti_core.object_store import ObjectStore, ObjectStoreConfig, input_key
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_core.spec.model import Rule
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_spring_boot import IMAGE
from nexti_sandbox import DockerSandbox
from nexti_verification.evaluation import evaluate, load_reference
from nexti_worker.project import WorkerProjectPort
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World, compose_env
from .run_support import NO_FRONTEND, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_runs_api import grant, sign_in

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden"
RECORDINGS = Path(__file__).parent / "recordings" / "m4"
MODEL = "anthropic/claude-sonnet-5.5"  # recorded with this model; its OpenRouter price is $2 / $10 per million tokens
BUDGET_USD = Decimal("5.00")
FULL_TEAM = {
    "legacy-analyst": "1.5.0",
    "rules-extractor": "2.2.0",
    "rules-verifier": "1.3.0",
    "solution-architect": "1.3.0",
    "test-engineer": "1.6.0",
    "backend-dev": "1.5.0",
    "equivalence-validator": "1.4.0",
}
RECORD = os.environ.get("NEXTI_RECORD_M4") == "1"


def _api_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY_FOR_TESTS"):
        return key
    try:
        return compose_env("OPENROUTER_API_KEY_FOR_TESTS")
    except (RuntimeError, OSError):
        return ""


def _image(name: str) -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", name], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def ready() -> None:
    if not _image(IMAGE):
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    if RECORD and not (_api_key() and _image("datagrip/sybase:16.0")):
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS and the image datagrip/sybase:16.0")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M4=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def object_store() -> ObjectStore:
    return ObjectStore(
        ObjectStoreConfig(
            SETTINGS.object_store_url,
            SETTINGS.object_store_access_key,
            SETTINGS.object_store_secret_key.get_secret_value(),
            SETTINGS.object_store_bucket,
        )
    )


async def model_for(
    owner: AsyncEngine, gateway: GatewayService, tenant_id: uuid.UUID, project_id: uuid.UUID, *, live: bool = RECORD
) -> str:
    """The recorded model for this project only: catalog row, an OpenRouter connection with its key in OpenBao (a
    placeholder when replaying: nothing leaves the machine), a profile and a project assignment. Returns the path."""
    async with owner.begin() as conn:
        version = (await conn.execute(select(ModelVersion.id).where(ModelVersion.provider_slug == MODEL))).scalar()
        if version is None:
            family = await conn.execute(
                insert(ModelFamily).values(key=f"m4-{uuid.uuid4().hex[:6]}", name="Anthropic").returning(ModelFamily.id)
            )
            version = (
                await conn.execute(
                    insert(ModelVersion)
                    .values(
                        family_id=family.scalar_one(),
                        provider_slug=MODEL,
                        canonical_slug=MODEL,
                        name="Claude Sonnet 5.5",
                    )
                    .returning(ModelVersion.id)
                )
            ).scalar_one()
        # The real upstream provider: the gateway pins OpenRouter's routing to the offering's provider.
        offering = (
            await conn.execute(
                select(ModelOffering.id).where(
                    ModelOffering.version_id == version, ModelOffering.upstream_provider == "anthropic"
                )
            )
        ).scalar()
        if offering is None:
            offering = (
                await conn.execute(
                    insert(ModelOffering)
                    .values(version_id=version, provider="openrouter", upstream_provider="anthropic", zdr=False)
                    .returning(ModelOffering.id)
                )
            ).scalar_one()
            await conn.execute(
                insert(PriceVersion).values(
                    offering_id=offering, input_per_mtok=Decimal("2"), output_per_mtok=Decimal("10"), source="manual"
                )
            )
        connection = uuid.uuid4()
        path = await gateway.store_credential(tenant_id, connection, _api_key() if live else "replay-only")
        await conn.execute(
            insert(ProviderConnection).values(
                id=connection,
                tenant_id=tenant_id,
                provider="openrouter",
                name=f"M4 {connection.hex[:6]}",
                vault_path=path,
            )
        )
        profile = (
            await conn.execute(
                insert(ModelProfile)
                .values(
                    tenant_id=tenant_id,
                    name=f"M4 acceptance {connection.hex[:6]}",
                    connection_id=connection,
                    offering_id=offering,
                    max_output_tokens=16000,
                    timeout_seconds=300,
                    max_retries=2,
                )
                .returning(ModelProfile.id)
            )
        ).scalar_one()
        await conn.execute(
            insert(ModelAssignment).values(tenant_id=tenant_id, project_id=project_id, profile_id=profile)
        )
    return path


async def spending_cap(
    owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, budget: Decimal = BUDGET_USD
) -> uuid.UUID:
    """Recording spends real money: the gateway stops every call once this run has spent BUDGET_USD. The cap is a
    tenant budget (the gateway checks every budget that applies to a call) set to what the tenant spent so far plus
    the budget; the project budget only alerts, so the preflight's estimate from the configuration (9.4), meant
    for whole projects, does not stop a run of one small procedure."""
    async with owner.begin() as conn:
        spent: Decimal = (
            await conn.execute(
                text("SELECT COALESCE(sum(cost_usd), 0) FROM usage_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        await conn.execute(
            insert(Budget).values(
                tenant_id=tenant_id,
                project_id=project_id,
                period="total",
                amount_usd=Decimal("100000"),
                hard_stop=False,
            )
        )
        cap: uuid.UUID = (
            await conn.execute(
                insert(Budget)
                .values(
                    tenant_id=tenant_id,
                    project_id=None,
                    period="total",
                    amount_usd=Decimal(spent) + budget,
                    hard_stop=True,
                )
                .returning(Budget.id)
            )
        ).scalar_one()
    return cap


async def upload_source(
    owner: AsyncEngine, store: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID,
    files: dict[str, bytes] | None = None,
) -> None:  # fmt: skip
    sources = files or {"sp/sp_pago_orden.sp": (FIXTURES / "sp_pago_orden.sp").read_bytes()}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, content in sources.items():
            zipped.writestr(name, content)
    data = archive.getvalue()
    input_id = uuid.uuid4()
    key = input_key(tenant_id, project_id, input_id)
    await store.put(key, io.BytesIO(data), len(data), "application/zip")
    async with owner.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, "
                "size_bytes, sha256, content_type) VALUES (:i, :t, :p, 'source_archive', 'code.zip', 1, 'accepted', "
                ":k, :s, :h, 'application/zip')"
            ),
            {
                "i": input_id,
                "t": tenant_id,
                "p": project_id,
                "k": key,
                "s": len(data),
                "h": hashlib.sha256(data).hexdigest(),
            },
        )


async def state(owner: AsyncEngine, run_id: uuid.UUID) -> dict[str, Any]:
    (row,) = await fetch(owner, "SELECT status, waiting_reason, current_phase FROM run WHERE id = :r", r=run_id)
    return row


async def test_the_fictitious_application_reaches_a_verdict_computed_by_code(
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
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id) if RECORD else None
        legacy = RecordedRunner(RECORDINGS / "golden", mode, AseRunner() if RECORD else None)
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
                        "SELECT id, phase, context, recommended->>'key' AS option FROM question WHERE run_id = :r "
                        "AND status = 'open'",
                        r=run_id,
                    )
                    assert asked, "the run waits for a question that is not open"
                    assert not (asked[0]["phase"] == "preflight" and decided.count("questions") >= 2), asked
                    # A person takes each recommendation (high-impact questions are answered one by one, 10.4).
                    for question in asked:
                        answered = api.post(
                            f"{base}/questions/{question['id']}:answer",
                            json={"option": question["option"]},
                            headers=headers,
                        )
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
    # Hardening and delivery (M9a) close the run: the report and the release (a ZIP: no repository is linked).
    assert run["status"] == "succeeded", (
        run,
        [e for e in events if e["kind"] in ("failed", "escalated", "verificationFailed")][-5:],
    )
    assert {"C1", "C4"} <= set(decided)

    (verdict,) = await fetch(
        owner_engine,
        "SELECT module, verdict, checks, not_proven, proof_pack_key FROM verdict WHERE run_id = :r "
        "AND module NOT LIKE 'iac-%'",
        r=run_id,
    )
    assert verdict["verdict"] in ("PROVEN", "PARTLY PROVEN", "NOT PROVEN")
    assert [c["key"] for c in verdict["checks"]] == [
        "tests_ran",
        "rules_traced",
        "same_behaviour",
        "fresh_inputs",
        "canary",
        "source_intact",
    ]
    assert verdict["proof_pack_key"]

    port = WorkerProjectPort(app_engine, (await _context(app_engine, run_id, world.tenant_a)), gateway, None, None)
    rules: list[Rule] = await port.load_rules()
    evaluation = evaluate(load_reference(FIXTURES / "reference_spec.json"), rules)
    await port.save_evaluation(evaluation)
    (cost,) = await fetch(
        owner_engine,
        "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls FROM usage_ledger WHERE project_id = :p",
        p=project_id,
    )
    report = {
        "model": MODEL,
        "mode": mode,
        "verdict": verdict["verdict"],
        "checks": {c["key"]: c["status"] for c in verdict["checks"]},
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
        # The replay reproduces the recorded run: same verdict, same checks, same evaluation.
        assert (report["verdict"], report["checks"], report["evaluation"]) == (
            recorded["verdict"],
            recorded["checks"],
            recorded["evaluation"],
        )
    assert evaluation.reference_rules == 9


async def _context(engine: AsyncEngine, run_id: uuid.UUID, tenant_id: uuid.UUID) -> Any:
    from nexti_worker.loading import load_run

    return (await load_run(engine, run_id, tenant_id)).context
