"""Wire shapes of the spec, user stories, the plan by waves and Gherkin validation."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from nexti_api.schemas import ApiModel

Priority = Literal["P0", "P1", "P2"]
Criteria = list[str]


class RuleOut(ApiModel):
    key: str
    version: int
    status: str
    data: dict[str, Any]
    origin: str
    created_at: datetime


class GherkinProblemOut(ApiModel):
    criterion: int
    code: str
    line: int
    message: str


class GherkinIn(ApiModel):
    criteria: list[str] = Field(max_length=50)


class GherkinOut(ApiModel):
    valid: bool
    problems: list[GherkinProblemOut]


class StoryOut(ApiModel):
    key: str
    version: int
    feature: str
    title: str
    narrative: str
    criteria: list[str]
    links: list[str]
    priority: str
    estimate: int
    status: str
    origin: str
    out_of_scope: bool
    merged_into: str | None
    reason: str | None
    action: str
    created_by: uuid.UUID | None
    created_by_name: str | None
    created_at: datetime
    traced: bool
    depends_on: list[dict[str, Any]]


class StoryIn(ApiModel):
    feature: str = Field(default="", max_length=200)
    title: str = Field(min_length=3, max_length=200)
    narrative: str = Field(default="", max_length=2000)
    criteria: Criteria = Field(default_factory=list, max_length=50)
    links: list[str] = Field(default_factory=list, max_length=200)
    priority: Priority = "P1"
    estimate: int = Field(default=3, ge=1, le=100)


class SplitIn(ApiModel):
    title: str = Field(min_length=3, max_length=200)
    criteria: list[int] = Field(default_factory=list, description="Indexes of the criteria that move")
    links: list[str] = Field(default_factory=list, description="Links that move to the new story")


class MergeIn(ApiModel):
    into: str = Field(pattern=r"^US-\d{3,}$")


class DiscardIn(ApiModel):
    reason: str = Field(min_length=3, max_length=2000)
    out_of_scope: bool = False


class DependencyIn(ApiModel):
    on: str = Field(pattern=r"^US-\d{3,}$")
    strength: Literal["hard", "soft"] = "soft"
    reason: str = Field(default="", max_length=500)


class CoverageOut(ApiModel):
    elements: int
    covered: dict[str, list[str]]
    gaps: list[str]
    out_of_scope: list[str]
    untraced_stories: list[str]
    complete: bool


class PlanProblemOut(ApiModel):
    code: str
    story: str
    on: str | None
    message: str


class PlanOut(ApiModel):
    version: int
    waves: list[list[str]]
    suggested: list[list[str]]
    differs_from_suggested: bool
    errors: list[PlanProblemOut]
    warnings: list[PlanProblemOut]
    change_note: str | None
    created_by_name: str | None
    created_at: datetime


class PlanIn(ApiModel):
    waves: list[list[str]] = Field(max_length=100)
    change_note: str | None = Field(default=None, max_length=2000)


class C1CheckOut(ApiModel):
    can_approve: bool
    blockers: list[str]


class CheckOut(ApiModel):
    key: str
    title: str
    status: Literal["passed", "failed", "not_checked"]
    detail: str


class VerdictOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    module: str
    verdict: Literal["PROVEN", "PARTLY PROVEN", "NOT PROVEN"]
    checks: list[CheckOut]
    not_proven: list[str]
    has_proof_pack: bool
    created_at: datetime


class TraceRuleOut(ApiModel):
    key: str
    name: str
    priority: str
    status: str
    sources: list[str]
    target_files: list[str]
    cases: int
    matched: int
    verified: bool | None = Field(description="None until a verification ran")


class CodeExcerptOut(ApiModel):
    path: str
    first_line: int
    lines: list[str]
    highlighted: list[int]
    truncated: bool


class CodeFileEntryOut(ApiModel):
    path: str
    layer: str
    size_bytes: int
    rules: list[str]


class CodeTreeOut(ApiModel):
    run_id: uuid.UUID
    generated_at: datetime
    files: list[CodeFileEntryOut]


class CodeFileOut(ApiModel):
    path: str
    layer: str
    size_bytes: int
    content: str
    truncated: bool


# The approved design (C3) as the Architecture tab reads it: a view of the pack's design document, which the worker
# stores as JSON. Fields the tab does not show are ignored.
class DesignFieldOut(ApiModel):
    name: str
    type: str
    column: str | None = None
    legacy: str | None = None


class DesignEntityOut(ApiModel):
    name: str
    table: str | None = None
    legacy_table: str | None = None
    key: list[str] = Field(default_factory=list)
    fields: list[DesignFieldOut] = Field(default_factory=list)


class DesignPortMethodOut(ApiModel):
    name: str
    description: str = ""


class DesignPortOut(ApiModel):
    name: str
    entity: str | None = None
    legacy_program: str | None = None
    methods: list[DesignPortMethodOut] = Field(default_factory=list)


class DesignErrorOut(ApiModel):
    code: str
    legacy_code: str | None = None
    message: str = ""


class DesignUseCaseOut(ApiModel):
    name: str
    description: str = ""
    rules: list[str] = Field(default_factory=list)
    http_method: str = "POST"
    path: str = ""
    ports: list[str] = Field(default_factory=list)
    legacy_program: str | None = None
    errors: list[DesignErrorOut] = Field(default_factory=list)


class DesignDecisionOut(ApiModel):
    title: str
    context: str = ""
    decision: str
    consequences: str = ""


class DesignOut(ApiModel):
    run_id: uuid.UUID
    created_at: datetime
    context: str
    base_package: str
    entities: list[DesignEntityOut] = Field(default_factory=list)
    ports: list[DesignPortOut] = Field(default_factory=list)
    use_cases: list[DesignUseCaseOut] = Field(default_factory=list)
    decisions: list[DesignDecisionOut] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)


class OperationOut(ApiModel):
    method: str
    path: str
    name: str
    summary: str
    rules: list[str]


class ContractsOut(ApiModel):
    """The HTTP contract of the target: the OpenAPI document the frontend pack derived from the design, when there is
    one, and its operations; without a frontend the operations come straight from the design's use cases."""

    source: Literal["openapi", "design"]
    operations: list[OperationOut]
    openapi: dict[str, Any] | None


