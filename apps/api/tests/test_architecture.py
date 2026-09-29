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
SECRETS_USERS = {
    ROOT / "apps" / "api" / "src" / "nexti_api" / "projects" / "repository.py",
    # The worker's preflight resolves the repository token (read only) to check the repository (spec 11.1).
    ROOT / "apps" / "worker" / "src" / "nexti_worker" / "probe.py",
    ROOT / "apps" / "worker" / "src" / "nexti_worker" / "runner.py",
    ROOT / "apps" / "worker" / "src" / "nexti_worker" / "__main__.py",
}


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


ENGINE_MODULES = ("langgraph", "procrastinate", "nexti_orchestration", "nexti_worker", "nexti_sandbox")


def test_the_api_never_runs_agents() -> None:
    """The API creates runs and enqueues them; the worker executes them (CLAUDE.md rule 3, plan M3)."""
    api = ROOT / "apps" / "api" / "src"
    offenders = sorted(
        f"{p.relative_to(ROOT)}: {m}"
        for p in api.rglob("*.py")
        for m in imports(p)
        if m.split(".")[0] in ENGINE_MODULES
    )
    assert offenders == []


# Objects of the customer's reference application (ADR-0011): they may only exist in the local reference kit.
REFERENCE_KIT_MARKERS = ("db_biz_pagos", "db_sat_his", "db_biz_admempresa", "bp_total_orden", "sp_debcred")
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".sp", ".sql", ".json", ".yaml", ".yml", ".feature", ".csv", ".txt"}


def test_no_customer_reference_code_is_in_the_repository() -> None:
    import shutil
    import subprocess

    git = shutil.which("git")
    assert git is not None
    tracked = subprocess.run(  # noqa: S603 - git with fixed arguments
        [git, "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    this = Path(__file__).resolve()
    offenders = sorted(
        f"{name}: {marker}"
        for name in tracked
        if Path(name).suffix in CODE_SUFFIXES and (ROOT / name).resolve() != this and (ROOT / name).is_file()
        for marker in REFERENCE_KIT_MARKERS
        if marker in (ROOT / name).read_text(encoding="utf-8", errors="ignore").lower()
    )
    assert offenders == []


def test_only_the_graph_package_talks_to_neo4j() -> None:
    """One access layer applies the tenant and project filters to every query (spec 5.3)."""
    graph = ROOT / "packages" / "graph"
    offenders = sorted(
        str(p.relative_to(ROOT))
        for r in (ROOT / "apps", ROOT / "packages")
        for p in r.rglob("*.py")
        if graph not in p.parents
        and not {".venv", "node_modules", "__pycache__"} & set(p.relative_to(ROOT).parts)
        and any(m.split(".")[0] == "neo4j" for m in imports(p))
    )
    assert offenders == []
