"""Local models through the API (M15, ADR-0030): an openai-compatible connection with its base URL, models entered by
hand or listed by the server, visible only to the tenant, and the air-gapped switches."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import AuditLog, ModelOffering
from nexti_core.db.session import DbScope, scoped_connection

from .conftest import World

PUBLIC_SERVER = "https://llm.andesbank.example/v1"
PRIVATE_SERVER = "http://vllm.internal:8000/v1"
HOSTS = {"llm.andesbank.example": "93.184.216.34", "vllm.internal": "10.0.4.7", "localhost": "127.0.0.1"}


async def _resolve(host: str, port: int) -> list[str]:
    return [HOSTS[host]] if host in HOSTS else []


@contextmanager
def client(settings: Settings, **overrides: object) -> Iterator[TestClient]:
    app = create_app(settings.model_copy(update={"dev_auth_enabled": True, **overrides}))
    with TestClient(app, base_url="https://testserver") as api:
        api.app.state.inputs.git_resolver = _resolve  # type: ignore[attr-defined]
        yield api


def sign_in(api: TestClient, user: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


def new_local(api: TestClient, headers: dict[str, str], base_url: str) -> object:
    body = {"provider": "openai-compatible", "name": f"vLLM {uuid.uuid4().hex[:8]}", "baseUrl": base_url}
    return api.post("/api/v1/ai/connections", json=body, headers=headers)


async def test_a_local_connection_its_models_and_a_profile_on_them(
    api_settings: Settings, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    with client(api_settings) as api, respx.mock(assert_all_called=False) as router:
        router.get(f"{PUBLIC_SERVER}/models").respond(json={"data": [{"id": "llama-3.1-8b", "max_model_len": 8192}]})
        router.route().pass_through()
        headers = sign_in(api, world.a_user)

        created = new_local(api, headers, PUBLIC_SERVER + "/")
        assert created.status_code == 201, created.text  # type: ignore[attr-defined]
        connection = created.json()  # type: ignore[attr-defined]
        assert (connection["provider"], connection["baseUrl"], connection["hasCredential"]) == (
            "openai-compatible",
            PUBLIC_SERVER,
            False,
        )
        tested = api.post(f"/api/v1/ai/connections/{connection['id']}:test", headers=headers).json()
        assert tested["status"] == "ok", tested
        served = api.get(f"/api/v1/ai/connections/{connection['id']}/served-models").json()
        assert served == [{"slug": "llama-3.1-8b", "contextWindow": 8192}]

        model = {"slug": "llama-3.1-8b", "contextWindow": 8192, "inputPerMtok": "0.10", "outputPerMtok": "0.20"}
        added = api.post(f"/api/v1/ai/connections/{connection['id']}/models", json=model, headers=headers)
        assert added.status_code == 201, added.text
        offering_id = added.json()["offeringId"]
        alias = {"slug": "llama-latest"}
        refused = api.post(f"/api/v1/ai/connections/{connection['id']}/models", json=alias, headers=headers)
        assert refused.json()["code"] == "alias_not_allowed"

        catalog = api.get("/api/v1/ai/catalog", params={"search": "llama-3.1-8b"}).json()
        [offering] = [o for v in catalog for o in v["offerings"] if o["id"] == offering_id]
        assert offering["provider"] == "openai-compatible"
        assert offering["connectionId"] == connection["id"]
        assert offering["price"]["inputPerMtok"] == "0.100000"
        assert offering["allowedByPolicy"] is True

        # A local model only through its own server.
        other = new_local(api, headers, PUBLIC_SERVER).json()  # type: ignore[attr-defined]
        profile = {"name": f"Local {uuid.uuid4().hex[:6]}", "offeringId": offering_id, "maxOutputTokens": 512}
        mismatch = api.post("/api/v1/ai/profiles", json={**profile, "connectionId": other["id"]}, headers=headers)
        assert mismatch.json()["code"] == "offering_connection_mismatch"
        ok = api.post("/api/v1/ai/profiles", json={**profile, "connectionId": connection["id"]}, headers=headers)
        assert ok.status_code == 201, ok.text

        # Deleting the second connection (no profile, no usage) takes nothing else with it.
        assert api.delete(f"/api/v1/ai/connections/{other['id']}", headers=headers).status_code == 204
    async with owner_engine.connect() as conn:
        actions = set(
            (
                await conn.execute(
                    select(AuditLog.action).where(AuditLog.target == f"offering:{offering_id}")
                )
            ).scalars()
        )  # fmt: skip
    assert "ai.local_model_add" in actions
    # Tenant B does not see it (RLS).
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_b)) as conn:
        hidden = (await conn.execute(select(ModelOffering.id).where(ModelOffering.id == offering_id))).first()
    assert hidden is None


async def test_base_urls_are_checked_against_ssrf(
    api_settings: Settings, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    with client(api_settings) as api:
        headers = sign_in(api, world.a_user)
        codes = {
            url: new_local(api, headers, url).json().get("code")  # type: ignore[attr-defined]
            for url in (PRIVATE_SERVER, "http://llm.andesbank.example/v1", "https://u:p@llm.andesbank.example/v1",
                        "https://nowhere.example/v1", "ftp://llm.andesbank.example/v1")
        }  # fmt: skip
        missing = api.post(
            "/api/v1/ai/connections", json={"provider": "openai-compatible", "name": "x"}, headers=headers
        )
    assert codes == {
        PRIVATE_SERVER: "host_not_allowed",
        "http://llm.andesbank.example/v1": "base_url_not_https",
        "https://u:p@llm.andesbank.example/v1": "invalid_base_url",
        "https://nowhere.example/v1": "host_unresolved",
        "ftp://llm.andesbank.example/v1": "invalid_base_url",
    }
    assert missing.json()["code"] == "base_url_required"

    with client(api_settings, model_servers_allow_private_hosts=True) as api:
        headers = sign_in(api, world.a_user)
        assert new_local(api, headers, PRIVATE_SERVER).status_code == 201  # type: ignore[attr-defined]
        assert new_local(api, headers, "http://localhost:11434/v1").status_code == 201  # type: ignore[attr-defined]
        public_http = new_local(api, headers, "http://llm.andesbank.example/v1").json()  # type: ignore[attr-defined]
    assert public_http["code"] == "base_url_not_https"


async def test_air_gapped_turns_off_openrouter_and_figma_but_not_local_models(
    api_settings: Settings, app_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    await reconcile(app_engine, fga)
    with client(api_settings, openrouter_enabled=False, figma_url="", model_servers_allow_private_hosts=True) as api:
        headers = sign_in(api, world.a_user)
        openrouter = {"name": f"OR {uuid.uuid4().hex[:8]}", "apiKey": "placeholder-not-a-key"}
        assert api.post("/api/v1/ai/connections", json=openrouter, headers=headers).json()["code"] == (
            "openrouter_disabled"
        )
        assert api.post("/api/v1/ai/catalog:sync", headers=headers).json()["code"] == "openrouter_disabled"
        assert new_local(api, headers, PRIVATE_SERVER).status_code == 201  # type: ignore[attr-defined]
        figma = {"kind": "figma", "name": f"Figma {uuid.uuid4().hex[:8]}", "token": "figd_airgapped"}
        integration = api.post("/api/v1/integrations", json=figma, headers=headers).json()
        tested = api.post(f"/api/v1/integrations/{integration['id']}:test", headers=headers).json()
    assert tested["status"] == "failed"
    assert "air-gapped" in tested["lastTestDetail"]
