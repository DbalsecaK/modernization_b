"""Prototypes of the UI phase (spec 7.4, ADR-0013): the checks a generated screen must pass before it is built, the
build in the web sandbox, and the NexTI base design system tokens. A prototype is code written by a model that will
run in a reviewer's browser, so it may only use React and the NexTI design system, never the network, storage,
cookies or the page around it; the platform's own entry mounts it in an isolated frame."""

import base64
import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-web:1"
LIMITS = Limits(cpus=1.0, memory_mb=768, pids=128, timeout_seconds=120, work_mb=128, max_output_bytes=4 * 1024 * 1024)
ALLOWED_IMPORTS = ("react", "@nexti/ds")
MAX_SOURCE_BYTES = 60_000
TOKENS_FILE = Path(__file__).resolve().parents[4] / "packages" / "ds" / "src" / "tokens.json"

_IMPORT = re.compile(r"""(?:^|\n)\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dynamic imports or require", re.compile(r"\bimport\s*\(|\brequire\s*\(")),
    ("network access", re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon)\b")),
    ("code evaluation", re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(")),
    ("cookies or storage", re.compile(r"document\.cookie|\b(localStorage|sessionStorage|indexedDB|caches)\b")),
    ("the page around the prototype", re.compile(r"\bwindow\.(parent|top|opener|frames)\b|\bpostMessage\b")),
    ("navigation away", re.compile(r"\b(window\.)?location\s*(\.\s*(href|assign|replace)\b|=)|\bwindow\.open\s*\(")),
    ("external URLs", re.compile(r"""['"`]\s*(https?:)?//""")),
    ("raw HTML", re.compile(r"dangerouslySetInnerHTML|<\s*(script|iframe|object|embed|link|meta|base)\b", re.I)),
)


@dataclass
class PrototypeBuild:
    ok: bool
    js: str = ""
    css: str = ""
    errors: list[str] = field(default_factory=list)


def problems(source: str) -> list[str]:
    """What the generated screen may not do (ADR-0013); empty when it can be built."""
    found: list[str] = []
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        found.append(f"the screen is larger than {MAX_SOURCE_BYTES} bytes")
    for module in _IMPORT.findall(source):
        if module not in ALLOWED_IMPORTS:
            found.append(f"import from {module!r} is not allowed: only react and @nexti/ds")
    for what, pattern in _FORBIDDEN:
        match = pattern.search(source)
        if match:
            line = source.count("\n", 0, match.start()) + 1
            found.append(f"line {line}: {what} is not allowed ({match.group(0).strip()})")
    if not re.search(r"\bexport\s+default\b", source):
        found.append("the screen must be the default export (a React component)")
    return found


async def build(sandbox: Sandbox, source: str) -> PrototypeBuild:
    """Validates and compiles one screen into a script and a stylesheet (base64 from the sandbox)."""
    blocked = problems(source)
    if blocked:
        return PrototypeBuild(False, errors=blocked)
    result = await sandbox.run(["node", "/opt/sandbox/build.mjs"],
                               files={"prototype/Screen.tsx": source.encode("utf-8")}, limits=LIMITS)  # fmt: skip
    out = result.stdout
    if "===PROTOTYPE===" not in out:
        detail = (result.stderr or out)[-2000:]
        return PrototypeBuild(False, errors=[f"the build did not finish (exit {result.exit_code}): {detail}"])
    report: dict[str, Any] = json.loads(out.split("===PROTOTYPE===", 1)[1].split("===END===", 1)[0])
    if not report.get("ok"):
        errors = [f"{e.get('file') or 'entry'}:{e.get('line')}:{e.get('column')}: {e.get('text')}"
                  for e in report.get("errors", [])]  # fmt: skip
        return PrototypeBuild(False, errors=errors or ["the build failed"])
    return PrototypeBuild(True, js=base64.b64decode(report["js"]).decode("utf-8"),
                          css=base64.b64decode(report.get("css") or "").decode("utf-8"))  # fmt: skip


def page(built: PrototypeBuild, title: str) -> str:
    """The HTML document served in the isolated frame: the bundle inline, nothing else (the CSP forbids the rest)."""
    safe_title = re.sub(r"[<>&\"']", "", title)[:120]
    script = built.js.replace("</script", "<\\/script")
    style = built.css.replace("</style", "<\\/style")
    return (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{safe_title}</title>'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><style>{style}</style></head>'
        f'<body><div id="root"></div><script>{script}</script></body></html>'
    )


@cache
def base_tokens() -> dict[str, Any]:
    """The NexTI base design system tokens (packages/ds/src/tokens.json), the version 1 of every project."""
    data: dict[str, Any] = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    return data


__all__ = ["ALLOWED_IMPORTS", "IMAGE", "LIMITS", "PrototypeBuild", "base_tokens", "build", "page", "problems"]
