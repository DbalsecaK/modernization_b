"""Characterization and golden master (spec 6.1 phase 9, 4.1 "test case"): the behaviour of the legacy frozen as
the oracle before anything is generated. A case is the data the legacy starts from, the inputs of the call and how
the external programs it calls answer; the observation is what the legacy did: its return code, its outputs, the
final state of the tables and the calls it made. Every value is kept in a canonical text form of its neutral type,
so the legacy and the target are compared by value and never by how each engine prints it."""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from nexti_core.spec import neutral_types as nt

if TYPE_CHECKING:
    from nexti_core.adapters import SourceFile

Scalar = str | int | float | bool | None
# The engine of a golden master taken from recorded traces (CICS, ADR-0015): the legacy did not run on the platform.
TRACE_ENGINE = "cics-trace"
# Every engine whose golden master comes from recorded traces (CICS ADR-0015, ASPX ADR-0020).
TRACE_ENGINES = (TRACE_ENGINE, "aspx-trace")
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_#@][A-Za-z0-9_#$@.]*$", max_length=200)]
CASE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


class CharacterizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Column(CharacterizationModel):
    name: Identifier
    type: str = Field(min_length=1, max_length=60, description="The legacy type as written, e.g. money, char(3)")
    nullable: bool = True


class Table(CharacterizationModel):
    """A legacy table the program reads or writes, qualified as the program names it (e.g. db..table)."""

    name: Identifier
    columns: list[Column] = Field(min_length=1)
    key: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def known_key(self) -> "Table":
        names = {c.name.lower() for c in self.columns}
        missing = [k for k in self.key if k.lower() not in names]
        if missing:
            raise ValueError(f"{self.name}: key columns not declared: {', '.join(missing)}")
        return self

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name.lower() == name.lower()), None)


class Schema(CharacterizationModel):
    tables: list[Table] = Field(default_factory=list)

    def table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name.lower() == name.lower()), None)


class StubAnswer(CharacterizationModel):
    """How an external program answers one call: its return code and its output parameters."""

    returns: int = 0
    outputs: dict[str, Scalar] = Field(default_factory=dict)


class Case(CharacterizationModel):
    name: str = Field(pattern=CASE_NAME.pattern, description="snake_case, unique in the suite")
    description: str = Field(default="", max_length=500)
    rules: list[str] = Field(min_length=1, description="The rules the case exercises (RULE-NNN)")
    inputs: dict[str, Scalar] = Field(default_factory=dict, description="Parameter -> value; absent uses the default")
    setup: dict[str, list[dict[str, Scalar]]] = Field(default_factory=dict, description="Table -> initial rows")
    stubs: dict[str, list[StubAnswer]] = Field(
        default_factory=dict, description="External program -> its answers, one per call in order (the last repeats)"
    )


class Suite(CharacterizationModel):
    """What the test engineer proposes: the legacy schema the program needs and the cases."""

    program: str = Field(min_length=1, max_length=200, description="The legacy entry point, e.g. dbo.sp_x")
    schema_: Schema = Field(alias="schema", default_factory=Schema)
    cases: list[Case] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def unique_names(self) -> "Suite":
        names = [c.name for c in self.cases]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate case names: {', '.join(duplicates)}")
        return self


class Call(CharacterizationModel):
    program: str
    arguments: dict[str, str | None]


class Observation(CharacterizationModel):
    """What the legacy did in one case, every value canonical (see `canonical`)."""

    returns: int | None = None
    outputs: dict[str, str | None] = Field(default_factory=dict)
    tables: dict[str, list[dict[str, str | None]]] = Field(default_factory=dict)
    calls: list[Call] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list, description="Messages the program raised (e.g. raiserror)")
    error: str | None = Field(default=None, description="The engine failed the case (not a business rejection)")


class Recorded(CharacterizationModel):
    case: Case
    observation: Observation


class CoveredBranch(CharacterizationModel):
    """A branch of the legacy program: the THEN or ELSE of an IF, an implicit ELSE, the body of a loop (ADR-0047)."""

    id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    line_start: int
    line_end: int
    measurable: bool = True
    file: str = Field(default="", max_length=500, description="The source file the lines belong to")


class Coverage(CharacterizationModel):
    """Which branches of the legacy program the cases exercised, measured on an instrumented copy run after the
    golden master (ADR-0047). A case whose instrumented run differed from the original is unreliable."""

    branches: list[CoveredBranch] = Field(default_factory=list)
    executed: dict[str, list[str]] = Field(default_factory=dict)  # case name -> branch ids
    unreliable: list[str] = Field(default_factory=list)

    @property
    def measurable(self) -> list[CoveredBranch]:
        return [b for b in self.branches if b.measurable]

    @property
    def exercised(self) -> set[str]:
        return {b for case, ids in self.executed.items() if case not in self.unreliable for b in ids}

    @property
    def not_exercised(self) -> list[CoveredBranch]:
        hit = self.exercised
        return [b for b in self.measurable if b.id not in hit]

    def note(self) -> str:
        measurable = self.measurable
        unmeasured = len(self.branches) - len(measurable)
        text = f"{len(measurable) - len(self.not_exercised)} of {len(measurable)} measurable branches exercised"
        if unmeasured:
            text += f", {unmeasured} not measurable"
        if self.unreliable:
            text += f", {len(self.unreliable)} case(s) without reliable coverage"
        return text


