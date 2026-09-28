"""M0 acceptance: the API does not start with dev-auth outside development/test."""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from nexti_api.auth.dev_auth import DevAuthDisabledError
from nexti_api.main import create_app
from nexti_api.settings import Settings


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_create_app_refuses_dev_auth_outside_local(app_env: str) -> None:
    with pytest.raises(DevAuthDisabledError, match="only exists in development and test"):
        create_app(Settings(_env_file=None, app_env=app_env, dev_auth_enabled=True))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_server_process_does_not_start(app_env: str) -> None:
    env = {**os.environ, "APP_ENV": app_env, "DEV_AUTH_ENABLED": "true"}
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "--factory", "nexti_api.main:create_app", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "DEV_AUTH_ENABLED=true is not allowed" in result.stderr


@pytest.mark.parametrize(("enabled", "present"), [(True, True), (False, False)])
def test_dev_routes_exist_only_when_enabled(enabled: bool, present: bool) -> None:
    app = create_app(Settings(_env_file=None, app_env="development", dev_auth_enabled=enabled))
    with TestClient(app) as client:
        paths = client.get("/api/v1/openapi.json").json()["paths"]
        assert ("/auth/dev/login" in paths) is present
        if not present:
            assert (
                client.post("/auth/dev/login", json={"userId": "00000000-0000-0000-0000-000000000000"}).status_code
                == 404
            )
