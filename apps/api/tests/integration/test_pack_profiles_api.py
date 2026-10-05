"""Pack profiles (ADR-0040): a tenant keeps profiles, its catalog offers them as the `pack_profile` preference, a
project may choose one, and another tenant never sees it."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .test_runs_api import sign_in

TARGET = {"architecture": "mvc", "backend": "spring-boot", "frontend": "none", "database": "postgresql", "cloud": "aws"}


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def test_a_pack_profile_becomes_a_preference_of_the_tenant_only(
    api: TestClient, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    key = f"bank-{uuid.uuid4().hex[:6]}"
    bad = api.post("/api/v1/pack-profiles", json={"key": key, "name": "Bank", "packageRoot": "Com.Bank"},
                   headers=headers)  # fmt: skip
    assert bad.status_code == 422
    created = api.post("/api/v1/pack-profiles", json={
        "key": key, "name": "Bank standard", "backend": "spring-boot", "packageRoot": "com.andesbank",
        "conventions": "Money as BigDecimal; one service per use case."}, headers=headers)  # fmt: skip
    assert created.status_code == 201, created.text
    assert created.json()["packageRoot"] == "com.andesbank"
    again = api.post("/api/v1/pack-profiles", json={"key": key, "name": "Bank"}, headers=headers)
    assert (again.status_code, again.json()["code"]) == (409, "pack_profile_exists")

    catalog = api.get("/api/v1/catalog", headers=headers).json()
    assert {"group": "pack_profile", "key": key, "name": "Bank standard", "default": False} in catalog["preferences"]
    proposal = api.post("/api/v1/projects:compose", json={
        "flow": "modernization", "sources": ["cobol"], "target": {**TARGET, "preferences": {"pack_profile": key}}},
        headers=headers)  # fmt: skip
    assert proposal.status_code == 200, proposal.text
    assert [p for p in proposal.json()["problems"] if p["code"] == "unknown_preference"] == []
    unknown = api.post("/api/v1/projects:compose", json={
        "flow": "modernization", "sources": ["cobol"], "target": {**TARGET, "preferences": {"pack_profile": "nope"}}},
        headers=headers)  # fmt: skip
    assert {"code": "unknown_preference", "subject": "pack_profile:nope"} in unknown.json()["problems"]

    other = sign_in(api, world.b_user)
    assert key not in [p["key"] for p in api.get("/api/v1/catalog", headers=other).json()["preferences"]]
    headers = sign_in(api, world.a_user)
    assert api.delete(f"/api/v1/pack-profiles/{created.json()['id']}", headers=headers).status_code == 204
    assert key not in [p["key"] for p in api.get("/api/v1/catalog", headers=headers).json()["preferences"]]
