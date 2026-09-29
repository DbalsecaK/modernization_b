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

from nexti_core.object_store import ObjectStore, ObjectStoreConfig, input_key
from nexti_core.spec.model import Rule
from nexti_core.spec.plan import Dependency
from nexti_graph import GraphStore, Scope
from nexti_model_gateway.service import GatewayService, SecretsConfig
from nexti_orchestration.stories import Stories, StoryDraft
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort, read_zip

from .conftest import SETTINGS, World
from .run_support import execute, fetch, make_config, make_project, make_run

ROOT = Path(__file__).resolve().parents[4]
SOURCE = (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp").read_bytes()


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
    files = read_zip(zipped({"sp/sp_pago_orden.sp": SOURCE, "img/logo.png": b"\x89PNG\x00\x00", "notes.txt": b"hola"}))
    assert [f.path for f in files] == ["sp/sp_pago_orden.sp", "notes.txt"]
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
            (dep,) = await fetch(owner_engine, "SELECT strength, origin, reason FROM story_dependency")
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


@pytest.mark.parametrize("mode", ["replay", "record"])
def test_recorded_responses_are_refused_outside_development(mode: str) -> None:
    from pydantic import ValidationError

    from nexti_worker.settings import WorkerSettings

    assert WorkerSettings(app_env="test", model_cassettes_dir="c", model_cassettes_mode=mode).model_cassettes_mode
    with pytest.raises(ValidationError, match="only allowed in development"):
        WorkerSettings(app_env="production", model_cassettes_dir="c", model_cassettes_mode=mode)
