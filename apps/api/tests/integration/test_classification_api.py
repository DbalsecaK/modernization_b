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


async def test_coverage_marks_each_business_statement_and_warns_before_c1(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    import hashlib
    import io
    import json

    from .run_support import execute

    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_classification(owner_engine, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    found = api.get(f"/api/v1/projects/{project_id}/classification", headers=headers).json()
    business = [s for s in found["statements"] if s["label"] == "business"]
    first, *rest = business
    document = {"business": len(business), "not_sliced": 0, "not_cited": 1, "statements": [
        {"file": s["file"], "line_start": s["lineStart"], "line_end": s["lineEnd"], "unit": s["unit"],
         "in_slice": True, "cited": s is not first} for s in business]}  # fmt: skip
    data = json.dumps(document).encode()
    key = f"tenants/{world.tenant_a}/projects/{project_id}/coverage.json"
    await store().put(key, io.BytesIO(data), len(data), "application/json")
    await execute(
        owner_engine,
        "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, sha256, size_bytes) "
        "SELECT tenant_id, project_id, run_id, 'docs', 'inventory/coverage.json', :k, :h, :s FROM generated_artifact "
        "WHERE project_id = :p LIMIT 1",
        k=key, h=hashlib.sha256(data).hexdigest(), s=len(data), p=project_id,
    )  # fmt: skip
    found = api.get(f"/api/v1/projects/{project_id}/classification", headers=headers).json()
    assert found["coverage"] == {"business": len(business), "notSliced": 0, "notCited": 1}
    marked = {(s["lineStart"], s["cited"]) for s in found["statements"] if s["label"] == "business"}
    assert (first["lineStart"], False) in marked
    assert all(cited for line, cited in marked if line != first["lineStart"]) or rest == []
    # ADR-0056: a business statement no rule cites blocks C1 (no rule asks the target to reproduce it); the
    # statements no slice reached stay a warning.
    check = api.get(f"/api/v1/projects/{project_id}/c1-check", headers=headers).json()
    assert check["warnings"] == []
    assert check["canApprove"] is False
    assert check["blockers"] == [
        f"1 of {len(business)} business statement(s) are cited by no rule ({first['file']}:{first['lineStart']}): "
        "extract the rules again so each one is cited, or classify the statement as infrastructure"
    ]
    where = {"file": first["file"], "lineStart": first["lineStart"], "lineEnd": first["lineEnd"]}
    assert check["uncited"] == [{**where, "unit": first["unit"]}]
    # The reviewer classifies it as infrastructure, with a reason (audited): it stops blocking and shows as theirs.
    url = f"/api/v1/projects/{project_id}/classification/overrides"
    assert api.post(url, json={"statements": [where], "reason": "corto"}, headers=headers).status_code == 422
    control = next(s for s in found["statements"] if s["label"] != "business")
    other = {"file": control["file"], "lineStart": control["lineStart"], "lineEnd": control["lineEnd"]}
    refused = api.post(url, json={"statements": [other], "reason": "Not business at all here"}, headers=headers)
    assert refused.status_code == 422, refused.text
    reason = "Error message of a table failure the business never sees"
    made = api.post(url, json={"statements": [where], "reason": reason}, headers=headers)
    assert made.status_code == 201, made.text
    assert [(o["file"], o["lineStart"], o["label"], o["reason"]) for o in made.json()] == [
        (first["file"], first["lineStart"], "infrastructure", reason)
    ]
    check = api.get(f"/api/v1/projects/{project_id}/c1-check", headers=headers).json()
    assert (check["blockers"], check["uncited"]) == ([], [])
    again = api.get(f"/api/v1/projects/{project_id}/classification", headers=headers).json()
    mine = next(s for s in again["statements"] if (s["file"], s["lineStart"]) == (first["file"], first["lineStart"]))
    assert (mine["label"], mine["overrideReason"]) == ("infrastructure", reason)
    assert again["counts"]["business"] == found["counts"]["business"] - 1
    assert again["coverage"]["notCited"] == 0
    assert api.post(
        url, json={"statements": [where], "reason": reason}, headers=sign_in(api, world.b_user)
    ).status_code in (403, 404)
    # Undone, it blocks again.
    params = {"file": first["file"], "line_start": first["lineStart"], "line_end": first["lineEnd"]}
    assert api.delete(url, params=params, headers=headers).json() == []
    assert api.get(f"/api/v1/projects/{project_id}/c1-check", headers=headers).json()["canApprove"] is False
