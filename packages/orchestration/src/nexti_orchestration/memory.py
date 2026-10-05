"""An in-memory RunStore with the same idempotency as the PostgreSQL one: for tests of the engine."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from nexti_orchestration.model import QuestionSpec
from nexti_orchestration.store import EventKind, EventStatus, Usage


@dataclass
class RecordedEvent:
    kind: EventKind
    status: EventStatus
    message: str
    phase: str | None
    agent: str | None
    invocation_id: uuid.UUID | None
    usage: Usage | None
    payload: dict[str, Any]


@dataclass
class MemoryStore:
    cancelled: bool = False
    status: str = "queued"
    waiting_reason: str | None = None
    current_phase: str | None = None
    error: str | None = None
    phases: dict[str, dict[str, Any]] = field(default_factory=dict)
    invocations: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    questions: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    events: list[RecordedEvent] = field(default_factory=list)
    invocation_starts: int = 0

    async def is_cancelled(self) -> bool:
        return self.cancelled

    def _final(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    async def run_running(self, phase: str | None) -> None:
        if self._final():
            return
        self.status, self.waiting_reason = "running", None
        if phase is not None:
            self.current_phase = phase

    async def run_waiting(self, reason: str, phase: str) -> None:
        if self._final():
            return
        self.status, self.waiting_reason, self.current_phase = "waiting", reason, phase

    async def run_finished(self, status: str, error: str | None = None) -> None:
        if self._final():
            return
        self.status, self.error, self.waiting_reason = status, error, None

    async def phase_started(self, phase: str) -> bool:
        current = self.phases.get(phase)
        if current and current["status"] in ("running", "waiting", "unavailable"):
            current["status"] = "running"
            return False
        self.phases[phase] = {"status": "running", "detail": None, "iterations": 0}
        return True

    async def phase_finished(self, phase: str, status: str, detail: str | None, iterations: int) -> None:
        self.phases[phase] = {"status": status, "detail": detail, "iterations": iterations}

    async def invocation_started(
        self, invocation_id: uuid.UUID, phase: str, agent: str, iteration: int, shard: str | None = None
    ) -> None:
        self.invocation_starts += 1
        self.invocations[invocation_id] = {
            "phase": phase, "agent": agent, "iteration": iteration, "shard": shard, "status": "running",
        }  # fmt: skip

    async def invocation_finished(
        self,
        invocation_id: uuid.UUID,
        status: str,
        summary: str | None = None,
        error: dict[str, Any] | None = None,
        usage: Usage | None = None,
    ) -> None:
        self.invocations[invocation_id].update(status=status, summary=summary, error=error, usage=usage)

    async def gate_requested(self, gate: str, required: bool) -> bool:
        if gate in self.gates:
            return False
        self.gates[gate] = {"required": required, "status": "pending"}
        return True

    async def reset_for_retry(self, phases: Sequence[str], gates: Sequence[str]) -> None:
        for phase in phases:
            self.phases.pop(phase, None)
        for gate in gates:
            self.gates.pop(gate, None)

    async def question_asked(self, question_id: uuid.UUID, phase: str, question: QuestionSpec) -> bool:
        if question_id in self.questions:
            return False
        self.questions[question_id] = {"phase": phase, "question": question, "status": "open"}
        return True

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
    ) -> None:
        self.events.append(RecordedEvent(kind, status, message, phase, agent, invocation_id, usage, payload or {}))

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]
