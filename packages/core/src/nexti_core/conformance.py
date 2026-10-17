"""The complete contract of a source adapter (spec 8.2, ADR-0055 point 13) as code: what every adapter must answer
about a legacy, checked by one conformance suite that each adapter's tests run on their own fixture, and reported
capability by capability so the coverage of each language is a document generated from the checks (point 21), never
a claim. A required capability that fails or is missing makes the adapter non-conformant; an optional one that is
missing is a gap the document shows."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nexti_core.adapters import SourceAdapter, SourceFile
from nexti_core.spec import neutral_types as nt

PROGRAM_LABELS = ("Program", "StoredProcedure")


@dataclass(frozen=True)
class Capability:
    key: str
    required: bool
    description: str


CONTRACT: tuple[Capability, ...] = (
    Capability("detect", True, "recognises its own technology (confidence above 0.5)"),
    Capability("inventory", True, "programs, data and calls with their lines"),
    Capability("types", True, "every declared type mapped to a neutral type"),
    Capability("slices", True, "units for rule extraction with exact line ranges"),
    Capability("classification", True, "statements by label, the transaction as business (ADR-0055)"),
    Capability("data_of", True, "tables read and written inside a slice"),
    Capability("digest", True, "the inventory in a few lines for the agents"),
    Capability("engine_quirks", True, "engine behaviours the code relies on (an empty list when none is catalogued)"),
    Capability("unit_of_work", False, "where a program begins, saves, confirms and undoes its work (ADR-0055)"),
    Capability("call_effects", False, "the tables each external call touches (ADR-0055)"),
    Capability("screens", False, "the screens the programs show"),
    Capability("coverage_branches", False, "the branches an instrumented run can report (ADR-0047)"),
    Capability("program_quirks", False, "quirks and settings per program from the catalog, for traces (R4)"),
)
REQUIRED = tuple(c.key for c in CONTRACT if c.required)


@dataclass(frozen=True)
class Finding:
    key: str
    status: str  # passed | missing | failed
    detail: str = ""


def conformance(adapter: SourceAdapter, files: Sequence[SourceFile], program: str | None = None) -> list[Finding]:
    """Every capability of the contract exercised on `files`; `program` (the first program of the inventory when
    omitted) is the one the per-program capabilities are asked about."""
    found: list[Finding] = []
    files = list(files)

    def check(key: str, run: Any) -> None:
        try:
            found.append(run())
        except Exception as exc:
            found.append(Finding(key, "failed", f"{type(exc).__name__}: {exc}"[:300]))

    def detect() -> Finding:
        score = float(adapter.detect(files))
        return Finding("detect", "passed" if score > 0.5 else "failed", f"confidence {score:.2f}")

    check("detect", detect)
    try:
        inventory = adapter.inventory(files)
    except Exception as exc:
        inventory = None
        found.append(Finding("inventory", "failed", f"{type(exc).__name__}: {exc}"[:300]))
    programs = [n.name for n in inventory.nodes if n.label in PROGRAM_LABELS] if inventory is not None else []
    if inventory is not None:
        summary = f"{len(programs)} program(s), {len(inventory.nodes)} node(s), {len(inventory.edges)} edge(s)"
        if inventory.problems:
            summary += f"; problems: {len(inventory.problems)}"
        found.append(Finding("inventory", "passed" if programs else "failed", summary))
    chosen = program or (programs[0] if programs else "")

    def types() -> Finding:
        mapped = adapter.types(files)
        bad = sorted(k for k, v in mapped.items() if v and _unparsable(v))
        if not mapped:
            return Finding("types", "failed", "no type mapped")
        if bad:
            return Finding("types", "failed", f"not neutral: {', '.join(bad[:5])}")
        unresolved = sum(1 for v in mapped.values() if not v)
        return Finding("types", "passed", f"{len(mapped)} type(s), {unresolved} unresolved")

    check("types", types)

    def slices() -> Finding:
        views = adapter.slices(files)
        if not views:
            return Finding("slices", "failed", "no slice")
        empty = [v.unit for v in views if not v.lines]
        if empty:
            return Finding("slices", "failed", f"slices without lines: {', '.join(empty[:5])}")
        return Finding("slices", "passed", f"{len(views)} slice(s)")

    check("slices", slices)

    def classification() -> Finding:
        counts = adapter.classification(files)
        if counts.get("business", 0) <= 0:
            return Finding("classification", "failed", f"no business statement: {counts}")
        return Finding("classification", "passed", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))

    check("classification", classification)

    def data_of() -> Finding:
        views = adapter.slices(files)
        view = views[0]
        reads, writes = adapter.data_of(files, view.file, list(view.lines))
        return Finding("data_of", "passed", f"{len(reads)} read, {len(writes)} written in {view.unit}")

    check("data_of", data_of)

    def digest() -> Finding:
        text = adapter.digest(files)
        return Finding("digest", "passed" if text.strip() else "failed", f"{len(text)} character(s)")

    check("digest", digest)

    def engine_quirks() -> Finding:
        quirks = adapter.engine_quirks(files)
        return Finding("engine_quirks", "passed", f"{len(quirks)} quirk(s)")

    check("engine_quirks", engine_quirks)
    found.append(_optional(adapter, "unit_of_work", lambda m: m(files, chosen), "entries", chosen))
    found.append(_optional(adapter, "call_effects", lambda m: m(files, chosen), "calls", chosen))
    found.append(_optional(adapter, "screens", lambda m: m(files), "screen(s)", chosen))
    found.append(_optional(adapter, "coverage_branches", lambda m: m(files, chosen), "branch(es)", chosen))
    found.append(_optional(adapter, "program_quirks", lambda m: m(files, chosen), "item(s)", chosen))
    return found


def _unparsable(neutral: str) -> bool:
    try:
        nt.parse(neutral)
    except Exception:
        return True
    return False


def _optional(adapter: SourceAdapter, key: str, call: Any, unit: str, program: str) -> Finding:
    method = getattr(adapter, key, None)
    if method is None:
        return Finding(key, "missing", "the adapter does not implement it")
    try:
        result = call(method)
    except Exception as exc:
        return Finding(key, "failed", f"{type(exc).__name__}: {exc}"[:300])
    count = sum(len(part) for part in result) if isinstance(result, tuple) else len(result)
    where = f" for {program}" if program and key != "screens" else ""
    return Finding(key, "passed", f"{count} {unit}{where}")


def problems(findings: Sequence[Finding]) -> list[str]:
    """What keeps the adapter from conforming: a required capability that failed or is missing."""
    by_key = {f.key: f for f in findings}
    return [f"{key}: {by_key[key].status} ({by_key[key].detail})" if key in by_key else f"{key}: not checked"
            for key in REQUIRED if key not in by_key or by_key[key].status != "passed"]  # fmt: skip


MARKS = {"passed": "✓", "missing": "—", "failed": "✗"}


def coverage_rows(reports: Mapping[str, Sequence[Finding]]) -> str:
    """The coverage of every adapter, one row per capability of the contract, as a Markdown table: ✓ passed,
    — missing (a gap the plan names), ✗ failed."""
    names = list(reports)
    header = "| Capacidad | " + " | ".join(names) + " |"
    rule = "|---|" + "|".join("---" for _ in names) + "|"
    rows = [header, rule]
    for capability in CONTRACT:
        marks = []
        for name in names:
            finding = next((f for f in reports[name] if f.key == capability.key), None)
            marks.append(MARKS.get(finding.status, "?") if finding else "?")
        kind = "obligatoria" if capability.required else "opcional"
        rows.append(f"| `{capability.key}` ({kind}): {capability.description} | " + " | ".join(marks) + " |")
    return "\n".join(rows)
