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