QuirkSeverity = Literal["critical", "high", "medium", "low"]
SEVERE: tuple[QuirkSeverity, ...] = ("critical", "high")


class EngineQuirk(CharacterizationModel):
    """A behaviour of the legacy engine the program relies on and a modern stack does differently (M28): where the
    program uses it, what the engine does, what the target must do, and what the engine answered to a probe."""

    id: str = Field(min_length=1, max_length=80)
    severity: QuirkSeverity
    behavior: str = Field(min_length=1, max_length=1000, description="What the legacy engine does")
    target: str = Field(min_length=1, max_length=1000, description="What the target must do to behave the same")
    file: str = Field(default="", max_length=500)
    lines: list[int] = Field(default_factory=list, description="Lines of the program that rely on it")
    probe: str = Field(default="", max_length=2000, description="The statements run on the engine to confirm it")
    expected: str = Field(default="", max_length=200, description="What the probe answers when the quirk holds")
    observed: str | None = Field(default=None, max_length=200, description="What the engine answered; None: not run")

    @property
    def confirmed(self) -> bool | None:
        """True: the engine behaves so; False: this engine (its options) does not; None: not probed."""
        return None if self.observed is None else self.observed == self.expected


class EnvironmentItem(CharacterizationModel):
    """A setting the legacy ran under (M28): an engine option measured on the engine, or one the program or its
    sources set (a SET option, a trigger on a table). The target reproduces it or a decision records why not."""

    key: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=500)
    source: Literal["engine", "program"]


class GoldenMaster(CharacterizationModel):
    """The frozen oracle: the suite as run and what the legacy did in every case."""

    program: str
    source_sha256: str
    engine: str = Field(description="What ran the legacy, e.g. sybase-ase-16.0")
    schema_: Schema = Field(alias="schema")
    results: list[Recorded]
    unassigned_outputs: list[str] = Field(
        default_factory=list,
        description="Output parameters the program never assigns (ADR-0044): the legacy returns the caller's value, "
        "so the comparison masks them",
    )
    coverage: Coverage | None = Field(
        default=None, description="Branches of the legacy the cases exercised, when the engine measured them (ADR-0047)"
    )
    quirks: list[EngineQuirk] = Field(
        default_factory=list, description="Engine behaviours the program relies on, probed on the engine (M28)"
    )
    environment: list[EnvironmentItem] = Field(
        default_factory=list, description="The settings the legacy ran under (M28)"
    )

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_serializer(mode="wrap")
    def _without_empty_unassigned(self, handler: SerializerFunctionWrapHandler) -> Any:
        """A golden master without unassigned outputs serialises as before ADR-0044 (recorded runs)."""
        data = handler(self)
        if isinstance(data, dict) and not self.unassigned_outputs:
            data.pop("unassigned_outputs", None)
        if isinstance(data, dict) and self.coverage is None:
            data.pop("coverage", None)
        for empty in ("quirks", "environment"):  # M28: recordings without them serialise as before
            if isinstance(data, dict) and not getattr(self, empty):
                data.pop(empty, None)
        return data

    @property
    def from_traces(self) -> bool:
        """Observed from recorded traces: the legacy cannot run fresh inputs (the verdict stays PARTLY PROVEN)."""
        return self.engine in TRACE_ENGINES


def _holder(coverage: Coverage, file: str, line: int) -> CoveredBranch | None:
    """The innermost branch body holding a line (an implicit ELSE spans its whole IF, so it holds none); None: the
    line is outside every branch, at the top level of the program."""
    bodies = [b for b in coverage.branches if b.kind != "if-false" and b.line_start <= line <= b.line_end
              and (not b.file or not file or b.file == file)]  # fmt: skip
    return min(bodies, key=lambda b: b.line_end - b.line_start) if bodies else None


def quirk_cases(master: GoldenMaster) -> dict[str, list[str]]:
    """Per quirk, the reliable cases that ran one of its lines (M28): a case ran a line when it entered the
    innermost branch holding it; a line at the top level is run by every reliable case. Without coverage the
    engine did not say which lines ran, and no quirk has cases."""
    measured = master.coverage
    if measured is None:
        return {q.id: [] for q in master.quirks}
    reliable = [r.case.name for r in master.results if r.case.name not in measured.unreliable]
    found: dict[str, list[str]] = {}
    for quirk in master.quirks:
        names: set[str] = set()
        for line in quirk.lines:
            branch = _holder(measured, quirk.file, line)
            if branch is None:
                names.update(reliable)
            else:
                names.update(c for c in reliable if branch.id in measured.executed.get(c, []))
        found[quirk.id] = sorted(names)
    return found


