"""Acceptance of M5 (plan section 3) with the fictitious BMS application: the maps uploaded in a zip become screen
specs with every field's position, length and attributes; the UX/UI designer writes a prototype per screen with the
design system, which code checks (every field shown) and compiles in the web sandbox; the API serves each page for an
isolated frame; a change asked through the chat comes back from the worker as a new version or as a proposal a
person accepts. The UI phase runs through the engine with the worker's real project port; the whole pipeline around
it is M4's acceptance.

CI replays what a real model answered (ADR-0012) with the real web sandbox. Recording is on demand, with a budget:
NEXTI_RECORD_M5=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) and writes the recordings next to this test.
Skipped without Docker or the web image, and in replay when nothing has been recorded yet."""

import json
import os
import re
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
from nexti_core.spec.screens import ScreenSpec
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_orchestration import PhaseSpec
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.ui import UiPhases, missing_fields
from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort
from nexti_worker.ui_chat import apply_ui_change

from .conftest import SETTINGS, World
from .run_support import BMS_SOURCE, fetch, make_config, make_project, make_run
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap, upload_source
from .test_runs_api import grant, sign_in

RECORDINGS = Path(__file__).parent / "recordings" / "m5"
MODEL = "anthropic/claude-sonnet-5.5"  # the model of test_acceptance_m4.model_for
BUDGET_USD = Decimal("5.00")
TEAM = {"ux-designer": "0.8.0"}
RECORD = os.environ.get("NEXTI_RECORD_M5") == "1"
CHANGE = "Agrupa los datos de la orden en una tarjeta y deja el valor alineado a la derecha"
EXPECTED = json.loads((BMS_SOURCE.parent / "reference_screens.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ready() -> None:
    if not _image(IMAGE):
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M5=1")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def _shown(source: str) -> set[str]:
    return set(re.findall(r"""data-field\s*=\s*(?:\{\s*)?['"]([^'"]+)['"]""", source))


async def test_the_fictitious_bms_application_gets_isolated_prototypes_and_a_change_by_chat(
    ready: None, api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    mode: Literal["record", "replay"] = "record" if RECORD else "replay"
    store = object_store()
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM)
    await upload_source(owner_engine, store, world.tenant_a, project_id, {"maps/PAGOSET.bms": BMS_SOURCE.read_bytes()})
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        try:
            # The UI phase through the engine, with the worker's port (object store, database, web sandbox).
            run = (await load_run(app_engine, run_id, world.tenant_a)).context
            port = WorkerProjectPort(app_engine, run, gateway, store, None, lambda image: DockerSandbox(image=image))
            events = MemoryStore()
            ctx = PhaseContext(run, events, PhaseSpec("ui", "C2", True), None)
            result = await UiPhases(port).ui(ctx)

            # A change asked through the API, applied by the worker's job.
            asked = api.post(f"{base}/screens/SCR-PAGOORD/chat", json={"body": CHANGE}, headers=headers)
            assert asked.status_code == 202, asked.text
            message_id = uuid.UUID(asked.json()[-1]["id"])
            outcome = await apply_ui_change(
                app_engine, gateway, store, lambda image: DockerSandbox(image=image), message_id, world.tenant_a
            )
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                async with owner_engine.begin() as conn:
                    await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})

    assert result.summary.startswith("3 screen(s) with 16 fields"), result.summary

    # Every field of the maps, with its position, length and attributes, is in the screen specs.
    screens = {
        s["key"]: ScreenSpec.model_validate(s["data"]) for s in api.get(f"{base}/screens", headers=headers).json()
    }
    assert set(screens) == {"SCR-PAGOMEN", "SCR-PAGOORD", "SCR-PAGORES"}
    for reference in EXPECTED["maps"]:
        key = f"SCR-{reference['map']}"
        for expected in reference["fields"]:
            got = screens[key].field(expected["name"])
            assert got is not None, (key, expected["name"])
            assert got.position is not None, (key, expected["name"])
            assert (got.position.row, got.position.column, got.length, list(got.attributes)) == (
                expected["row"], expected["column"], expected["length"], expected["attributes"]
            ), (key, expected["name"])  # fmt: skip

    # A prototype per screen: it shows every field, compiles, and is served for an isolated frame.
    shown: dict[str, int] = {}
    for key, screen in screens.items():
        (first, *_) = sorted(
            api.get(f"{base}/screens/{key}/prototypes", headers=headers).json(), key=lambda v: v["version"]
        )
        source = api.get(f"{base}/screens/{key}/prototypes/{first['version']}/source", headers=headers).text
        assert missing_fields(screen, source) == [], key
        shown[key] = len(_shown(source))
        served = api.get(f"{base}/screens/{key}/prototypes/{first['version']}/page", headers=headers)
        assert served.status_code == 200
        assert "sandbox allow-scripts" in served.headers["content-security-policy"]
        assert "connect-src 'none'" in served.headers["content-security-policy"]
        assert "allow-same-origin" not in served.headers["content-security-policy"]
    (system,) = await fetch(
        owner_engine, "SELECT version, source FROM design_system WHERE project_id = :p", p=project_id
    )
    assert (system["version"], system["source"]) == (1, "nexti-base")

    # The change: a new version, or a proposal a person accepts (the chat never approves C2).
    assert outcome in ("version", "proposal"), outcome
    if outcome == "proposal":
        proposal = api.get(f"{base}/screens/SCR-PAGOORD/chat", headers=headers).json()[-1]
        accepted = api.post(f"{base}/screens/SCR-PAGOORD/chat/{proposal['id']}:accept", headers=headers)
        assert accepted.status_code == 200, accepted.text
    versions = api.get(f"{base}/screens/SCR-PAGOORD/prototypes", headers=headers).json()
    assert sorted((v["version"], v["origin"]) for v in versions) == [(1, "generated"), (2, "chat")]
    changed = api.get(f"{base}/screens/SCR-PAGOORD/prototypes/2/source", headers=headers).text
    assert missing_fields(screens["SCR-PAGOORD"], changed) == []

    (cost,) = await fetch(
        owner_engine,
        "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls FROM usage_ledger WHERE project_id = :p",
        p=project_id,
    )
    report: dict[str, Any] = {
        "model": MODEL,
        "mode": mode,
        "screens": sorted(screens),
        "fields": sum(len([f for f in s.fields if f.kind != "literal"]) for s in screens.values()),
        "data_fields_shown": shown,
        "self_corrected": events.kinds().count("selfCorrected"),
        "chat_outcome": outcome,
        "model_calls": cost["calls"],
        "cost_usd": str(cost["usd"]),
    }
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        # The replay reproduces the recorded run: same screens, same prototypes, same chat outcome.
        keys = ("screens", "fields", "data_fields_shown", "chat_outcome")
        assert {k: report[k] for k in keys} == {k: recorded[k] for k in keys}