class DifferenceOut(ApiModel):
    path: str
    expected: str | None
    actual: str | None


class CaseOut(ApiModel):
    name: str
    matched: bool
    failure: str | None
    differences: list[DifferenceOut]


class TraceDetailOut(ApiModel):
    key: str
    rule: dict[str, Any]
    status: str
    legacy: list[CodeExcerptOut]
    target: list[CodeExcerptOut]
    cases: list[CaseOut]
    verified: bool | None
    verdict: Literal["PROVEN", "PARTLY PROVEN", "NOT PROVEN"] | None


class DesignSystemOut(ApiModel):
    version: int
    source: Literal["nexti-base", "client-brand"]
    tokens: dict[str, Any]
    status: str
    created_at: datetime


class PrototypeOut(ApiModel):
    id: uuid.UUID
    screen_key: str
    version: int
    origin: Literal["generated", "chat"]
    status: str
    notes: str
    open_comments: int
    created_at: datetime


class AnchorIn(ApiModel):
    field: str | None = Field(default=None, max_length=64, description="The data-field the comment is about")
    x: float | None = Field(default=None, ge=0, le=1, description="Horizontal position, 0-1 of the frame")
    y: float | None = Field(default=None, ge=0, le=1)


class CommentIn(ApiModel):
    body: str = Field(min_length=1, max_length=2000)
    anchor: AnchorIn = Field(default_factory=AnchorIn)


class CommentOut(ApiModel):
    id: uuid.UUID
    body: str
    anchor: dict[str, Any]
    resolved: bool
    author: str | None
    created_at: datetime


class ResolveIn(ApiModel):
    resolved: bool = True


class ChatIn(ApiModel):
    body: str = Field(min_length=3, max_length=2000, description="The change asked, in natural language")


class ChatMessageOut(ApiModel):
    id: uuid.UUID
    role: Literal["user", "agent"]
    body: str
    status: Literal["pending", "done", "failed", "proposal", "rejected"]
    proposal_fields: list[str]
    prototype_version: int | None
    author: str | None
    created_at: datetime


# -- independent validation (Flow 4, ADR-0025) --------------------------------------------------------------------
class IvvOut(ApiModel):
    inventory: dict[str, Any] | None
    mapping: str | None
    mapping_updated_at: datetime | None
    gaps: list[str]
    problems: list[str]
    comparison: dict[str, Any] | None
    report: str | None


class IvvMappingIn(ApiModel):
    mapping: str = Field(min_length=1)


# -- delta on an existing application (Flow 3, ADR-0026) ------------------------------------------------------------
class DeltaOut(ApiModel):
    inventory: dict[str, Any] | None
    baseline: dict[str, list[str]] | None
    design: dict[str, Any] | None
    added: list[str]
    changed: list[str]
    report: str | None
