"""The on-demand run against a customer reference kit (plan M4 step 15, spec 21.4, ADR-0011): the pipeline extracts
and reviews the rules of the kit's legacy with real models up to gate C1, and the rules are evaluated against the
kit's reference spec (omissions, P0 omissions, hallucinations, precision errors).

Nothing of the kit enters the repository: its code is uploaded to the throwaway project of the test, the recorded
model responses and the full metrics are written inside the kit folder, and the output shows counts and rule ids.
Needs NEXTI_REFERENCE_DIR and NEXTI_REFERENCE_KIT (the kit's folder name) and OPENROUTER_API_KEY_FOR_TESTS; the
gateway stops every call once NEXTI_REFERENCE_BUDGET_USD (default 2.00) is spent. Skipped otherwise."""

import json
import os
from collections.abc import Iterator
from decimal import Decimal

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
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_verification.evaluation import evaluate
from nexti_verification.kit import kits_root, load_kit
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import FULL_TEAM, _api_key, model_for, object_store, spending_cap, state, upload_source
from .test_runs_api import grant, sign_in

ROOT = kits_root()
KIT = os.environ.get("NEXTI_REFERENCE_KIT", "")
BUDGET = Decimal(os.environ.get("NEXTI_REFERENCE_BUDGET_USD", "2.00"))
pytestmark = pytest.mark.skipif(
    not (ROOT and KIT and _api_key()),
    reason="on demand: set NEXTI_REFERENCE_DIR, NEXTI_REFERENCE_KIT and OPENROUTER_API_KEY_FOR_TESTS",
)


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_the_rules_extracted_from_the_kit_are_measured_against_its_reference(
    api: TestClient,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    fga: OpenFga,
    world: World,
    databases: Databases,
) -> None:
    assert ROOT is not None
    folder = ROOT / KIT
    kit = load_kit(folder)
    store = object_store()
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id, team=FULL_TEAM)
    await upload_source(
        owner_engine, store, world.tenant_a, project_id, {f"src/{s.path}": s.text.encode("utf-8") for s in kit.sources}
    )
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(folder / "recordings" / "models", "record"))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=True)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET)
        runtime = Runtime(
            engine=app_engine,
            dsn=psycopg_dsn(databases.app_url),
            sandbox=FakeSandbox(),
            http=http,
            objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway,
        )
        try:
            for _ in range(20):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting" or run["waiting_reason"] != "question":
                    break  # C1 is where the rules are reviewed by people: the evaluation happens here
                asked = await fetch(
                    owner_engine,
                    "SELECT id, recommended->>'key' AS option FROM question WHERE run_id = :r AND status = 'open'",
                    r=run_id,
                )
                for question in asked:
                    answered = api.post(
                        f"{base}/questions/{question['id']}:answer",
                        json={"option": question["option"]},
                        headers=headers,
                    )
                    assert answered.status_code == 200, answered.text
        finally:
            await gateway.delete_credential(path)
            async with owner_engine.begin() as conn:
                await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})

    run = await state(owner_engine, run_id)
    assert (run["waiting_reason"], run["current_phase"]) == ("gate", "ruleReview"), run
    context = (await load_run(app_engine, run_id, world.tenant_a)).context
    port = WorkerProjectPort(app_engine, context, gateway, None, None)
    result = evaluate(kit.reference, await port.load_rules())
    await port.save_evaluation(result)
    (spent,) = await fetch(
        owner_engine,
        "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls FROM usage_ledger WHERE project_id = :p",
        p=project_id,
    )
    metrics = {**result.metrics(), "model_calls": spent["calls"], "cost_usd": str(spent["usd"])}
    (folder / "evaluation.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {  # counts and rule ids only: the details stay in the kit folder
                "reference": result.reference,
                "reference_rules": result.reference_rules,
                "found_rules": result.found_rules,
                "recall": result.recall,
                "precision": result.precision,
                "omissions": result.omissions,
                "omissions_p0": result.omissions_p0,
                "hallucinations": result.hallucinations,
                "precision_errors": len(result.precision_errors),
                "known_bias": bool(result.known_bias),
                "model_calls": spent["calls"],
                "cost_usd": str(spent["usd"]),
            },
            indent=2,
        )
    )
    assert result.reference_rules == len(kit.reference.rules)
