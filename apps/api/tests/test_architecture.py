"""The model gateway is the only way to a model provider or to the secrets store (CLAUDE.md, ADR-0007, spec 12).

Outside packages/model_gateway, production code may use the gateway facade (service), its errors and call context
(gateway) and its pure rules (rules), never the provider client or the secrets store; and no other code talks to
OpenRouter or OpenBao on its own.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / "packages" / "model_gateway"
ALLOWED = {"nexti_model_gateway.service", "nexti_model_gateway.gateway", "nexti_model_gateway.rules"}
# Signs of a direct call to the provider or the secrets store.
FORBIDDEN_TEXT = ("openrouter.ai/api", "X-Vault-Token", "/v1/secret/data")


def production_python() -> list[Path]:
    roots = [ROOT / "apps", ROOT / "packages"]
    files = [p for r in roots for p in r.rglob("*.py")]
    return [
        p
        for p in files
        if GATEWAY not in p.parents
        and not {"tests", ".venv", "node_modules", "migrations", "__pycache__"} & set(p.relative_to(ROOT).parts)
    ]


def gateway_imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return {m for m in found if m == "nexti_model_gateway" or m.startswith("nexti_model_gateway.")}


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
    sources = [*production_python(), *[p for p in web.rglob("*") if p.suffix in {".ts", ".tsx"}]]
    offenders = sorted(
        f"{p.relative_to(ROOT)}: {needle}"
        for p in sources
        for needle in FORBIDDEN_TEXT
        if needle in p.read_text(encoding="utf-8")
    )
    assert offenders == []
