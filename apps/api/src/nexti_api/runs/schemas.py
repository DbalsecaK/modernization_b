"""Wire shapes of runs, phases, invocations, gates, questions, tasks and activity events."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from nexti_api.schemas import ApiModel


class RetryIn(ApiModel):
    phase: str | None = Field(
        default=None,
        description="Retry from this phase instead of the failed one; it must be the failed phase or an earlier one "
        "(ADR-0035). The phases from it on run again; what came before keeps its results.",
    )


RunStatus = Literal["queued", "running", "waiting", "succeeded", "failed", "cancelled"]
ACTIVE = ("queued", "running", "waiting")
FINAL = ("succeeded", "failed", "cancelled")


class DemoOptionsIn(ApiModel):
    """Behaviour of the demonstration pipeline (development and test only)."""

    slow_phase: str | None = Field(default=None, max_length=64)
    slow_seconds: float = Field(default=0, ge=0, le=600)
    fail_verification: str | None = Field(default=None, max_length=64)
    question_phase: str | None = Field(default=None, max_length=64)
    fix_after: int = Field(default=1, ge=0, le=10)
    shards: list[str] | None = Field(default=None, max_length=8)


class RunIn(ApiModel):
    kind: Literal["pipeline", "demo"] = "pipeline"
    options: DemoOptionsIn | None = None
    deep_inventory: bool | None = Field(
        default=None,
        description="Pipeline runs: model-written descriptions, observations and business scenarios (ADR-0032); "
        "on unless false",
    )
    guided_extraction: bool | None = Field(
        default=None,
        description="Pipeline runs: rules extracted with the program map, small programs whole, citations corrected "
        "by the verifier, P0 judged through two lenses and rules consolidated by meaning (ADR-0033); on unless false",
    )

    @model_validator(mode="after")
    def options_only_for_demo(self) -> "RunIn":
        if self.options is not None and self.kind != "demo":
            raise ValueError("options are only for demo runs")
        return self


class RunOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    config_version: int
    kind: Literal["pipeline", "demo"]
    status: RunStatus
    waiting_reason: str | None
    current_phase: str | None
    autonomy: str
    max_iterations: int
    options: dict[str, Any]
    error: str | None
    started_by: uuid.UUID | None
    started_by_name: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PhaseRunOut(ApiModel):
    phase: str
    position: int
    status: str
    iterations: int
    detail: str | None
    started_at: datetime | None
    finished_at: datetime | None


class InvocationOut(ApiModel):
    id: uuid.UUID
    phase: str
    agent_key: str
    shard: str | None
    iteration: int
    status: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    summary: str | None
    error: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None


class GateOut(ApiModel):
    gate: str
    required: bool
    status: Literal["pending", "approved", "rejected"]
    requested_at: datetime
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    comment: str | None


class QuestionOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    phase: str
    agent_key: str
    question_text: str
    context: str
    evidence: list[dict[str, Any]]
    reason: str
    impact: Literal["high", "low"]
    recommended: dict[str, Any]
    alternatives: list[dict[str, Any]]
    affects: list[str]
    status: Literal["open", "answered", "cancelled"]
    answer: str | None
    was_recommended: bool | None
    answered_by: uuid.UUID | None
    answered_by_name: str | None
    answered_at: datetime | None
    comment: str | None
    created_at: datetime


class RunDetail(RunOut):
    phases: list[PhaseRunOut]
    invocations: list[InvocationOut]
    gates: list[GateOut]
    questions: list[QuestionOut]
    cost_visible: bool


class GateDecisionIn(ApiModel):
    comment: str | None = Field(default=None, max_length=2000)


class AnswerIn(ApiModel):
    """Choose an option (the recommended one or an alternative) or write an answer."""

    option: str | None = Field(default=None, min_length=1, max_length=64)
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def one_answer(self) -> "AnswerIn":
        if (self.option is None) == (self.text is None):
            raise ValueError("give either an option or a text")
        return self


class AcceptRecommendedIn(ApiModel):
    question_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class AcceptRecommendedOut(ApiModel):
    answered: int


class TaskOut(ApiModel):
    kind: Literal["question", "gate"]
    project_id: uuid.UUID
    project_name: str
    run_id: uuid.UUID
    question_id: uuid.UUID | None = None
    gate: str | None = None
    phase: str
    title: str
    impact: Literal["high", "low"]
    created_at: datetime


class ActivityEventOut(ApiModel):
    id: int
    project_id: uuid.UUID
    run_id: uuid.UUID
    invocation_id: uuid.UUID | None
    agent_key: str | None
    phase: str | None
    kind: str
    status: str
    message: str
    model: str | None
    tokens: int
    cost_usd: Decimal | None
    payload: dict[str, Any]
    occurred_at: datetime
