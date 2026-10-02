"""Offline license in the API (ADR-0030): a valid license enables; a missing, expired, tampered, foreign-key or
exceeded one leaves the platform read-only (reads work, runs/projects/tenants are refused with a stable code and the
refusal is audited); without a license configured nothing changes."""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core import license as lic
from nexti_core import signing
from nexti_core.db.models import AppUser, AuditLog, PlatformRoleAssignment, Tenant

from .conftest import World
from .run_support import make_config, make_project
from .test_endpoints_authz import CONFIG

KEY = Ed25519PrivateKey.generate()  # generated at run time; never stored
NOW = datetime.now(UTC)


def write_license(
    tmp_path: Path,
    *,
    expires: datetime = NOW + timedelta(days=30),
    max_tenants: int = 1000,
    max_projects: int = 1000,
    signer: Ed25519PrivateKey = KEY,
) -> Path:
    data, signature = lic.issue(
        signer, customer="Andes Bank", deployment_profile="air-gapped", expires_at=expires, max_tenants=max_tenants,
        max_projects=max_projects, features=["modernization"], issued_at=NOW - timedelta(days=60),
    )  # fmt: skip
    path = tmp_path / f"license-{uuid.uuid4().hex[:6]}.json"
    path.write_bytes(data)
    lic.signature_path(path).write_text(signature)
    return path


@contextmanager
def client(settings: Settings, license_file: Path | None, public_key: str | None = None) -> Iterator[TestClient]:
    update: dict[str, Any] = {"dev_auth_enabled": True}
    if license_file is not None:
        update |= {"license_file": str(license_file),
                   "license_public_key": public_key or signing.raw_public(KEY.public_key())}  # fmt: skip
    with TestClient(create_app(settings.model_copy(update=update)), base_url="https://testserver") as api:
        yield api


def sign_in(api: TestClient, user: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


@pytest.fixture(scope="module")
async def root(owner_engine: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        user_id: uuid.UUID = (
            await conn.execute(
                insert(AppUser)
                .values(email=f"m15test-root-{uuid.uuid4().hex[:6]}@example.test", display_name="Root")
                .returning(AppUser.id)
            )
        ).scalar_one()
        await conn.execute(insert(PlatformRoleAssignment).values(user_id=user_id, role="superAdmin"))
    await reconcile(app_engine, fga)  # publish the platform role to OpenFGA
    return user_id


@pytest.fixture
async def fresh_project(owner_engine: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner_engine, world.tenant_a)
    await make_config(owner_engine, world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


async def denials(owner: AsyncEngine) -> int:
    async with owner.connect() as conn:
        query = select(func.count()).select_from(AuditLog).where(AuditLog.action.like("%.license_denied"))
        return int((await conn.execute(query)).scalar_one())


async def tenant_count(owner: AsyncEngine) -> int:
    async with owner.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(Tenant))).scalar_one())


def new_tenant() -> dict[str, str]:
    return {"slug": f"m15-{uuid.uuid4().hex[:8]}", "name": "License test tenant"}


def assert_read_only(response: Any, state: str, reason: str) -> None:
    assert response.status_code == 403, response.text
    body = response.json()
    assert (body["code"], body["state"], body["reason"]) == ("license_read_only", state, reason)


async def test_no_license_configured_changes_nothing(api_settings: Settings, root: uuid.UUID) -> None:
    with client(api_settings, None) as api:
        sign_in(api, root)
        found = api.get("/api/v1/platform/status").json()["license"]
        assert (found["state"], found["readOnly"], found["customer"]) == ("not_required", False, None)


