"""dev-auth against the real database and Redis: same session as the BFF, audited as dev-auth."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import SETTINGS, World


@pytest.fixture
def client(api_settings: Settings) -> Iterator[TestClient]:
    settings = api_settings.model_copy(update={"dev_auth_enabled": True})
    with TestClient(create_app(settings), base_url="https://testserver") as c:
        yield c


async def test_sign_in_as_a_seeded_user(client: TestClient, world: World, owner_engine: AsyncEngine) -> None:
    users = client.get("/auth/dev/users").json()
    assert str(world.a_user) in {u["id"] for u in users}

    res = client.post("/auth/dev/login", json={"userId": str(world.a_user)}, headers={"Origin": SETTINGS.web_origin})
    assert res.status_code == 204
    assert res.cookies.get("__Host-nexti_session")

    me = client.get("/api/v1/me").json()
    assert me["authMethod"] == "dev-auth"
    assert me["activeTenant"]["id"] == str(world.tenant_a)

    async with owner_engine.connect() as conn:
        kinds: set[str] = set(
            (
                await conn.execute(
                    text("SELECT actor_kind FROM audit_log WHERE action = 'auth.login' AND actor_id = :u"),
                    {"u": world.a_user},
                )
            ).scalars()
        )
        assert "dev-auth" in kinds

    assert client.post("/auth/logout", headers={"X-CSRF-Token": me["csrfToken"]}).status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_unknown_user_and_foreign_origin_are_refused(client: TestClient) -> None:
    unknown = client.post("/auth/dev/login", json={"userId": str(uuid.uuid4())})
    assert unknown.json()["code"] == "user_not_found"
    foreign = client.post(
        "/auth/dev/login", json={"userId": str(uuid.uuid4())}, headers={"Origin": "https://evil.example"}
    )
    assert foreign.json()["code"] == "origin_not_allowed"
