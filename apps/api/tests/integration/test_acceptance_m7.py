"""Acceptance of M7 (plan section 3, ADR-0018): with a set of user stories + Figma of example, a functionality is
generated and validated end to end, with each element traced to its input. The fictitious "Simulador de crédito":
its requirements and stories are uploaded as documents and its Figma file is added as a link; the worker reads Figma
with the recorded answer of the file (the tenant's integration is not needed in replay). The whole Flow 2 runs through
the worker and the API: ingestion, normalization, consolidation (the gaps and contradictions become questions that a
person answers with the recommendation), C1, prototypes (C2), design without legacy (C3), generation with the Spring
Boot and React packs in their sandboxes, validation with the verdict computed by code (C4) and delivery.

CI replays what real models answered (ADR-0012). Recording is on demand, with a budget: NEXTI_RECORD_M7=1 calls
OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) and writes the answers next to this test. Skipped without Docker or the
images, and in replay when nothing has been recorded yet."""

import hashlib
import io
import json
import os
import uuid
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
from nexti_core.object_store import ObjectStore, input_key
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_ingest.figma import RecordedFigma
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_frontend import IMAGE as FRONTEND_IMAGE
from nexti_pack_spring_boot.build import IMAGE as JAVA_IMAGE
from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE as WEB_IMAGE
from nexti_verification.verdict import FEATURE_CHECKS
from nexti_worker.runner import Runtime, execute_run

from .conftest import SETTINGS, Databases, World
from .run_support import TARGET, FakeSandbox, fetch, make_config, make_project, make_run, psycopg_dsn
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap, state
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m7"
EXAMPLE = Path(__file__).resolve().parents[4] / "packages/ingest/tests/fixtures/simulador_credito"
FIGMA_FILE = "FicSimCred2026abc"
FIGMA_URL = f"https://www.figma.com/design/{FIGMA_FILE}/Simulador-de-credito"
MODEL = "anthropic/claude-sonnet-5.5"  # the model of test_acceptance_m4.model_for
BUDGET_USD = Decimal("5.00")  # of the 10 USD proposed for M7 and M7b
TARGET_FEATURE = {**TARGET, "backend": "spring-boot", "frontend": "react", "database": "postgresql"}
TEAM = {
    "functional-analyst": "0.9.0",
    "rules-verifier": "1.3.0",
    "ux-designer": "0.8.0",
    "solution-architect": "1.3.0",
    "test-engineer": "1.6.0",
    "backend-dev": "1.5.0",
    "frontend-dev": "1.2.0",
    "acceptance-judge": "1.0.0",
}
RECORD = os.environ.get("NEXTI_RECORD_M7") == "1"


