"""The independent validation through the API (Flow 4, ADR-0025): the target's inventory and the vendor's mapping as
the intake stored them, checked by code against the golden master; a person corrects the mapping before C2 (a new
object, audited), an unreadable one is refused, and another tenant reaches nothing."""

import uuid
from collections.abc import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import fetch, make_project, seed_ivv
from .test_runs_api import sign_in
from .test_validation_api import store


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _project(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_ivv(owner, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


async def test_the_inventory_and_the_mapping_are_shown_and_checked(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    found = api.get(f"/api/v1/projects/{project_id}/ivv", headers=headers).json()
    assert found["inventory"]["stack"] == "spring-boot"
    assert found["inventory"]["endpoints"][0]["path"] == "/api/v1/payments"
    assert "/api/v1/payments" in found["mapping"]
    assert (found["problems"], found["gaps"], found["report"]) == ([], [], None)


async def test_a_corrected_mapping_is_saved_audited_and_rechecked(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    url = f"/api/v1/projects/{project_id}/ivv"
    mapping = yaml.safe_load(api.get(url, headers=headers).json()["mapping"])
    mapping["programs"][0]["request"].pop("channel")
    changed = api.put(f"{url}/mapping", json={"mapping": yaml.safe_dump(mapping)}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["problems"] == ["The legacy parameter @i_canal goes to no request field"]
    assert "channel" not in api.get(url, headers=headers).json()["mapping"].split("request:")[1].split("response:")[0]
    audited = await fetch(owner_engine, "SELECT details FROM audit_log WHERE action = 'ivv.mapping.change' "
                                        "AND target = :t", t=f"project:{project_id}")  # fmt: skip
    assert [a["details"]["problems"] for a in audited] == [1]
    for broken in ("programs: [", "programs: [{legacy: 1, unknown: x}]"):
        refused = api.put(f"{url}/mapping", json={"mapping": broken}, headers=headers)
        assert (refused.status_code, refused.json()["code"]) == (422, "invalid_mapping")


async def test_before_the_target_intake_there_is_no_mapping_to_change(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    found = api.get(f"/api/v1/projects/{project_id}/ivv", headers=headers).json()
    assert (found["inventory"], found["mapping"], found["problems"]) == (None, None, [])
    refused = api.put(f"/api/v1/projects/{project_id}/ivv/mapping", json={"mapping": "programs: []"}, headers=headers)
    assert refused.status_code == 404


async def test_the_validation_of_another_tenant_is_unreachable(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.b_user)
    url = f"/api/v1/projects/{project_id}/ivv"
    assert api.get(url, headers=headers).status_code in (403, 404)
    assert api.put(f"{url}/mapping", json={"mapping": "programs: []"}, headers=headers).status_code in (403, 404)
