"""Check that the local environment is up and configured as M0 expects. Never prints secrets.

Usage: python infra/docker-compose/smoke_check.py   (after `docker compose up -d --wait`)
"""

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_env() -> dict[str, str]:
    env = {}
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            env[name.strip()] = value
    return env


def http(
    method: str, url: str, data: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})  # noqa: S310 (local URLs)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:  # noqa: S310
            raw = res.read()
            status = res.status
    except urllib.error.HTTPError as err:
        raw = err.read()
        status = err.code
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")


def compose_exec(service: str, *args: str) -> str:
    cmd = ["docker", "compose", "exec", "-T", service, *args]
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603


def main() -> int:
    env = load_env()
    kc = f"http://localhost:{env['KEYCLOAK_PORT']}/realms/nexti"
    kc_admin = f"http://localhost:{env['KEYCLOAK_PORT']}/admin/realms/nexti"
    token_url = f"{kc}/protocol/openid-connect/token"
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            failures.append(name)

    status, discovery = http("GET", f"{kc}/.well-known/openid-configuration")
    check(
        "keycloak: realm nexti publishes OIDC discovery",
        status == 200 and "S256" in discovery.get("code_challenge_methods_supported", []),
    )

    status, token = http(
        "POST",
        token_url,
        {
            "grant_type": "client_credentials",
            "client_id": "nexti-admin",
            "client_secret": env["KC_ADMIN_CLIENT_SECRET"],
        },
    )
    check("keycloak: admin service account authenticates (secret placeholder resolved)", status == 200)
    auth = {"Authorization": f"Bearer {token.get('access_token', '')}"} if status == 200 else {}

    status, users = http("GET", f"{kc_admin}/users?briefRepresentation=true&max=50", headers=auth)
    emails = sorted(u.get("email", "") for u in users) if status == 200 else []
    check("keycloak: 5 fictitious dev users imported", len([e for e in emails if e.endswith(".example")]) == 5)
    status, _ = http("GET", f"{kc_admin}/events?max=1", headers=auth)
    check("keycloak: service account can read events (audit)", status == 200)
    status, _ = http("GET", f"{kc_admin}/clients", headers=auth)
    check("keycloak: service account cannot read clients (least privilege)", status == 403)

    status, body = http(
        "POST",
        token_url,
        {
            "grant_type": "password",
            "client_id": "nexti-bff",
            "client_secret": env["KC_BFF_CLIENT_SECRET"],
            "username": "admin@nexti.example",
            "password": env["KC_DEV_USER_PASSWORD"],
        },
    )
    # Keycloak answers `unauthorized_client` both for a bad secret and for a disabled grant; the description tells
    # them apart, so this also proves the BFF secret placeholder was resolved.
    check(
        "keycloak: BFF client authenticates but the password grant is disabled (code + PKCE only)",
        "direct access" in str(body.get("error_description", "")).lower(),
    )
    status, body = http(
        "POST", token_url, {"grant_type": "client_credentials", "client_id": "nexti-bff", "client_secret": "wrong"}
    )
    check(
        "keycloak: BFF client rejects a wrong secret",
        status == 401 and "invalid client credentials" in str(body.get("error_description", "")).lower(),
    )

    fga = f"http://localhost:{env['OPENFGA_HTTP_PORT']}"
    check("openfga: rejects calls without the preshared key", http("GET", f"{fga}/stores")[0] == 401)
    check(
        "openfga: accepts the preshared key",
        http("GET", f"{fga}/stores", headers={"Authorization": f"Bearer {env['OPENFGA_API_KEY']}"})[0] == 200,
    )

    roles = compose_exec(
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "platform",
        "-tAc",
        "SELECT rolname || ':' || rolbypassrls || ':' || rolsuper FROM pg_roles "
        "WHERE rolname IN ('platform_app','authz_relay') ORDER BY 1",
    )
    check(
        "postgres: runtime roles have neither BYPASSRLS nor SUPERUSER",
        roles.splitlines() == ["authz_relay:false:false", "platform_app:false:false"],
    )
    dbs = compose_exec(
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-tAc",
        "SELECT string_agg(datname, ',' ORDER BY datname) FROM pg_database WHERE NOT datistemplate",
    )
    check("postgres: one database per service", dbs == "keycloak,langfuse,openfga,platform,postgres")

    pong = compose_exec("redis", "sh", "-c", 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping')
    check("redis: answers with its password", pong == "PONG")
    status, _ = http("GET", f"http://localhost:{env['MINIO_API_PORT']}/minio/health/live")
    check("minio: live", status == 200)
    status, _ = http("GET", f"http://localhost:{env['MAILPIT_UI_PORT']}/api/v1/info")
    check("mailpit: API up", status == 200)

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
