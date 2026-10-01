"""Insecure patterns the generator could introduce, by language (ADR-0023). Deterministic rules on the generated
files: SQL built by concatenation, TLS verification turned off, credentials in the code, CORS open to any origin and
debug switches. Tests are not scanned: their fixtures are not deployed."""

import re
from dataclasses import dataclass

from nexti_hardening.report import Finding, Severity


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    suffixes: tuple[str, ...]
    pattern: re.Pattern[str]
    message: str


def _rule(id_: str, severity: Severity, suffixes: tuple[str, ...], pattern: str, message: str) -> Rule:
    return Rule(id_, severity, suffixes, re.compile(pattern, re.IGNORECASE), message)


CODE = (".java", ".cs", ".ts", ".tsx", ".js")
CONFIG = (".properties", ".yml", ".yaml", ".json", ".config")
RULES: tuple[Rule, ...] = (
    _rule(
        "sql-concatenation",
        "high",
        (".java",),
        r"""(execute(Query|Update)?|prepareStatement|createQuery|createNativeQuery)\s*\(\s*"[^"]*"\s*\+""",
        "SQL built by concatenating strings: use bound parameters",
    ),
    _rule(
        "sql-concatenation",
        "high",
        (".cs",),
        r"""(new\s+SqlCommand|CommandText\s*=|FromSqlRaw|ExecuteSqlRaw)\s*\(?\s*(\$"[^"]*\{|"[^"]*"\s*\+)""",
        "SQL built by concatenating strings: use bound parameters",
    ),
    _rule(
        "sql-concatenation",
        "high",
        (".ts", ".tsx", ".js"),
        r"""\.(query|raw)\s*\(\s*`[^`]*\$\{""",
        "SQL built with template strings: use bound parameters",
    ),
    _rule(
        "tls-verification-off",
        "high",
        (".java",),
        r"""(checkServerTrusted\s*\([^)]*\)\s*(throws\s+[\w.]+\s*)?\{\s*\}|setHostnameVerifier\s*\(\s*\([^)]*\)\s*->\s*true)""",
        "TLS certificate or host name verification turned off",
    ),
    _rule(
        "tls-verification-off",
        "high",
        (".cs",),
        r"""ServerCertificateCustomValidationCallback\s*=\s*[^;]*=>\s*true""",
        "TLS certificate verification turned off",
    ),
    _rule(
        "tls-verification-off",
        "high",
        (".ts", ".tsx", ".js"),
        r"""rejectUnauthorized\s*:\s*false""",
        "TLS certificate verification turned off",
    ),
    _rule(
        "credential-in-code",
        "critical",
        CODE,
        r"""\b(password|passwd|pwd|secret|api_?key|access_?token)\b\s*[:=]\s*"[^"${}\s]{6,}\"""",
        "A credential is written in the code: read it from the secrets store",
    ),
    _rule(
        "credential-in-config",
        "critical",
        (".properties",),
        r"""^\s*[\w.-]*(password|secret|api-?key|token)\s*=\s*(?!\$\{)[^\s#]{4,}\s*$""",
        "A credential is written in the configuration: use an environment variable or the secrets store",
    ),
    _rule(
        "credential-in-config",
        "critical",
        (".json", ".config"),
        r""""(Password|Pwd)\s*=\s*[^;"$]{4,}""",
        "A connection string carries a password: use the secrets store",
    ),
    _rule(
        "cors-any-origin",
        "medium",
        (".java",),
        r"""(allowedOrigins\s*\(\s*"\*"|@CrossOrigin\s*\(\s*(origins\s*=\s*)?"\*")""",
        "CORS allows any origin",
    ),
    _rule("cors-any-origin", "medium", (".cs",), r"""AllowAnyOrigin\s*\(\s*\)""", "CORS allows any origin"),
    _rule(
        "debug-enabled",
        "medium",
        (".properties",),
        r"""^\s*(debug\s*=\s*true|spring\.h2\.console\.enabled\s*=\s*true|server\.error\.include-stacktrace\s*=\s*always)""",
        "A debug switch is on in the configuration",
    ),
)


def is_test(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return ("/test/" in lowered or "/tests/" in lowered or lowered.startswith(("test/", "tests/"))
            or lowered.endswith(("test.java", "tests.cs", ".test.ts", ".test.tsx", ".spec.ts")))  # fmt: skip


def scan(files: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    for path, content in sorted(files.items()):
        if is_test(path):
            continue
        rules = [r for r in RULES if path.endswith(r.suffixes)]
        if not rules:
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            for rule in rules:
                if rule.pattern.search(line):
                    found.append(Finding("patterns", rule.severity, rule.id, path, number, rule.message))
    return found
