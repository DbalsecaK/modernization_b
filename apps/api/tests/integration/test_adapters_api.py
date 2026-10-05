"""The adapter studio (ADR-0039): a tenant declares an adapter, tries it on samples, the catalog of that tenant
lists it as experimental with its source option, a project can be composed on it, and another tenant never sees it."""

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


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


SPEC = {
    "key": "toy-lang",
    "name": "Toy language",
    "extensions": [".toy"],
    "comment_prefixes": ["--"],
    "unit": r"^\s*PROCEDURE\s+(?P<name>\w+)",
    "call": r"\bCALL\s+(?P<callee>\w+)",
    "reads": [r"\bFROM\s+(?P<table>[\w.]+)"],
    "writes": [r"\bUPDATE\s+(?P<table>[\w.]+)"],
    "infrastructure_keywords": ["LOG"],
    "control_keywords": ["IF"],
    "type_map": {},
}
SAMPLE = {
    "path": "pay.toy",
    "text": "PROCEDURE pay\n  SELECT a FROM db.t\n  IF a > 1\n  LOG 'x'\n  UPDATE db.t\n  CALL post\n",
}


async def test_a_declared_adapter_is_tried_saved_listed_in_the_catalog_and_private_to_its_tenant(
    api: TestClient, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    tried = api.post("/api/v1/adapters:try", json={"spec": SPEC, "samples": [SAMPLE]}, headers=headers)
    assert tried.status_code == 200, tried.text
    found = tried.json()["summary"]
    assert (found["metrics"]["programs"], found["tables"], found["calls"]) == (1, ["db.t"], ["post"])
    assert found["classification"] == {"business": 3, "control_flow": 1, "infrastructure": 1}

    bad = api.post("/api/v1/adapters", json={"spec": {**SPEC, "unit": "PROCEDURE (\\w+)"}}, headers=headers)
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_adapter_spec")
    taken = api.post("/api/v1/adapters", json={"spec": {**SPEC, "key": "sybase-sp"}}, headers=headers)
    assert (taken.status_code, taken.json()["code"]) == (422, "adapter_key_taken")

    key = f"toy-{uuid.uuid4().hex[:6]}"
    created = api.post("/api/v1/adapters", json={"spec": {**SPEC, "key": key}}, headers=headers)
    assert created.status_code == 201, created.text
    assert (created.json()["key"], created.json()["level"]) == (key, "experimental")
    again = api.post("/api/v1/adapters", json={"spec": {**SPEC, "key": key}}, headers=headers)
    assert (again.status_code, again.json()["code"]) == (409, "adapter_exists")
    assert key in [a["key"] for a in api.get("/api/v1/adapters", headers=headers).json()]

    catalog = api.get("/api/v1/catalog", headers=headers).json()
    adapter = next(a for a in catalog["adapters"] if a["key"] == key)
    assert (adapter["level"], adapter["validation"]) == ("experimental", "none")
    option = next(s for s in catalog["sources"] if s["key"] == key)
    assert (option["adapter"], sorted(option["flows"])) == (key, ["independentValidation", "modernization"])
    proposal = api.post("/api/v1/projects:compose", json={
        "flow": "modernization", "sources": [key],
        "target": {"architecture": "mvc", "backend": "spring-boot", "frontend": "none", "database": "postgresql",
                   "cloud": "aws"}}, headers=headers)  # fmt: skip
    assert proposal.status_code == 200, proposal.text
    assert [p for p in proposal.json()["problems"] if p["code"] == "unknown_source"] == []

    deleted = api.delete(f"/api/v1/adapters/{created.json()['id']}", headers=headers)
    assert deleted.status_code == 204
    assert key not in [a["key"] for a in api.get("/api/v1/catalog", headers=headers).json()["adapters"]]

    # Another tenant's catalog does not list it.
    other = sign_in(api, world.b_user)
    assert key not in [a["key"] for a in api.get("/api/v1/catalog", headers=other).json()["adapters"]]
    headers = sign_in(api, world.a_user)
    assert key not in [a["key"] for a in api.get("/api/v1/catalog", headers=headers).json()["adapters"]]