@pytest.fixture(scope="module")
def ready() -> None:
    for image in (JAVA_IMAGE, WEB_IMAGE, FRONTEND_IMAGE):
        if not _image(image):
            pytest.skip(f"Docker or the image {image} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M7=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def upload_inputs(owner: AsyncEngine, store: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """The requirements and the stories as accepted documents, and the Figma file as a link (as the API leaves them
    after validation)."""
    async with owner.begin() as conn:
        for name in ("requisitos.md", "historias.md"):
            data = (EXAMPLE / name).read_bytes()
            input_id = uuid.uuid4()
            key = input_key(tenant_id, project_id, input_id)
            await store.put(key, io.BytesIO(data), len(data), "text/markdown")
            await conn.execute(
                text("INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, "
                     "size_bytes, sha256, content_type) VALUES (:i, :t, :p, 'document', :n, 1, 'accepted', :k, :s, :h, "
                     "'text/markdown')"),
                {"i": input_id, "t": tenant_id, "p": project_id, "n": name, "k": key, "s": len(data),
                 "h": hashlib.sha256(data).hexdigest()},
            )  # fmt: skip
        await conn.execute(
            text("INSERT INTO input_artifact (tenant_id, project_id, kind, name, version, status, url, notes) VALUES "
                 "(:t, :p, 'figma_link', :n, 1, 'accepted', :u, 'Respetar los textos y la navegación')"),
            {"t": tenant_id, "p": project_id, "n": f"Figma {FIGMA_FILE}", "u": FIGMA_URL},
        )  # fmt: skip
        await conn.execute(text("UPDATE project SET flow = 'newFeature' WHERE id = :p"), {"p": project_id})


async def test_a_functionality_from_stories_and_figma_is_built_and_validated_end_to_end(
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
    version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM, target=TARGET_FEATURE)
    await upload_inputs(owner_engine, store, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await grant(owner_engine, world, world.a_user, "architect", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    decided: list[str] = []
    questions: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        runtime = Runtime(
            engine=app_engine, dsn=psycopg_dsn(databases.app_url), sandbox=FakeSandbox(), http=http, objects=store,
            secrets=SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http),
            gateway=gateway, sandboxes=lambda image: DockerSandbox(image=image),
            figma=RecordedFigma(EXAMPLE / "figma"),
        )  # fmt: skip
        try:
            for _ in range(40):
                await execute_run(runtime, run_id, world.tenant_a)
                run = await state(owner_engine, run_id)
                if run["status"] != "waiting":
                    break
                if run["waiting_reason"] == "gate":
                    (gate,) = await fetch(owner_engine, "SELECT gate FROM gate WHERE run_id = :r "
                                          "AND status = 'pending' ORDER BY gate LIMIT 1", r=run_id)  # fmt: skip
                    if gate["gate"] == "C1":
                        blockers = api.get(f"{base}/c1-check").json()
                        assert blockers["blockers"] == [], blockers
                    approved = api.post(f"{base}/runs/{run_id}/gates/{gate['gate']}:approve", json={}, headers=headers)
                    assert approved.status_code == 200, approved.text
                    decided.append(gate["gate"])
                elif run["waiting_reason"] == "question":
                    asked = await fetch(owner_engine, "SELECT id, question_text, recommended->>'key' AS option "
                                        "FROM question WHERE run_id = :r AND status = 'open'", r=run_id)  # fmt: skip
                    assert asked, "the run waits for a question that is not open"
                    for question in asked:  # a person takes each recommendation
                        answered = api.post(f"{base}/questions/{question['id']}:answer",
                                            json={"option": question["option"]}, headers=headers)  # fmt: skip
                        assert answered.status_code == 200, answered.text
                        questions.append(question["question_text"])
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
    assert {"C1", "C2", "C3", "C4"} <= set(decided)
    verdicts = {v["module"]: v for v in await fetch(owner_engine, "SELECT module, verdict, checks, proof_pack_key "
                                                    "FROM verdict WHERE run_id = :r", r=run_id)}  # fmt: skip
    feature = next(v for m, v in verdicts.items() if not m.startswith("frontend-"))
    frontend = verdicts.get("frontend-react")
    stories = await fetch(owner_engine, "SELECT DISTINCT ON (s.key) s.key, v.origin, v.links FROM user_story s JOIN "
                          "user_story_version v ON v.story_id = s.id WHERE s.project_id = :p ORDER BY s.key, v.version "
                          "DESC", p=project_id)  # fmt: skip
    elements = await fetch(owner_engine, "SELECT DISTINCT ON (key) key, element_type, data FROM spec_element WHERE "
                           "project_id = :p ORDER BY key, version DESC", p=project_id)  # fmt: skip
    files = {f["path"] for f in await fetch(owner_engine, "SELECT path FROM generated_artifact WHERE run_id = :r",
                                            r=run_id)}  # fmt: skip
    (cost,) = await fetch(owner_engine, "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls "
                          "FROM usage_ledger WHERE project_id = :p", p=project_id)  # fmt: skip
    report: dict[str, Any] = {
        "model": MODEL, "mode": mode, "verdict": feature["verdict"],
        "checks": {c["key"]: c["status"] for c in feature["checks"]},
        "details": {c["key"]: c["detail"] for c in feature["checks"]},
        "frontend": frontend["verdict"] if frontend else None,
        "frontend_checks": {c["key"]: c["status"] for c in frontend["checks"]} if frontend else {},
        "stories": len(stories), "rules": sum(1 for e in elements if e["element_type"] == "rule"),
        "screens": sum(1 for e in elements if e["element_type"] == "screen"), "questions": questions,
        "model_calls": cost["calls"], "cost_usd": str(cost["usd"]), "decisions": decided,
    }  # fmt: skip
    print(json.dumps(report, indent=2, ensure_ascii=False))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        assert (report["verdict"], report["checks"], report["frontend"]) == (
            recorded["verdict"], recorded["checks"], recorded["frontend"])  # fmt: skip
    assert [c["key"] for c in feature["checks"]] == [k for k, _ in FEATURE_CHECKS]
    assert feature["proof_pack_key"]
    assert stories
    assert {s["origin"] for s in stories} == {"document"}
    traced = [e for e in elements if e["element_type"] in ("rule", "screen")]
    assert traced
    assert all(e["data"]["sources"] for e in traced)  # every element cites its input
    assert all(s["file"].startswith(("docs/", "figma/")) for e in traced for s in e["data"]["sources"])
    assert any(p.startswith("inputs/figma/") for p in files)
    assert any(p.startswith("frontend/") for p in files)
