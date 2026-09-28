"""Gateway tests. Those that need a local service read it from infra/docker-compose/.env and skip without it."""

from pathlib import Path

import pytest

COMPOSE_ENV = Path(__file__).resolve().parents[3] / "infra" / "docker-compose" / ".env"


def compose_env() -> dict[str, str]:
    if not COMPOSE_ENV.exists():
        return {}
    values = {}
    for line in COMPOSE_ENV.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            values[name.strip()] = value
    return values


ENV = compose_env()
needs_openbao = pytest.mark.skipif(not ENV.get("OPENBAO_DEV_ROOT_SECRET"), reason="OpenBao not configured")
