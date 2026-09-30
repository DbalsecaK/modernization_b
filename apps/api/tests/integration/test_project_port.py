"""The worker's project port on the real services (plan M4 step 7): source code read from an accepted zip in the
object store, rules written as versions (a rerun only adds versions that changed, lost rules become obsolete),
stories with their dependencies and plan version 1, and the knowledge graph mirrored."""

import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.object_store import ObjectStore, ObjectStoreConfig, input_key
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.model import Rule
from nexti_core.spec.plan import Dependency
from nexti_graph import GraphStore, Scope
from nexti_model_gateway.service import GatewayService, SecretsConfig
from nexti_orchestration.stories import Stories, StoryDraft
from nexti_pack_spring_boot import Design
from nexti_ui import PrototypeBuild
from nexti_verification import compute
from nexti_verification import verdict as checks
from nexti_verification.evaluation import evaluate, load_reference
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort, read_zip

from .conftest import SETTINGS, World
from .run_support import execute, fetch, make_config, make_project, make_run

ROOT = Path(__file__).resolve().parents[4]
SOURCE = (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp").read_bytes()
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"


def graph_settings() -> dict[str, str]:
    env = ROOT / "apps" / "worker" / ".env"
    values: dict[str, str] = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.startswith("GRAPH_"):
                values[name] = value
    return values


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def rule(key: str, line: int, statement: str) -> Rule:
    return Rule.model_validate({
        "id": key, "name": f"Rule at {line}", "category": "validation", "priority": "P1", "statement": statement,
        "sources": [{"file": "sp/sp_pago_orden.sp", "line_start": line, "line_end": line + 3}],
    })  # fmt: skip


def story(title: str, links: list[str]) -> StoryDraft:
    criterion = "Scenario: It works\n  Given an order\n  When it is paid\n  Then it is marked A"
    return StoryDraft(title=title, links=links, criteria=[criterion])


def test_the_zip_is_read_as_text_with_limits() -> None:
    files = read_zip(zipped({"sp/sp_pago_orden.sp": SOURCE, "img/logo.png": b"\x89PNG\x00\x00", "notes.txt": b"hola",
                             "maps/PAGOSET.bms": BMS.read_bytes()}))  # fmt: skip
    assert [f.path for f in files] == ["sp/sp_pago_orden.sp", "notes.txt", "maps/PAGOSET.bms"]
    assert files[0].text.startswith("/*")


async def test_the_port_reads_inputs_and_versions_rules_stories_and_the_plan(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    store = ObjectStore(ObjectStoreConfig(SETTINGS.object_store_url, SETTINGS.object_store_access_key,
                                          SETTINGS.object_store_secret_key.get_secret_value(),
                                          SETTINGS.object_store_bucket))  # fmt: skip
    data = zipped({"sp/sp_pago_orden.sp": SOURCE})
    input_id = uuid.uuid4()
    key = input_key(world.tenant_a, project_id, input_id)
    await store.put(key, io.BytesIO(data), len(data), "application/zip")
    await execute(
        owner_engine,
        "INSERT INTO input_artifact (id, tenant_id, project_id, kind, name, version, status, object_key, size_bytes, "
        "sha256, content_type) VALUES (:i, :t, :p, 'source_archive', 'code.zip', 1, 'accepted', :k, :s, :h, "
        "'application/zip')",
        i=input_id, t=world.tenant_a, p=project_id, k=key, s=len(data), h=hashlib.sha256(data).hexdigest(),
    )  # fmt: skip
    loaded = await load_run(app_engine, run_id, world.tenant_a)
    graph_env = graph_settings()
    graph = (
        GraphStore.connect(graph_env["GRAPH_URI"], graph_env["GRAPH_USER"], graph_env["GRAPH_PASSWORD"])
        if graph_env.get("GRAPH_URI") else None
    )  # fmt: skip
    async with httpx.AsyncClient() as http:
        gateway = GatewayService(app_engine, http, SecretsConfig(SETTINGS.secrets_url, "unused"))
        port = WorkerProjectPort(app_engine, loaded.context, gateway, store, graph)
        try:
            (source,) = await port.source_files()
            assert source.path == "sp/sp_pago_orden.sp"

            await port.save_rules([rule("RULE-001", 34, "Only CTE, AHO and VIR accounts are debited."),
                                   rule("RULE-002", 80, "WEB pays half the tariff.")])  # fmt: skip
            # A rerun: RULE-001 unchanged, RULE-002 reworded, RULE-003 new... and RULE-001 then lost.
            await port.save_rules([rule("RULE-002", 80, "WEB orders pay half the tariff, rounded to cents."),
                                   rule("RULE-003", 144, "A paid order is marked A.")])  # fmt: skip
            versions = await fetch(
                owner_engine,
                "SELECT key, version, status FROM spec_element WHERE project_id = :p ORDER BY key, version",
                p=project_id,
            )
            assert [(v["key"], v["version"], v["status"]) for v in versions] == [
                ("RULE-001", 1, "review"), ("RULE-001", 2, "obsolete"),
                ("RULE-002", 1, "review"), ("RULE-002", 2, "review"),
                ("RULE-003", 1, "review"),
            ]  # fmt: skip
            assert [r.id for r in await port.load_rules()] == ["RULE-002", "RULE-003"]

            stories = Stories(
                [story("Charge the commission", ["RULE-002"]), story("Mark the order paid", ["RULE-003"])],
                [Dependency("US-002", "US-001", "hard", "reads db_pagos..pg_orden, written by US-001")],
                [["US-001"], ["US-002"]],
            )
            await port.save_stories(stories)
            rows = await fetch(
                owner_engine,
                "SELECT s.key, v.version, v.status, v.links FROM user_story s JOIN user_story_version v "
                "ON v.story_id = s.id WHERE s.project_id = :p ORDER BY s.key",
                p=project_id,
            )
            assert [(r["key"], r["version"], r["status"], r["links"]) for r in rows] == [
                ("US-001", 1, "review", ["RULE-002"]), ("US-002", 1, "review", ["RULE-003"]),
            ]  # fmt: skip
            (dep,) = await fetch(
                owner_engine,
                "SELECT d.strength, d.origin, d.reason FROM story_dependency d JOIN "
                "user_story s ON s.id = d.story_id WHERE s.project_id = :p",
                p=project_id,
            )
            assert (dep["strength"], dep["origin"]) == ("hard", "graph")
            (plan,) = await fetch(owner_engine, "SELECT version, waves, suggested FROM migration_plan WHERE "
                                                "project_id = :p", p=project_id)  # fmt: skip
            assert (plan["version"], plan["waves"], plan["suggested"]) == (1, [["US-001"], ["US-002"]],
                                                                            [["US-001"], ["US-002"]])  # fmt: skip

            # A new derivation keeps people's stories and plan; only the suggestion is new.
            await port.save_stories(Stories([story("Other", ["RULE-002", "RULE-003"])], [], [["US-001"]]))
            plans = await fetch(owner_engine, "SELECT version, waves, suggested FROM migration_plan WHERE "
                                              "project_id = :p ORDER BY version", p=project_id)  # fmt: skip
            assert [(p["version"], p["waves"], p["suggested"]) for p in plans][-1] == (
                2,
                [["US-001"], ["US-002"]],
                [["US-001"]],
            )
            titles = await fetch(owner_engine, "SELECT v.title FROM user_story s JOIN user_story_version v ON "
                                               "v.story_id = s.id WHERE s.project_id = :p", p=project_id)  # fmt: skip
            assert "Other" not in {t["title"] for t in titles}

            if graph is not None:
                scope = Scope(world.tenant_a, project_id)
                edges = set(await graph.edges(scope))
                assert ("story:US-002", "DEPENDS_ON", "story:US-001") in edges
                assert ("story:US-001", "COVERS", "rule:RULE-002") in edges
        finally:
            if graph is not None:
                await graph.delete_project(Scope(world.tenant_a, project_id))
                await graph.close()
    assert json.dumps({"ok": True})


async def test_the_port_keeps_designs_drafts_and_the_golden_master_as_references(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    store = ObjectStore(ObjectStoreConfig(SETTINGS.object_store_url, SETTINGS.object_store_access_key,
                                          SETTINGS.object_store_secret_key.get_secret_value(),
                                          SETTINGS.object_store_bucket))  # fmt: skip
    loaded = await load_run(app_engine, run_id, world.tenant_a)
    fixtures = ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden"
    master = (fixtures / "golden" / "086a748602b848d260c4abb97357af67.json").read_text(encoding="utf-8")
    design = (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text("utf-8")
    async with httpx.AsyncClient() as http:
        gateway = GatewayService(app_engine, http, SecretsConfig(SETTINGS.secrets_url, "unused"))
        port = WorkerProjectPort(app_engine, loaded.context, gateway, store, None)
        assert await port.load_design() is None
        runner = port.legacy_runner()  # this worker has no engine and the inputs have no traces: the phase waits
        assert runner is not None
        with pytest.raises(LegacyUnavailableError):
            await runner.run(await port.source_files(), Suite.model_validate_json(
                (fixtures / "characterization.json").read_text(encoding="utf-8")))  # fmt: skip

        await port.save_design(Design.model_validate_json(design))
        loaded_design = await port.load_design()
        assert loaded_design is not None
        assert loaded_design.context == "payments"
        reference = await port.save_file("src/A.java", "class A {}")
        assert reference.startswith(f"tenants/{world.tenant_a}/projects/{project_id}/runs/{run_id}/drafts/")
        assert await port.load_file(reference) == "class A {}"
        await port.save_golden_master(GoldenMaster.model_validate_json(master))
        loaded_master = await port.load_golden_master()
        assert loaded_master is not None
        assert len(loaded_master.results) == 12
        await port.save_artifacts({"src/main/java/A.java": "class A {}"}, {"src/main/java/A.java": "domain"},
                                  {"src/main/java/A.java": ["RULE-001"]})  # fmt: skip
        generated, traced = await port.load_generated()
        assert generated == {"src/main/java/A.java": "class A {}"}  # the design and the golden master apart
        assert traced == {"src/main/java/A.java": ["RULE-001"]}
        verdict = compute("PayOrder", [checks.tests_ran(7, 0, True)], ["a note"])
        pack_key = await port.save_verdict(verdict, b"PK-proof")
        assert pack_key.endswith("/verification/PayOrder/proof-pack.zip")
        assert b"".join(await store.read(pack_key)) == b"PK-proof"
        (row,) = await fetch(owner_engine, "SELECT verdict, checks, not_proven FROM verdict WHERE run_id = :r",
                             r=run_id)  # fmt: skip
        assert row["verdict"] == "PARTLY PROVEN"
        assert row["checks"][0]["key"] == "tests_ran"
        assert row["not_proven"][0] == "a note"
        spec_file = fixtures / "reference_spec.json"
        await port.save_evaluation(evaluate(load_reference(spec_file), []))
        (stored,) = await fetch(owner_engine, "SELECT reference, reference_sha256, metrics FROM evaluation "
                                "WHERE project_id = :p", p=project_id)  # fmt: skip
        assert stored["reference_sha256"] == hashlib.sha256(spec_file.read_bytes()).hexdigest()
        assert stored["metrics"]["omissions_p0"] == ["RULE-001", "RULE-002", "RULE-004", "RULE-006", "RULE-007"]
        assert "statement" not in json.dumps(stored["metrics"])  # the metrics, never the content of the reference

        # Screens, the design system and prototype versions (M5).
        screens = BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text(encoding="utf-8"))])
        await port.save_screens(screens)
        await port.save_screens(screens)  # unchanged: no new version
        assert await port.ensure_design_system() == 1
        assert await port.ensure_design_system() == 1
        built = PrototypeBuild(True, js="console.log(1)", css=".nx-root{}")
        assert await port.save_prototype("SCR-PAGOORD", "export default () => null", built, "generated", "") == 1
        assert await port.save_prototype("SCR-PAGOORD", "export default () => null", built, "chat", "agrupa") == 2
    elements = await fetch(owner_engine, "SELECT key, version FROM spec_element WHERE project_id = :p AND "
                           "element_type = 'screen' ORDER BY key", p=project_id)  # fmt: skip
    assert [(e["key"], e["version"]) for e in elements] == [("SCR-PAGOMEN", 1), ("SCR-PAGOORD", 1), ("SCR-PAGORES", 1)]
    (system,) = await fetch(owner_engine, "SELECT source, tokens FROM design_system WHERE project_id = :p",
                            p=project_id)  # fmt: skip
    assert system["source"] == "nexti-base"
    assert system["tokens"]["color"]["primary"] == "#052158"
    versions = await fetch(owner_engine, "SELECT version, origin, bundle_key FROM prototype WHERE project_id = :p "
                           "ORDER BY version", p=project_id)  # fmt: skip
    assert [(v["version"], v["origin"]) for v in versions] == [(1, "generated"), (2, "chat")]
    served = b"".join(await store.read(versions[1]["bundle_key"])).decode("utf-8")
    assert served.startswith("<!doctype html>")
    assert "console.log(1)" in served

    rows = await fetch(owner_engine, "SELECT path, layer, rules, object_key FROM generated_artifact "
                                     "WHERE project_id = :p ORDER BY path", p=project_id)  # fmt: skip
    assert [(r["path"], r["layer"]) for r in rows] == [
        ("characterization/golden_master.json", "tests"), ("design/design.json", "docs"),
        ("src/main/java/A.java", "domain"),
    ]  # fmt: skip
    assert rows[0]["rules"] == [f"RULE-00{n}" for n in range(1, 10)]
    kept = b"".join(await store.read(rows[0]["object_key"])).decode("utf-8")
    assert GoldenMaster.model_validate_json(kept).engine == "sybase-ase-16.0"


@pytest.mark.parametrize("mode", ["replay", "record"])
def test_recorded_responses_are_refused_outside_development(mode: str) -> None:
    from pydantic import ValidationError

    from nexti_worker.settings import WorkerSettings

    assert WorkerSettings(app_env="test", model_cassettes_dir="c", model_cassettes_mode=mode).model_cassettes_mode
    with pytest.raises(ValidationError, match="only allowed in development"):
        WorkerSettings(app_env="production", model_cassettes_dir="c", model_cassettes_mode=mode)
