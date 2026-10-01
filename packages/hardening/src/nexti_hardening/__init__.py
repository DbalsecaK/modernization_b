"""Hardening of the generated project (spec 6.1 phase 12, ADR-0023), computed by code: secrets (gitleaks in the
sandbox), vulnerable dependencies (OSV), insecure patterns by language and slow tests. It informs: the release carries
the report, and deploying is the customer's decision after C4."""

import httpx

from nexti_hardening import dependencies, patterns, performance, secrets
from nexti_hardening.report import Check, Finding, Report
from nexti_sandbox import Sandbox

IMAGE = secrets.IMAGE
REPORT_JSON = "hardening/report.json"
REPORT_MD = "hardening/REPORT.md"


async def harden(
    files: dict[str, str], *, sandbox: Sandbox | None, http: httpx.AsyncClient | None, junit_xml: str | None,
    osv_url: str | None = dependencies.OSV_URL,
) -> Report:  # fmt: skip
    found: list[Finding] = patterns.scan(files)
    checks = [Check("patterns", "checked", f"{len(patterns.RULES)} rules on {len(files)} file(s)")]
    if sandbox is None:
        checks.append(Check("secrets", "not_checked", "no sandbox for gitleaks"))
    else:
        leaks, check = await secrets.scan(sandbox, files)
        found += leaks
        checks.append(check)
    vulnerable, check = await dependencies.scan(http, files, osv_url)
    found += vulnerable
    checks.append(check)
    slow, check = performance.scan(junit_xml)
    found += slow
    checks.append(check)
    return Report.of(found, checks)


__all__ = ["IMAGE", "REPORT_JSON", "REPORT_MD", "Check", "Finding", "Report", "harden"]
