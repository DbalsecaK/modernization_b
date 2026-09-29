"""The model gateway is the only way to a model provider, and one module is the only way to the secrets store
(CLAUDE.md, ADR-0007, spec 12).

Outside packages/model_gateway, production code may use the gateway facade (service), its errors and call context
(gateway) and its pure rules (rules), never the provider client or the gateway's credential paths. The secrets store
client (`nexti_core.secrets`) is used only by the gateway and by the project repository module (the Git token, M2);
no other code talks to OpenRouter or OpenBao on its own.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / "packages" / "model_gateway"
ALLOWED = {"nexti_model_gateway.service", "nexti_model_gateway.gateway", "nexti_model_gateway.rules"}
# Signs of a direct call to the provider or the secrets store.
FORBIDDEN_TEXT = ("openrouter.ai/api", "X-Vault-Token", "/v1/secret/data")
SECRETS_CLIENT = ROOT / "packages" / "core" / "src" / "nexti_core" / "secrets.py"
SECRETS_USERS = {ROOT / "apps" / "api" / "src" / "nexti_api" / "projects" / "repository.py"}


def production_python() -> list[Path]:
    roots = [ROOT / "apps", ROOT / "packages"]
    files = [p for r in roots for p in r.rglob("*.py")]
    return [
        p
        for p in files
        if GATEWAY not in p.parents
        and not {"tests", ".venv", "node_modules", "migrations", "__pycache__"} & set(p.relative_to(ROOT).parts)
    ]


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def gateway_imports(path: Path) -> set[str]:
    return {m for m in imports(path) if m == "nexti_model_gateway" or m.startswith("nexti_model_gateway.")}


def test_the_scan_sees_the_api() -> None:
    files = production_python()
    # Guard against a silent pass: the API and its AI routers are in the list.
    assert any(p.name == "connections.py" for p in files)
    assert all(GATEWAY not in p.parents for p in files)


def test_only_the_gateway_facade_is_imported_outside_the_gateway() -> None:
    offenders = {
        str(p.relative_to(ROOT)): sorted(bad) for p in production_python() if (bad := gateway_imports(p) - ALLOWED)
    }
    assert offenders == {}, "use nexti_model_gateway.service instead of the provider client or the secrets store"


def test_no_code_outside_the_gateway_calls_the_provider_or_the_secrets_store() -> None:
    web = ROOT / "apps" / "web" / "src"
    sources = [
        *[p for p in production_python() if p != SECRETS_CLIENT],
        *[p for p in web.rglob("*") if p.suffix in {".ts", ".tsx"}],
    ]
    offenders = sorted(
        f"{p.relative_to(ROOT)}: {needle}"
        for p in sources
        for needle in FORBIDDEN_TEXT
        if needle in p.read_text(encoding="utf-8")
    )
    assert offenders == []


def test_only_the_repository_module_uses_the_secrets_client_outside_the_gateway() -> None:
    offenders = sorted(
        str(p.relative_to(ROOT))
        for p in production_python()
        if "nexti_core.secrets" in imports(p) and p not in SECRETS_USERS
    )
    assert offenders == []
    assert SECRETS_CLIENT.is_file()
