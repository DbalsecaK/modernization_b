"""The spec as structured data (spec 4.1, 4.2): what agents produce, people review and packs generate from. Every
element carries its traceable origin. These models are the contract between the worker, the API and the packs;
they are persisted by the API (PostgreSQL) and mirrored in the knowledge graph."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexti_core.spec import neutral_types

RULE_ID = re.compile(r"^RULE-\d{3,}$")
Category = Literal["calculation", "validation", "lifecycle", "policy"]
Priority = Literal["P0", "P1", "P2"]
Confidence = Literal["high", "medium", "low"]
ElementStatus = Literal["draft", "review", "approved", "reopened", "obsolete"]


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(SpecModel):
    """Where an element comes from (4.2): `file:start-end` of the legacy for Flow 1."""

    file: str = Field(min_length=1, max_length=400)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> "SourceRef":
        if self.line_end < self.line_start:
            raise ValueError("line_end must not be before line_start")
        return self

    def __str__(self) -> str:
        span = f"{self.line_start}" if self.line_start == self.line_end else f"{self.line_start}-{self.line_end}"
        return f"{self.file}:{span}"

    @classmethod
    def parse(cls, text: str) -> "SourceRef":
        match = re.match(r"^(?P<file>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$", text.strip().strip("`"))
        if not match:
            raise ValueError(f"not a file:line reference: {text!r}")
        start = int(match["start"])
        return cls(file=match["file"], line_start=start, line_end=int(match["end"] or start))


class DataItem(SpecModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(description="Neutral type (4.3)")
    description: str = Field(default="", max_length=500)

    @field_validator("type")
    @classmethod
    def neutral(cls, value: str) -> str:
        return str(neutral_types.parse(value))


class Rule(SpecModel):
    """A business rule (4.1) with its citation; scenarios carry concrete values."""

    id: str
    name: str = Field(min_length=3, max_length=200)
    domain: str = Field(default="", max_length=120)
    category: Category
    priority: Priority
    statement: str = Field(min_length=10, max_length=2000, description="In business language")
    condition: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)
    inputs: tuple[DataItem, ...] = ()
    outputs: tuple[DataItem, ...] = ()
    scenarios: tuple[str, ...] = Field(default=(), description="Given/When/Then with concrete values")
    hardcoded: tuple[str, ...] = ()
    suspected_defect: str | None = Field(default=None, max_length=1000)
    confidence: Confidence = "medium"
    sme_question: str | None = Field(default=None, max_length=1000)
    sources: tuple[SourceRef, ...] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def rule_id(cls, value: str) -> str:
        if not RULE_ID.match(value):
            raise ValueError("a rule id looks like RULE-001")
        return value


class Capability(SpecModel):
    id: str = Field(pattern=r"^CAP-\d{3,}$")
    name: str = Field(min_length=3, max_length=200)
    domain: str = Field(default="", max_length=120)
    actor: str = Field(default="", max_length=120)
    goal: str = Field(default="", max_length=1000)
    priority: Priority = "P1"
    rules: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()


class Contract(SpecModel):
    id: str = Field(pattern=r"^CON-\d{3,}$")
    operation: str = Field(min_length=1, max_length=200)
    inputs: tuple[DataItem, ...] = ()
    outputs: tuple[DataItem, ...] = ()
    errors: tuple[str, ...] = ()
    idempotent: bool = False
    rules: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()


class TestCase(SpecModel):
    __test__ = False  # not a pytest class

    id: str = Field(pattern=r"^TC-\d{3,}$")
    kind: Literal["acceptance", "characterization", "golden_master", "contract", "visual"]
    description: str = Field(default="", max_length=1000)
    inputs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    expected: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    verifies: tuple[str, ...] = ()


class Spec(SpecModel):
    """A snapshot of the spec of a project (what the evaluation compares and packs generate from)."""

    rules: tuple[Rule, ...] = ()
    capabilities: tuple[Capability, ...] = ()
    contracts: tuple[Contract, ...] = ()
    test_cases: tuple[TestCase, ...] = ()

    @model_validator(mode="after")
    def unique_ids(self) -> "Spec":
        for kind, items in (("rule", self.rules), ("capability", self.capabilities), ("contract", self.contracts),
                            ("test case", self.test_cases)):  # fmt: skip
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {kind} ids")
        return self

    def rule(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)
