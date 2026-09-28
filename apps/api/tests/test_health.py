import pytest
from fastapi.testclient import TestClient

from nexti_api.health import Check
from nexti_api.main import create_app
from nexti_api.settings import Settings


async def ok() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("postgres://platform_app:hunter2@db:5432 refused")


def client(checks: dict[str, Check], app_env: str = "test") -> TestClient:
    settings = Settings(_env_file=None, app_env=app_env)
    return TestClient(create_app(settings, health_checks=checks))


def test_live_does_not_touch_dependencies() -> None:
    with client({"postgres": broken}) as c:
        assert c.get("/api/v1/health/live").json() == {"status": "ok"}


def test_ready_is_ok_when_every_dependency_answers() -> None:
    with client({"postgres": ok, "redis": ok}) as c:
        res = c.get("/api/v1/health/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert set(res.json()["checks"]) == {"postgres", "redis"}


def test_ready_is_503_and_hides_error_details() -> None:
    with client({"postgres": broken, "redis": ok}) as c:
        res = c.get("/api/v1/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "fail"
    assert body["checks"]["postgres"]["status"] == "fail"
    assert body["checks"]["redis"]["status"] == "ok"
    assert "hunter2" not in res.text


def test_default_checks_fail_when_not_configured() -> None:
    settings = Settings(_env_file=None, app_env="test")
    with TestClient(create_app(settings)) as c:
        res = c.get("/api/v1/health/ready")
    assert res.status_code == 503
    assert set(res.json()["checks"]) == {"postgres", "redis", "keycloak", "openfga", "secrets"}


def test_request_id_is_echoed_or_generated() -> None:
    with client({}) as c:
        echoed = c.get("/api/v1/health/live", headers={"X-Request-ID": "abc-123"})
        unsafe = c.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\n"})
    assert echoed.headers["x-request-id"] == "abc-123"
    assert unsafe.headers["x-request-id"] != "bad id\n"
    assert len(unsafe.headers["x-request-id"]) == 32


@pytest.mark.parametrize(("app_env", "docs_status"), [("development", 200), ("production", 404)])
def test_openapi_always_docs_only_locally(app_env: str, docs_status: int) -> None:
    with client({}, app_env=app_env) as c:
        spec = c.get("/api/v1/openapi.json")
        assert spec.status_code == 200
        assert "/api/v1/health/ready" in spec.json()["paths"]
        assert c.get("/api/v1/docs").status_code == docs_status
