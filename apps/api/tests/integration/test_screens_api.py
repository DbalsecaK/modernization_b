"""Screens and prototypes through the API (spec 4.1, 7.4, ADR-0013; plan M5 step 8): screen specs listed and edited
as versions, the design system, prototype versions served for an isolated frame with a strict CSP, their source only
with code.view, and comments anchored to a field, audited and resolvable."""

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
from .run_support import PROTOTYPE_TSX, fetch, make_project, seed_screens
from .test_runs_api import sign_in
from .test_validation_api import store


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def seeded(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_screens(owner, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


async def test_screen_specs_are_listed_and_edited_as_versions(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    screens = {s["key"]: s for s in api.get(f"{base}/screens", headers=headers).json()}
    assert set(screens) == {"SCR-PAGOMEN", "SCR-PAGOORD", "SCR-PAGORES"}
    order = screens["SCR-PAGOORD"]["data"]
    orden = next(f for f in order["fields"] if f["name"] == "ORDEN")
    assert (orden["position"], orden["length"], orden["attributes"]) == (
        {"row": 4, "column": 26}, 7, ["unprotected", "numeric", "cursor", "modified"])  # fmt: skip

    orden["message"] = "INGRESE EL NUMERO DE ORDEN"
    edited = api.put(f"{base}/screens/SCR-PAGOORD", json=order, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["origin"] == "person"
    versions = api.get(f"{base}/screens/SCR-PAGOORD/versions", headers=headers).json()
    assert [v["version"] for v in versions] == [2, 1]

    order["fields"].append({**orden, "name": "OTRO"})  # the same position as ORDEN: they overlap
    invalid = api.put(f"{base}/screens/SCR-PAGOORD", json=order, headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_screen"
    audits = await fetch(owner_engine, "SELECT action FROM audit_log WHERE target = :t ORDER BY occurred_at",
                         t=f"project:{project_id}")  # fmt: skip
    assert [a["action"] for a in audits] == ["screen.edit"]


async def test_a_prototype_page_is_served_for_an_isolated_frame_and_its_source_needs_code_view(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}"
    (version,) = api.get(f"{base}/screens/SCR-PAGOORD/prototypes", headers=headers).json()
    assert (version["version"], version["origin"], version["openComments"]) == (1, "generated", 0)
    design = api.get(f"{base}/design-system", headers=headers).json()
    assert (design["version"], design["source"]) == (1, "nexti-base")

    served = api.get(f"{base}/screens/SCR-PAGOORD/prototypes/1/page", headers=headers)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/html")
    csp = served.headers["content-security-policy"]
    for directive in ("default-src 'none'", "connect-src 'none'", "sandbox allow-scripts", "frame-ancestors 'self'"):
        assert directive in csp
    assert "allow-same-origin" not in csp
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in served.headers
    assert "document.body.dataset.ready" in served.text

    source = api.get(f"{base}/screens/SCR-PAGOORD/prototypes/1/source", headers=headers)
    assert source.status_code == 200
    assert source.text == PROTOTYPE_TSX
    assert api.get(f"{base}/screens/SCR-PAGOORD/prototypes/9/page", headers=headers).status_code == 404


async def test_comments_are_anchored_to_a_field_audited_and_resolved(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    comments = f"/api/v1/projects/{project_id}/screens/SCR-PAGOORD/prototypes/1/comments"
    created = api.post(comments, json={"body": "El valor debe mostrar decimales", "anchor": {"field": "VALOR"}},
                       headers=headers)  # fmt: skip
    assert created.status_code == 201, created.text
    comment = created.json()
    assert comment["anchor"] == {"field": "VALOR"}
    listed = api.get(comments, headers=headers).json()
    assert [(c["body"], c["resolved"]) for c in listed] == [("El valor debe mostrar decimales", False)]
    assert listed[0]["author"]
    counts = api.get(f"/api/v1/projects/{project_id}/screens/SCR-PAGOORD/prototypes", headers=headers).json()
    assert counts[0]["openComments"] == 1
    resolved = api.post(f"{comments}/{comment['id']}:resolve", json={"resolved": True}, headers=headers)
    assert resolved.json()["resolved"] is True
    assert api.post(comments, json={"body": ""}, headers=headers).status_code == 422
    audits = await fetch(owner_engine, "SELECT action FROM audit_log WHERE target = :t ORDER BY occurred_at",
                         t=f"project:{project_id}")  # fmt: skip
    assert [a["action"] for a in audits] == ["prototype.comment", "prototype.comment_resolve"]
