"""Readiness against the real local services (docker compose). Skipped when apps/api/.env is not configured."""

import pytest
from fastapi.testclient import TestClient

from nexti_api.main import create_app
from nexti_api.settings import Settings

settings = Settings(app_env="test")
pytestmark = pytest.mark.skipif(
    not settings.database_url.get_secret_value(), reason="local services not configured (run init_env.py)"
)


def test_ready_with_every_local_service() -> None:
    with TestClient(create_app(settings)) as c:
        res = c.get("/api/v1/health/ready")
    assert res.json()["checks"] == {
        name: {"status": "ok", "latency_ms": res.json()["checks"][name]["latency_ms"]}
        for name in ("postgres", "redis", "keycloak", "openfga", "secrets")
    }
    assert res.status_code == 200