async def test_valid_license_enables_and_is_shown(
    api_settings: Settings, root: uuid.UUID, world: World, owner_engine: AsyncEngine, tmp_path: Path
) -> None:
    with client(api_settings, write_license(tmp_path)) as api:  # the world: two tenants with a project each
        headers = sign_in(api, root)
        found = api.get("/api/v1/platform/status").json()["license"]
        assert (found["state"], found["readOnly"], found["customer"], found["maxProjects"]) == (
            "valid", False, "Andes Bank", 1000)  # fmt: skip
        assert found["tenants"] >= 2
        assert found["projects"] >= 2
        assert api.post("/api/v1/tenants", json=new_tenant(), headers=headers).status_code == 201
    async with owner_engine.connect() as conn:
        verified = await conn.execute(
            text(
                "SELECT outcome FROM audit_log WHERE action = 'license.verify' AND tenant_id IS NULL "
                "ORDER BY seq DESC LIMIT 1"
            )
        )
        assert verified.scalar_one() == "success"


@pytest.mark.parametrize("case", ["expired", "tampered", "foreign_key", "missing"])
async def test_bad_license_makes_the_platform_read_only(
    case: str,
    api_settings: Settings,
    root: uuid.UUID,
    world: World,
    owner_engine: AsyncEngine,
    fresh_project: uuid.UUID,
    tmp_path: Path,
) -> None:
    path = write_license(tmp_path, expires=NOW - timedelta(days=1) if case == "expired" else NOW + timedelta(days=30))
    public_key = None
    if case == "tampered":
        body = json.loads(path.read_text())
        body["max_projects"] = 100000
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    elif case == "foreign_key":
        public_key = signing.raw_public(Ed25519PrivateKey.generate().public_key())
    elif case == "missing":
        path = tmp_path / "absent.json"
    state, reason = {
        "expired": ("expired", "expired"),
        "tampered": ("invalid", "bad_signature"),
        "foreign_key": ("invalid", "bad_signature"),
        "missing": ("missing", "file_not_found"),
    }[case]
    before = await denials(owner_engine)
    with client(api_settings, path, public_key) as api:
        headers = sign_in(api, root)
        found = api.get("/api/v1/platform/status").json()["license"]
        assert (found["state"], found["reason"], found["readOnly"]) == (state, reason, True)
        assert api.get("/api/v1/tenants").status_code == 200
        assert_read_only(api.post("/api/v1/tenants", json=new_tenant(), headers=headers), state, reason)

        headers = sign_in(api, world.a_user)  # tenant administrator of tenant A
        assert api.get("/api/v1/projects").status_code == 200
        assert api.get(f"/api/v1/projects/{fresh_project}/runs").status_code == 200
        started = api.post(f"/api/v1/projects/{fresh_project}/runs", json={"kind": "pipeline"}, headers=headers)
        assert_read_only(started, state, reason)
        project = {**CONFIG, "name": "Blocked", "flow": "modernization"}
        created = api.post("/api/v1/projects", json=project, headers=headers)
        assert_read_only(created, state, reason)
    assert await denials(owner_engine) == before + 3


async def test_over_max_projects_is_read_only_and_reaching_a_limit_refuses_more(
    api_settings: Settings,
    root: uuid.UUID,
    world: World,
    owner_engine: AsyncEngine,
    fresh_project: uuid.UUID,
    tmp_path: Path,
) -> None:
    with client(api_settings, write_license(tmp_path, max_projects=1)) as api:  # the world already has more
        headers = sign_in(api, world.a_user)
        started = api.post(f"/api/v1/projects/{fresh_project}/runs", json={"kind": "pipeline"}, headers=headers)
        assert_read_only(started, "over_limits", "max_projects")
        assert api.get("/api/v1/projects").status_code == 200

    tenants = await tenant_count(owner_engine)
    with client(api_settings, write_license(tmp_path, max_tenants=tenants)) as api:
        headers = sign_in(api, root)
        assert api.get("/api/v1/platform/status").json()["license"]["state"] == "valid"
        refused = api.post("/api/v1/tenants", json=new_tenant(), headers=headers)
        assert refused.status_code == 403
        assert (refused.json()["code"], refused.json()["reason"]) == ("license_limit_reached", "max_tenants")
