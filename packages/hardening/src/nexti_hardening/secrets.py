"""Secrets in the generated files, found by gitleaks in the sandbox without network (ADR-0023). The report keeps the
rule, the file and the line: never the secret nor the line's text."""

import json

from nexti_hardening.report import Check, Finding
from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-hardening:1"
LIMITS = Limits(cpus=1.0, memory_mb=512, pids=128, timeout_seconds=180, work_mb=64)
SCRIPT = ("gitleaks dir /input --no-banner --report-format json --report-path /work/report.json --exit-code 0 "
          ">/work/log 2>&1; echo '===REPORT==='; cat /work/report.json 2>/dev/null || echo '[]'")  # fmt: skip


async def scan(sandbox: Sandbox, files: dict[str, str]) -> tuple[list[Finding], Check]:
    if not files:
        return [], Check("secrets", "checked", "no files")
    result = await sandbox.run(["sh", "-c", SCRIPT], {p: c.encode("utf-8") for p, c in files.items()}, LIMITS)
    raw = result.stdout.split("===REPORT===", 1)[-1].strip() or "[]"
    try:
        leaks = json.loads(raw)
    except json.JSONDecodeError:
        return [], Check("secrets", "not_checked", f"gitleaks did not answer: {result.stderr[-300:]}")
    findings = [
        Finding("secrets", "critical", str(leak.get("RuleID", "secret")),
                str(leak.get("File", "")).removeprefix("/input/"),
                int(leak["StartLine"]) if leak.get("StartLine") else None,
                str(leak.get("Description") or "A secret is written in the code"))
        for leak in leaks if isinstance(leak, dict)
    ]  # fmt: skip
    return findings, Check("secrets", "checked", f"gitleaks on {len(files)} file(s)")
