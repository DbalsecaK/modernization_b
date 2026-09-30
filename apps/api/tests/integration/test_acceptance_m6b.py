"""Acceptance of M6b (plan section 3) with the fictitious application: the Sybase procedure's design (M4) and the BMS
maps with the prototypes the UX/UI designer drew for them (M5, taken from that milestone's recording) become a React
frontend and an Angular one. The frontend developer writes each page; the platform's harness checks it in the frontend
sandbox; both frontends compile, pass their tests, cover every field, validation and action of the screen specs and
have no serious axe violation, and each gets its own verdict. The generation runs through the engine with the
worker's real project port.

CI replays what a real model answered (ADR-0012) with the real frontend sandbox. Recording is on demand, with a
budget: NEXTI_RECORD_M6B=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS) and writes the recordings next to this
test. Skipped without Docker or the frontend image, and in replay when nothing has been recorded yet."""

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_orchestration import PhaseSpec
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.frontend import frontend_checks, generate
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.ui import tsx_block
from nexti_orchestration.verification import frontend_proof_pack
from nexti_pack_frontend import IMAGE
from nexti_pack_spring_boot import Design
from nexti_sandbox import DockerSandbox
from nexti_ui import PrototypeBuild
from nexti_verification import verdict as checks
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort

from .conftest import SETTINGS, World
from .run_support import TARGET, fetch, make_config, make_project, make_run, seed_screens
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap

ROOT = Path(__file__).resolve().parents[4]
RECORDINGS = Path(__file__).parent / "recordings" / "m6b"
M5 = Path(__file__).parent / "recordings" / "m5" / "models"
DESIGN = Design.model_validate_json(
    (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
MODEL = "anthropic/claude-sonnet-5.5"  # the model of test_acceptance_m4.model_for
BUDGET_USD = Decimal("2.00")  # of what is left of the 10 USD for M6, M6b and M6c
TEAM = {"frontend-dev": "1.2.0"}
RECORD = os.environ.get("NEXTI_RECORD_M6B") == "1"
FLAVOURS: tuple[Literal["react", "angular"], ...] = ("react", "angular")


def prototypes_of_m5() -> dict[str, str]:
    """The prototypes of M5's recorded run, the newest per screen (the chat's version 2 of PAGOORD included)."""
    found: dict[str, tuple[int, str]] = {}
    for path in sorted(M5.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if "UX/UI Designer" not in entry["messages"][0]["content"]:
            continue
        request = entry["messages"][1]["content"]
        screen = re.search(r'"id": "(SCR-[A-Z]+)"', request)
        if screen is None:
            continue
        rank = 2 if "Change asked by the reviewer" in request else 1
        if found.get(screen.group(1), (0, ""))[0] < rank:
            found[screen.group(1)] = (rank, tsx_block(entry["response"]["content"]))
    return {screen: source for screen, (_, source) in found.items()}


@pytest.fixture(scope="module")
def ready() -> None:
    if not _image(IMAGE):
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M6B=1")


async def test_the_fictitious_application_gets_a_react_and_an_angular_frontend(
    ready: None, app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    mode: Literal["record", "replay"] = "record" if RECORD else "replay"
    store = object_store()
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_screens(owner_engine, store, world.tenant_a, project_id)
    prototypes = prototypes_of_m5()
    assert set(prototypes) == {"SCR-PAGOMEN", "SCR-PAGOORD", "SCR-PAGORES"}
    report: dict[str, Any] = {"model": MODEL, "mode": mode}

    async with httpx.AsyncClient(timeout=60) as http:
        secrets = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, secrets, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        try:
            for flavour in FLAVOURS:
                version = await make_config(owner_engine, world.tenant_a, project_id, team=TEAM,
                                            target={**TARGET, "frontend": flavour})  # fmt: skip
                run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
                run = (await load_run(app_engine, run_id, world.tenant_a)).context
                port = WorkerProjectPort(
                    app_engine, run, gateway, store, None, lambda image: DockerSandbox(image=image)
                )
                if flavour == FLAVOURS[0]:  # the prototypes approved at C2, newest per screen
                    for screen, source in sorted(prototypes.items()):
                        await port.save_prototype(screen, source, PrototypeBuild(True), "generated", "M5 recording")
                events = MemoryStore()
                ctx = PhaseContext(run, events, PhaseSpec("generation", None, True), None)
                files, final, summary = await generate(ctx, port, DESIGN, flavour)
                assert final is not None, summary
                await port.save_artifacts(files, {}, {})
                verdict = checks.compute(f"frontend-{flavour}", frontend_checks(final), [],
                                         required=checks.FRONTEND_CHECKS)  # fmt: skip
                await port.save_verdict(verdict, frontend_proof_pack(verdict, final))
                report[flavour] = {
                    "summary": summary,
                    "verdict": verdict.verdict,
                    "checks": {c.key: c.status for c in verdict.checks},
                    "screens": {s.id: {c.key: c.status for c in s.checks} for s in final.screens},
                    "self_corrected": events.kinds().count("selfCorrected"),
                }
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                async with owner_engine.begin() as conn:
                    await conn.execute(text("DELETE FROM budget WHERE id = :b"), {"b": cap})

    (cost,) = await fetch(
        owner_engine,
        "SELECT COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls FROM usage_ledger WHERE project_id = :p",
        p=project_id,
    )
    report |= {"model_calls": cost["calls"], "cost_usd": str(cost["usd"])}
    print(json.dumps(report, indent=2))  # the evidence of the run in the test output
    if RECORD:
        (RECORDINGS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        recorded = json.loads((RECORDINGS / "report.json").read_text(encoding="utf-8"))
        for flavour in FLAVOURS:
            assert report[flavour]["checks"] == recorded[flavour]["checks"]
    verdicts = await fetch(owner_engine, "SELECT module, verdict FROM verdict WHERE project_id = :p ORDER BY module",
                           p=project_id)  # fmt: skip
    assert [(v["module"], v["verdict"]) for v in verdicts] == [
        ("frontend-angular", "PROVEN"),
        ("frontend-react", "PROVEN"),
    ]
    for flavour in FLAVOURS:
        assert set(report[flavour]["checks"].values()) == {"passed"}, report[flavour]
