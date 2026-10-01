"""The hardening report (ADR-0023): findings by kind, each with its severity, file, line and rule, and whether each
kind could be checked. A finding never carries the secret or the code it points at: only where and why."""

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["critical", "high", "medium", "low"]
Kind = Literal["secrets", "dependencies", "patterns", "performance"]
Status = Literal["checked", "not_checked"]
KINDS: tuple[Kind, ...] = ("secrets", "dependencies", "patterns", "performance")
ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(frozen=True)
class Finding:
    kind: Kind
    severity: Severity
    rule: str
    file: str
    line: int | None
    message: str


@dataclass(frozen=True)
class Check:
    kind: Kind
    status: Status
    detail: str


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]
    checks: tuple[Check, ...]
    counts: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def of(findings: list[Finding], checks: list[Check]) -> "Report":
        ordered = sorted(findings, key=lambda f: (ORDER[f.severity], f.kind, f.file, f.line or 0, f.rule))
        counts = {s: sum(1 for f in ordered if f.severity == s) for s in ORDER}
        return Report(tuple(ordered), tuple(sorted(checks, key=lambda c: KINDS.index(c.kind))), counts)

    @property
    def critical(self) -> int:
        return self.counts.get("critical", 0) + self.counts.get("high", 0)

    def summary(self) -> str:
        found = ", ".join(f"{n} {s}" for s, n in self.counts.items() if n) or "no findings"
        unchecked = [c.kind for c in self.checks if c.status == "not_checked"]
        return f"Hardening: {found}" + (f"; not checked: {', '.join(unchecked)}" if unchecked else "")

    def to_dict(self) -> dict[str, object]:
        return {"counts": self.counts, "checks": [asdict(c) for c in self.checks],
                "findings": [asdict(f) for f in self.findings]}  # fmt: skip

    def to_markdown(self) -> str:
        lines = ["# Hardening report", "", "Computed by code on the generated project (ADR-0023).", "",
                 "| Check | Status | Detail |", "|---|---|---|"]  # fmt: skip
        lines += [f"| {c.kind} | {c.status.replace('_', ' ')} | {c.detail} |" for c in self.checks]
        lines += ["", "## Findings", ""]
        if not self.findings:
            lines.append("No findings.")
        else:
            lines += ["| Severity | Kind | Rule | Where | What |", "|---|---|---|---|---|"]
            for f in self.findings:
                where = f"{f.file}:{f.line}" if f.line else f.file
                lines.append(f"| {f.severity} | {f.kind} | {f.rule} | `{where}` | {f.message} |")
        return "\n".join(lines) + "\n"
