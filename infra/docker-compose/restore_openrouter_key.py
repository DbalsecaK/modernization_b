"""Development only: put the OpenRouter test key back into every OpenRouter connection of the local platform.

OpenBao runs in dev mode in the local compose (secrets in memory), so recreating its container loses the provider
credentials and every run fails with ProviderCallError: missing_credential. This script signs in with the
development login as the first platform admin it finds, rotates the key of each OpenRouter connection with
OPENROUTER_API_KEY_FOR_TESTS from infra/docker-compose/.env and tests the connection. It never prints the key.

Usage (from the repository root, with the API running):
    .venv/Scripts/python.exe infra/docker-compose/restore_openrouter_key.py [--api http://127.0.0.1:8100]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def _test_key() -> str:
    env = ROOT / "infra" / "docker-compose" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY_FOR_TESTS="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("OPENROUTER_API_KEY_FOR_TESTS is not set in infra/docker-compose/.env")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8100")
    parser.add_argument("--user", default=None, help="user id for the development login (default: the seeded admin)")
    args = parser.parse_args()
    key = _test_key()
    client = httpx.Client(base_url=args.api, timeout=60)
    user = args.user or "0ae57647-fdb0-4d42-8a1c-5f3ccdcad18a"
    login = client.post("/auth/dev/login", json={"userId": user})
    if login.status_code != 204:
        print(f"development login refused ({login.status_code}): is the API local and running?")
        return 2
    headers = {"Cookie": f"__Host-nexti_session={login.cookies.get('__Host-nexti_session')}"}
    headers["X-CSRF-Token"] = client.get("/api/v1/me", headers=headers).json()["csrfToken"]
    connections = client.get("/api/v1/ai/connections", headers=headers).json()
    restored = 0
    for connection in connections:
        if connection.get("provider") != "openrouter":
            continue
        rotated = client.patch(f"/api/v1/ai/connections/{connection['id']}", headers=headers, json={"apiKey": key})
        tested = client.post(f"/api/v1/ai/connections/{connection['id']}:test", headers=headers)
        status = tested.json().get("status") if tested.status_code < 400 else f"test failed {tested.status_code}"
        print(f"{connection.get('name')}: rotate {rotated.status_code}, connection {status}")
        restored += rotated.status_code == 200
    if not restored:
        print("no OpenRouter connection found for the active tenant")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
