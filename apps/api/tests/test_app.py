from fastapi.testclient import TestClient

from nexti_api.errors import ProblemError
from nexti_api.main import create_app
from nexti_api.settings import Settings


def make_client() -> TestClient:
    app = create_app(Settings(app_env="test"))

    @app.get("/boom")
    async def boom() -> None:
        raise ProblemError(409, "tenant_slug_taken", "The tenant slug is already in use.")

    @app.get("/typed/{n}")
    async def typed(n: int) -> int:
        return n

    return TestClient(app)


def test_healthz() -> None:
    assert make_client().get("/healthz").json() == {"status": "ok"}


def test_problem_error_uses_rfc9457() -> None:
    res = make_client().get("/boom")
    assert res.status_code == 409
    assert res.headers["content-type"] == "application/problem+json"
    body = res.json()
    assert body["code"] == "tenant_slug_taken"
    assert body["title"] == "Conflict"
    assert body["instance"] == "/boom"


def test_not_found_and_validation_are_problems() -> None:
    client = make_client()
    missing = client.get("/nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    invalid = client.get("/typed/abc")
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_failed"
    assert invalid.json()["errors"][0]["loc"] == ["path", "n"]
