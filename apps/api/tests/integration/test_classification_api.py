"""The classification of the statements through the API (spec 6.1 phase 4): the counts and each statement with its
class and why, as the classification phase stored them; nothing before the phase; another tenant reaches nothing."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import make_project, seed_classification
from .test_runs_api import sign_in
from .test_validation_api import store


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_the_statements_come_with_their_class_and_reason(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_classification(owner_engine, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    found = api.get(f"/api/v1/projects/{project_id}/classification", headers=headers).json()
    assert set(found["counts"]) == {"business", "control_flow", "infrastructure"}
    assert len(found["statements"]) == sum(found["counts"].values())
    first = found["statements"][0]
    assert (first["unit"], first["file"]) == ("dbo.sp_pago_orden", "sp/sp_pago_orden.sp")
    assert {"lineStart", "lineEnd", "statement", "label", "reason"} <= set(first)
    assert api.get(f"/api/v1/projects/{project_id}/classification", headers=sign_in(api, world.b_user)).status_code in (
        403,
        404,
    )


async def test_before_the_classification_there_is_nothing(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    assert api.get(f"/api/v1/projects/{project_id}/classification", headers=sign_in(api, world.a_user)).json() is None
