"""What a generated page may not do (ADR-0016), checked by code before it is built: it talks to the backend only
through the typed client, imports only the framework, the design system and the project's own modules, and never
runs strings as code, writes raw HTML, touches cookies or storage, leaves the app or loads anything external."""

import re

MAX_BYTES = 80_000
IMPORTS = {
    "react": ("react", "@nexti/ds", "../api/client", "./types"),
    "angular": ("@angular/core", "@angular/common", "@angular/forms", "../api/client", "../app/tokens"),
}
_FORBIDDEN = (
    (re.compile(r"\beval\s*\(|\bnew\s+Function\s*\("), "no eval or new Function"),
    (
        re.compile(r"dangerouslySetInnerHTML|\[innerHTML\]|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML"),
        "no raw HTML",
    ),
    (
        re.compile(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon"),
        "the backend is called only through the typed client",
    ),
    (re.compile(r"document\.cookie|localStorage|sessionStorage|indexedDB"), "no cookies or browser storage"),
    (
        re.compile(r"window\.location|location\.href|window\.open\s*\(|document\.location"),
        "navigation between screens goes through navigate()",
    ),
    (re.compile(r"""["'`]\s*(?:https?:)?//"""), "no external URLs"),
    (re.compile(r"<script\b|\bimport\s*\("), "no scripts or dynamic imports"),
)
_IMPORT = re.compile(r"""^\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE)


def problems(source: str, flavour: str) -> list[str]:
    found = []
    if len(source.encode("utf-8")) > MAX_BYTES:
        found.append(f"the page is larger than {MAX_BYTES // 1000} KB")
    allowed = IMPORTS[flavour]
    for module in _IMPORT.findall(source):
        if module not in allowed:
            found.append(f"import '{module}' is not allowed (only {', '.join(allowed)})")
    found += [reason for pattern, reason in _FORBIDDEN if pattern.search(source)]
    return found