def unresolved_quirks(master: GoldenMaster) -> list[EngineQuirk]:
    """The quirks no reliable case reaches, when coverage was measured (M28): what they do is not proven. A quirk
    whose lines are only in branches that cannot be measured is not counted (nobody can say)."""
    if master.coverage is None:
        return []
    cases = quirk_cases(master)
    measured = master.coverage

    def knowable(quirk: EngineQuirk) -> bool:
        return any((b := _holder(measured, quirk.file, line)) is None or b.measurable for line in quirk.lines)

    return [q for q in master.quirks if not cases.get(q.id) and knowable(q)]


def quirk_combinations(master: GoldenMaster) -> list[tuple[str, str, str, list[str]]]:
    """Critical and high quirks that meet in the same branch (or both at the top level), with that branch and the
    reliable cases entering it (M28): one case must show how the engine combines them."""
    measured = master.coverage
    if measured is None:
        return []
    reliable = [r.case.name for r in master.results if r.case.name not in measured.unreliable]
    where: dict[str, set[str]] = {}
    for quirk in master.quirks:
        if quirk.severity not in SEVERE:
            continue
        for line in quirk.lines:
            branch = _holder(measured, quirk.file, line)
            where.setdefault(branch.id if branch else "top level", set()).add(quirk.id)
    out: list[tuple[str, str, str, list[str]]] = []
    for place, ids in sorted(where.items()):
        cases = reliable if place == "top level" else [c for c in reliable if place in measured.executed.get(c, [])]
        ordered = sorted(ids)
        out += [(a, b, place, cases) for i, a in enumerate(ordered) for b in ordered[i + 1 :]]
    return out


def engine_not_proven(master: GoldenMaster) -> list[str]:
    """What of the engine behaviour the golden master does not show (M28), for the verdict's "not proven"."""
    out = [f"Engine quirk no case reaches: {q.id} ({q.severity}) at lines {', '.join(str(n) for n in q.lines[:10])}"
           for q in unresolved_quirks(master)]  # fmt: skip
    out += [f"Engine quirks {a} and {b} meet in {place} and no case runs it"
            for a, b, place, cases in quirk_combinations(master) if not cases]  # fmt: skip
    return out[:50]


def engine_notes(master: GoldenMaster) -> str:
    """The engine behaviour and settings the program relies on, for the agents that write the target (M28)."""
    lines: list[str] = []
    for quirk in master.quirks:
        if quirk.confirmed is False:
            state = f"this engine does NOT behave so (it answered {quirk.observed!r}): follow the golden master"
        else:
            state = "confirmed on the legacy engine" if quirk.confirmed else "not probed"
        at = ", ".join(str(n) for n in quirk.lines[:20]) + (" ..." if len(quirk.lines) > 20 else "")
        lines.append(f"- [{quirk.severity}] {quirk.id} (lines {at}; {state}): {quirk.behavior} Target: {quirk.target}")
    settings = [f"- {e.key} = {e.value} ({e.source})" for e in master.environment]
    if not lines and not settings:
        return ""
    text = "The legacy engine behaviour this program relies on (measured on the engine of the golden master):"
    if lines:
        text += "\n" + "\n".join(lines)
    if settings:
        text += "\nThe settings the legacy ran under (reproduce them in the target or keep the behaviour they give):\n"
        text += "\n".join(settings)
    return text


def source_digest(files: "Sequence[SourceFile]") -> str:
    """SHA-256 of the legacy as characterized (spec 11.3 check 6: the source stays intact)."""
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda f: f.path):
        digest.update(file.path.encode() + b"\0" + file.text.encode() + b"\0")
    return digest.hexdigest()


def suite_key(source: str, suite: Suite) -> str:
    """The identity of a run: the same code and the same suite give the same observations (recordings, 12)."""
    payload = json.dumps({"source": source, "suite": suite.model_dump(mode="json", by_alias=True)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical(neutral: str | None, value: object) -> str | None:
    """The value in the canonical text of its neutral type: decimals at the scale of the type, integers without
    sign noise, fixed text without trailing blanks, dates and timestamps in ISO 8601, booleans as true/false.
    Unknown types keep the text as given."""
    if value is None:
        return None
    text = str(value).strip() if not isinstance(value, str) else value
    try:
        kind = nt.parse(neutral) if neutral else None
    except nt.NeutralTypeError:
        kind = None
    try:
        if isinstance(kind, nt.Decimal):
            number = Decimal(text.replace(",", ""))
            return str(number.quantize(Decimal(1).scaleb(-kind.scale)))
        if isinstance(kind, nt.Integer):
            return str(int(Decimal(text)))
        if isinstance(kind, nt.Text):
            return text.rstrip(" ") if kind.kind == "fixed" else text
        if isinstance(kind, nt.Boolean):
            lowered = text.strip().lower()
            if lowered in ("1", "true", "t", "y", "s", "yes"):
                return "true"
            if lowered in ("0", "false", "f", "n", "no"):
                return "false"
            return text
        if isinstance(kind, nt.Date):
            return date.fromisoformat(text.strip()[:10]).isoformat()
        if isinstance(kind, nt.Timestamp):
            moment = datetime.fromisoformat(text.strip().replace(" ", "T"))
            return moment.isoformat(timespec="milliseconds")
        if isinstance(kind, nt.Binary):
            return text.lower().removeprefix("0x")
    except (InvalidOperation, ValueError):
        return text
    return text
