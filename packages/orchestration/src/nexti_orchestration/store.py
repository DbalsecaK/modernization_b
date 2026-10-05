"""Where the engine writes what happens (run, phases, invocations, gates, questions, events). The worker implements
it on PostgreSQL (tenant-scoped, redacted); tests use an in-memory one. Every write that a replayed node can repeat
takes a stable id, so a resumed run updates the same rows instead of duplicating them."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from nexti_orchestration.model import QuestionSpec

EventKind = Literal[
    "runStarted", "phaseStarted", "started", "completed", "failed", "verificationFailed", "selfCorrected",
    "escalated", "gateWaiting", "gateDecided", "questionAsked", "questionAnswered", "fanOut", "phaseCompleted",
    "runFinished", "info",
]  # fmt: skip
EventStatus = Literal["running", "succeeded", "failed", "waiting"]


@dataclass(frozen=True)
class Usage:
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)


class RunStore(Protocol):
    async def is_cancelled(self) -> bool: ...

    async def run_running(self, phase: str | None) -> None: ...

    async def run_waiting(
        self, reason: Literal["gate", "question", "escalation", "phaseUnavailable"], phase: str
    ) -> None: ...

    async def run_finished(
        self, status: Literal["succeeded", "failed", "cancelled"], error: str | None = None
    ) -> None: ...

    async def phase_started(self, phase: str) -> bool:
        """Mark the phase running; False when it already was (a replay: no second phaseStarted event)."""
        ...

    async def phase_finished(
        self,
        phase: str,
        status: Literal["succeeded", "failed", "waiting", "unavailable"],
        detail: str | None,
        iterations: int,
    ) -> None: ...

    async def invocation_started(
        self, invocation_id: uuid.UUID, phase: str, agent: str, iteration: int, shard: str | None = None
    ) -> None: ...

    async def invocation_finished(
        self,
        invocation_id: uuid.UUID,
        status: Literal["succeeded", "failed", "escalated"],
        summary: str | None = None,
        error: dict[str, Any] | None = None,
        usage: Usage | None = None,
    ) -> None: ...

    async def gate_requested(self, gate: str, required: bool) -> bool:
        """Record the gate; False when it was already recorded (a replay)."""
        ...

    async def reset_for_retry(self, phases: Sequence[str], gates: Sequence[str]) -> None:
        """A retry from a phase (ADR-0035): the phases from it on are pending again and their gates are asked again
        (the decisions stay in the audit log)."""
        ...

    async def question_asked(self, question_id: uuid.UUID, phase: str, question: QuestionSpec) -> bool:
        """Open the question; False when it already exists (a replay)."""
        ...

    async def event(
        self,
        kind: EventKind,
        status: EventStatus,
        message: str,
        *,
        phase: str | None = None,
        agent: str | None = None,
        invocation_id: uuid.UUID | None = None,
        usage: Usage | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...
