"""What the engine knows about a run: built by the worker from the project's configuration version, so the same run
always rebuilds the same graph (its checkpoints stay valid)."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Autonomy = Literal["guided", "balanced", "autonomous"]
RunKind = Literal["pipeline", "demo"]
GATES = ("C1", "C2", "C3", "C4")
# Autonomous projects only stop at the spec and the sign-off (10.4).
AUTONOMOUS_GATES = ("C1", "C4")
# Stable namespace for the ids of the rows a node writes: a replayed node writes the same rows again (idempotent).
ID_NAMESPACE = uuid.UUID("7b9d3a3e-7f7e-4c1e-9a55-2a3c1f5d9e10")


@dataclass(frozen=True)
class PhaseSpec:
    key: str
    gate: str | None
    agent_required: bool


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    phases: tuple[str, ...]
    mandatory: bool


@dataclass(frozen=True)
class RunContext:
    run_id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    kind: RunKind
    flow: str
    phases: tuple[PhaseSpec, ...]
    template_gates: tuple[str, ...]
    autonomy: Autonomy
    max_iterations: int
    agents: tuple[AgentSpec, ...]
    options: dict[str, Any] = field(default_factory=dict)
    target: dict[str, str] = field(default_factory=dict)  # the five axes of the target (8.4): backend, database...

    @property
    def required_gates(self) -> tuple[str, ...]:
        """The gates that stop the run: the template's, reduced to C1 and C4 for autonomous projects."""
        if self.autonomy == "autonomous":
            return tuple(g for g in self.template_gates if g in AUTONOMOUS_GATES)
        return self.template_gates

    def agents_of(self, phase: str) -> tuple[AgentSpec, ...]:
        return tuple(a for a in self.agents if phase in a.phases)

    def stable_id(self, *parts: object) -> uuid.UUID:
        return uuid.uuid5(ID_NAMESPACE, "/".join([str(self.run_id), *map(str, parts)]))


@dataclass(frozen=True)
class Evidence:
    kind: Literal["code", "document", "test", "rule", "log", "analysis"]
    reference: str
    excerpt: str = ""


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    rationale: str = ""
    confidence: float | None = None  # when an analysis proposed it (ADR-0045)
    instruction: str = ""  # what the next attempt is told when this option is chosen


@dataclass(frozen=True)
class Explanation:
    """What a person sees when attempts run out (ADR-0045): the files of the last attempt and the version before,
    the diagnostic, and an analysis with proposed answers. Built by the phase, which knows the files."""

    evidence: tuple[Evidence, ...] = ()
    recommended: Option | None = None
    alternatives: tuple[Option, ...] = ()
    confidence: float | None = None
    summary: str = ""  # the cause in plain words, shown before the diagnostic


@dataclass(frozen=True)
class QuestionSpec:
    """A decision card (10.4): the recommended option comes first and is preselected in the UI."""

    key: str  # stable within the phase: the same question on a replay
    agent: str
    text: str
    context: str
    reason: Literal["lowConfidence", "contradiction", "judgesDisagree", "missingInformation", "retriesExhausted"]
    impact: Literal["high", "low"]
    recommended: Option
    confidence: float
    alternatives: tuple[Option, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    affects: tuple[str, ...] = ()


@dataclass(frozen=True)
class Answer:
    option: str | None  # the chosen option key, or None for a free-text answer
    text: str
    by: str | None = None
    comment: str = ""  # the person's comment: with a retry it is the instruction for the next attempt


class PhaseUnavailableError(Exception):
    """The phase has no executor in this version: the run waits, it never skips a phase (11.1)."""


@dataclass(frozen=True)
class PhaseResult:
    summary: str
    artifacts: dict[str, str] = field(default_factory=dict)  # name -> object key (references only, 10.2)


class PhaseFailedError(Exception):
    """The phase failed for a reason no retry fixes (for example a failed preflight a person chose not to fix)."""
