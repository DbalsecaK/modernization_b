"""Validation and traceability through the API (spec 11.3, 11.6; plan M4 step 14): the verdicts the worker computed,
their proof pack, and rule by rule the cited legacy lines, the generated files that implement the rule and the
golden cases that exercise it."""

import io
import uuid
import zipfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, ObjectStoreConfig

from .conftest import SETTINGS, World
from .run_support import make_project, seed_spec, seed_validation
from .test_runs_api import sign_in


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def store() -> ObjectStore:
    return ObjectStore(ObjectStoreConfig(SETTINGS.object_store_url, SETTINGS.object_store_access_key,
                                         SETTINGS.object_store_secret_key.get_secret_value(),
                                         SETTINGS.object_store_bucket))  # fmt: skip


async def seeded(
    owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> tuple[uuid.UUID, uuid.UUID]:
    project_id = await make_project(owner, world.tenant_a)
    await seed_spec(owner, world.tenant_a, project_id)
    verdict_id = await seed_validation(owner, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id, verdict_id


async def test_the_verdict_and_its_proof_pack(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, verdict_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    (verdict,) = api.get(f"/api/v1/projects/{project_id}/verdicts", headers=headers).json()
    assert (verdict["id"], verdict["module"], verdict["verdict"]) == (str(verdict_id), "PayOrder", "PARTLY PROVEN")
    assert [c["key"] for c in verdict["checks"]] == ["tests_ran", "same_behaviour"]
    assert verdict["notProven"][0] == "a note"
    assert verdict["hasProofPack"] is True
    download = api.get(f"/api/v1/projects/{project_id}/verdicts/{verdict_id}/proof-pack", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert "attachment" in download.headers["content-disposition"]
    assert "VERIFICATION.json" in zipfile.ZipFile(io.BytesIO(download.content)).namelist()
    missing = api.get(f"/api/v1/projects/{project_id}/verdicts/{uuid.uuid4()}/proof-pack", headers=headers)
    assert missing.status_code == 404


async def test_rule_by_rule_the_legacy_the_target_and_the_behaviour(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    rules = {r["key"]: r for r in api.get(f"/api/v1/projects/{project_id}/traceability", headers=headers).json()}
    assert set(rules) == {"RULE-001", "RULE-002", "RULE-003"}
    first = rules["RULE-001"]
    assert first["sources"] == ["sp_pago_orden.sp:40-42"]
    assert first["targetFiles"] == ["src/main/java/demo/PayOrderService.java"]
    assert (first["cases"], first["matched"], first["verified"]) == (1, 1, True)
    assert rules["RULE-002"]["verified"] is None  # not part of that verification
    assert rules["RULE-002"]["targetFiles"] == []

    detail = api.get(f"/api/v1/projects/{project_id}/traceability/RULE-001", headers=headers).json()
    (legacy,) = detail["legacy"]
    assert legacy["path"] == "sp/sp_pago_orden.sp"
    assert legacy["firstLine"] == 37
    assert legacy["highlighted"] == [40, 41, 42]
    assert len(legacy["lines"]) == 9  # the cited lines with three lines of context on each side
    (target,) = detail["target"]
    assert target["highlighted"] == [5]
    assert "RULE-001" in target["lines"][4]
    assert detail["cases"] == [{"name": "case_one", "matched": True, "failure": None, "differences": []}]
    assert (detail["verified"], detail["verdict"]) == (True, "PARTLY PROVEN")
    assert api.get(f"/api/v1/projects/{project_id}/traceability/RULE-404", headers=headers).status_code == 404


async def test_before_any_verification_the_trace_says_so(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_spec(owner_engine, world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    assert api.get(f"/api/v1/projects/{project_id}/verdicts", headers=headers).json() == []
    rules = api.get(f"/api/v1/projects/{project_id}/traceability", headers=headers).json()
    assert {r["verified"] for r in rules} == {None}
    detail = api.get(f"/api/v1/projects/{project_id}/traceability/RULE-001", headers=headers).json()
    assert (detail["legacy"], detail["target"], detail["cases"], detail["verdict"]) == ([], [], [], None)
