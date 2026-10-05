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
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


KEY_MARKERS = ("key", "primary_key", "primaryKey", "pk", "is_key", "isKey")


class Column(CharacterizationModel):
    name: Identifier
    type: str = Field(min_length=1, max_length=60, description="The legacy type as written, e.g. money, char(3)")
    nullable: bool = True


class Table(CharacterizationModel):
    """A legacy table the program reads or writes, qualified as the program names it (e.g. db..table)."""

    name: Identifier
    columns: list[Column] = Field(min_length=1)
    key: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def key_marked_on_columns(cls, data: object) -> object:
        """A key written as a marker on each column (`"key": true`, `"primary_key": true`, the way database tools
        show it) means the table's key: the marked columns, in order, join the table's list."""
        if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
            return data
        marked: list[str] = []
        columns = []
        for item in data["columns"]:
            if not isinstance(item, dict):
                columns.append(item)
                continue
            rest = {k: v for k, v in item.items() if k not in KEY_MARKERS}
            if any(item.get(k) is True for k in KEY_MARKERS) and isinstance(item.get("name"), str):
                marked.append(item["name"])
            columns.append(rest)
        key = list(data.get("key") or []) if isinstance(data.get("key"), list) else []
        key += [m for m in marked if m.lower() not in {k.lower() for k in key}]
        return {**data, "columns": columns, "key": key}

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


class GoldenMaster(CharacterizationModel):
    """The frozen oracle: the suite as run and what the legacy did in every case."""

    program: str
    source_sha256: str
    engine: str = Field(description="What ran the legacy, e.g. sybase-ase-16.0")
    schema_: Schema = Field(alias="schema")
    results: list[Recorded]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @property
    def from_traces(self) -> bool:
        """Observed from recorded traces: the legacy cannot run fresh inputs (the verdict stays PARTLY PROVEN)."""
        return self.engine in TRACE_ENGINES


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
