"""The engine of a run (spec 10, 11.1): a LangGraph graph composed from the project's configuration, with gates,
questions and the do -> verify -> correct loop. The worker runs it; the API never imports this package."""

from nexti_orchestration.context import Attempt, NeedsAnswer, PhaseContext, RunStoppedError, Verification
from nexti_orchestration.graph import Executor, RunState, build_graph, compile_graph, pending_interrupts, thread_config
from nexti_orchestration.model import (
    AgentSpec,
    Answer,
    PhaseFailedError,
    PhaseResult,
    PhaseSpec,
    PhaseUnavailableError,
    QuestionSpec,
    RunContext,
)
from nexti_orchestration.preflight import Check, Preflight, PreflightProbe
from nexti_orchestration.registry import executors_for
from nexti_orchestration.store import RunStore, Usage

__all__ = [
    "AgentSpec",
    "Answer",
    "Attempt",
    "Check",
    "Executor",
    "NeedsAnswer",
    "PhaseContext",
    "PhaseFailedError",
    "PhaseResult",
    "PhaseSpec",
    "PhaseUnavailableError",
    "Preflight",
    "PreflightProbe",
    "QuestionSpec",
    "RunContext",
    "RunState",
    "RunStoppedError",
    "RunStore",
    "Usage",
    "Verification",
    "build_graph",
    "compile_graph",
    "executors_for",
    "pending_interrupts",
    "thread_config",
]
