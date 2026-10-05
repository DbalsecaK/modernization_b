"""The run as a LangGraph graph composed from the project's configuration (spec 10.1, 10.4, 11.1).

    start -> phase.<p1> -> [gate.<p1>] -> phase.<p2> -> ... -> finish
               |  ^             |
               v  |             v (rejected)
            ask.<p1>          fail

Each phase node runs the phase's executor. A question from the executor sends the run to `ask.<phase>`, which waits
with `interrupt` and returns to the phase with the answers (the phase's journal avoids repeating its work). A gate
node after a phase with a required gate waits with `interrupt` for the decision; a non-required gate is recorded for
an asynchronous review. A phase without an executor in this version waits in `wait.<phase>` (never skipped, 11.1).

The graph only holds references (ids, object keys, the journal of small results): the checkpointer and its tables
never see customer data (10.2, ADR-0009). What resumes an interrupt is decided by the worker from the database:
answered questions, a decided gate, a phase that became available.
"""

from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from nexti_core.run_phase import CURRENT_PHASE
from nexti_orchestration.context import Memo, NeedsAnswer, PhaseContext, RunStoppedError
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseSpec, PhaseUnavailableError, RunContext
from nexti_orchestration.store import RunStore
from nexti_sandbox import Sandbox


class Executor(Protocol):
    async def __call__(self, ctx: PhaseContext) -> PhaseResult: ...


class RunState(TypedDict, total=False):
    journal: dict[str, dict[str, Memo]]  # phase -> the results of its steps while it is not finished
    answers: dict[str, Memo]  # question id -> the person's answer
    pending: list[str]  # the question ids the current phase is waiting for
    artifacts: dict[str, str]  # name -> object key
    outcome: str  # why the run failed
    failed_phase: str  # the phase a failed run may be retried from (ADR-0034)
    resume_from: str  # a finished run invoked again starts over from this phase (ADR-0035)
    retries: dict[str, int]  # phase -> how many times it was retried (its questions and invocations get new ids)


def phase_node_name(phase: str) -> str:
    return f"phase.{phase}"


def _iterations(journal: Mapping[str, Memo]) -> int:
    """The highest attempt number of any agent in the phase (1 when it ran agents without retrying)."""
    highest = 0
    for key in journal:
        parts = key.split("/")
        if len(parts) >= 4 and parts[1] in ("dvc", "invoke") and parts[3].isdigit():
            highest = max(highest, int(parts[3]))
    return highest


def build_graph(
    run: RunContext, store: RunStore, executors: Mapping[str, Executor], sandbox: Sandbox | None = None
) -> StateGraph[RunState]:
    phases = run.phases
    if not phases:
        raise ValueError("a run needs at least one phase")
    graph: StateGraph[RunState] = StateGraph(RunState)

    def after_phase(index: int) -> str:
        phase = phases[index]
        if phase.gate:
            return f"gate.{phase.key}"
        return after_gate(index)

    def after_gate(index: int) -> str:
        return phase_node_name(phases[index + 1].key) if index + 1 < len(phases) else "finish"

    async def restart(state: RunState, target: str, ceiling: str) -> Command[str]:
        """The run goes on from `target` (at most `ceiling`): the phases from it on start over, with their gates
        asked again and fresh ids for their questions and invocations; what came before keeps its results."""
        keys = [p.key for p in phases]
        if target not in keys or keys.index(target) > keys.index(ceiling):
            target = ceiling
        redo = keys[keys.index(target) :]
        await store.reset_for_retry(redo, [p.gate for p in phases[keys.index(target) :] if p.gate])
        await store.run_running(target)
        await store.event("info", "running", f"Retrying from phase {target}", phase=target)
        # The redone phases start over: their journals and the answers to their questions do not carry over.
        journals = {k: v for k, v in (state.get("journal") or {}).items() if k not in redo}
        previous = dict(state.get("retries") or {})
        retries = {**previous, **{k: int(previous.get(k, 0)) + 1 for k in redo}}
        update: RunState = {"outcome": "", "failed_phase": "", "resume_from": "", "journal": journals, "pending": [],
                            "retries": retries}  # fmt: skip
        return Command(goto=phase_node_name(target), update=update)

    async def start(state: RunState) -> Command[str]:
        if await store.is_cancelled():
            return Command(goto=END)
        if target := str(state.get("resume_from") or ""):
            # A finished run invoked again (ADR-0035): a NOT PROVEN delivery redone from the design, for instance.
            return await restart(state, target, phases[-1].key)
        await store.run_running(None)
        await store.event("runStarted", "running", f"Run started ({run.kind}, flow {run.flow})")
        return Command(goto=phase_node_name(phases[0].key))

    def make_phase(index: int, phase: PhaseSpec) -> Any:
        async def node(state: RunState) -> Command[str]:
            if await store.is_cancelled():
                return Command(goto=END)
            journals = dict(state.get("journal") or {})
            journal = dict(journals.get(phase.key) or {})
            CURRENT_PHASE.set(phase.key)  # the stores tag what this phase produces (ADR-0035)
            if await store.phase_started(phase.key):
                await store.event("phaseStarted", "running", f"Phase {phase.key} started", phase=phase.key)
            await store.run_running(phase.key)
            ctx = PhaseContext(run, store, phase, sandbox, journal=journal, answers=dict(state.get("answers") or {}),
                               retry=int((state.get("retries") or {}).get(phase.key, 0)))  # fmt: skip
            executor = executors.get(phase.key)
            try:
                if executor is None:
                    raise PhaseUnavailableError(f"Phase {phase.key} is available from M4")
                result = await executor(ctx)
            except NeedsAnswer as waiting:
                pending: list[str] = []
                for question_id, question in waiting.questions:
                    if await store.question_asked(question_id, phase.key, question):
                        await store.event(
                            "questionAsked", "waiting", question.text, phase=phase.key, agent=question.agent,
                            payload={"question_id": str(question_id), "impact": question.impact,
                                     "reason": question.reason},
                        )  # fmt: skip
                    pending.append(str(question_id))
                escalation = any(q.reason == "retriesExhausted" for _, q in waiting.questions)
                await store.phase_finished(phase.key, "waiting", str(waiting), _iterations(journal))
                await store.run_waiting("escalation" if escalation else "question", phase.key)
                journals[phase.key] = journal
                return Command(goto=f"ask.{phase.key}", update={"journal": journals, "pending": pending})
            except PhaseUnavailableError as unavailable:
                await store.phase_finished(phase.key, "unavailable", str(unavailable), 0)
                await store.event("info", "waiting", str(unavailable), phase=phase.key)
                await store.run_waiting("phaseUnavailable", phase.key)
                return Command(goto=f"wait.{phase.key}")
            except (RunStoppedError, PhaseFailedError) as stopped:
                await store.phase_finished(phase.key, "failed", str(stopped)[:2000], _iterations(journal))
                await store.event("failed", "failed", f"Phase {phase.key} failed: {stopped}"[:2000], phase=phase.key)
                return Command(goto="fail", update={"outcome": str(stopped)[:2000], "failed_phase": phase.key})
            await store.phase_finished(phase.key, "succeeded", result.summary, _iterations(journal))
            await store.event(
                "phaseCompleted", "succeeded", f"{phase.key}: {result.summary}"[:2000], phase=phase.key,
                payload={"artifacts": result.artifacts},
            )  # fmt: skip
            journals.pop(phase.key, None)
            return Command(
                goto=after_phase(index),
                update={"journal": journals, "artifacts": {**(state.get("artifacts") or {}), **result.artifacts}},
            )

        return node

    def make_ask(phase: PhaseSpec) -> Any:
        async def node(state: RunState) -> Command[str]:
            pending = list(state.get("pending") or [])
            received: dict[str, Memo] = interrupt({"type": "questions", "phase": phase.key, "question_ids": pending})
            if await store.is_cancelled():
                return Command(goto=END)
            answers = dict(state.get("answers") or {})
            for question_id in pending:
                answer = (received or {}).get(question_id)
                if answer is not None and question_id not in answers:
                    answers[question_id] = answer
                    await store.event(
                        "questionAnswered", "succeeded", "Question answered", phase=phase.key,
                        payload={"question_id": question_id, "option": answer.get("option")},
                    )  # fmt: skip
            still = [q for q in pending if q not in answers]
            if still:
                return Command(goto=f"ask.{phase.key}", update={"answers": answers, "pending": still})
            return Command(goto=phase_node_name(phase.key), update={"answers": answers, "pending": []})

        return node

    def make_wait(phase: PhaseSpec) -> Any:
        async def node(state: RunState) -> Command[str]:
            interrupt({"type": "phaseUnavailable", "phase": phase.key})
            return Command(goto=phase_node_name(phase.key))

        return node

    def make_gate(index: int, phase: PhaseSpec, gate: str) -> Any:
        async def node(state: RunState) -> Command[str]:
            if await store.is_cancelled():
                return Command(goto=END)
            required = gate in run.required_gates
            new = await store.gate_requested(gate, required)
            if not required:
                if new:
                    await store.event(
                        "info", "succeeded", f"Gate {gate} recorded for asynchronous review", phase=phase.key
                    )
                return Command(goto=after_gate(index))
            if new:
                await store.event(
                    "gateWaiting", "waiting", f"Gate {gate} waiting for approval", phase=phase.key,
                    payload={"gate": gate},
                )  # fmt: skip
            await store.run_waiting("gate", phase.key)
            decision: Memo = interrupt({"type": "gate", "gate": gate, "phase": phase.key})
            if await store.is_cancelled():
                return Command(goto=END)
            approved = decision.get("decision") == "approved"
            await store.event(
                "gateDecided", "succeeded" if approved else "failed",
                f"Gate {gate} {'approved' if approved else 'rejected'}", phase=phase.key,
                payload={"gate": gate, "decision": decision.get("decision")},
            )  # fmt: skip
            if not approved:
                comment = str(decision.get("comment") or "").strip()
                outcome = f"Gate {gate} rejected" + (f": {comment}" if comment else "")
                return Command(goto="fail", update={"outcome": outcome, "failed_phase": phase.key})
            await store.run_running(phase.key)
            return Command(goto=after_gate(index))

        return node

    async def finish(state: RunState) -> Command[str]:
        await store.run_finished("succeeded")
        await store.event("runFinished", "succeeded", "Run finished")
        return Command(goto=END)

    async def fail(state: RunState) -> Command[str]:
        outcome = state.get("outcome") or "Run failed"
        await store.run_finished("failed", outcome)
        await store.event("runFinished", "failed", outcome[:2000])
        return Command(goto="retry" if state.get("failed_phase") else END)

    async def retry(state: RunState) -> Command[str]:
        """A failed run waits here (ADR-0034): a person may retry it from the phase that failed, and the phases
        before it keep their results. Without a retry it stays failed."""
        phase_key = str(state.get("failed_phase") or "")
        decision: Memo = interrupt({"type": "failed", "phase": phase_key})
        if not decision.get("retry") or await store.is_cancelled():
            return Command(goto=END)
        # A person may start again from an earlier phase (a design to redo after a failed verification).
        return await restart(state, str(decision.get("phase") or phase_key), phase_key)

    graph.add_node("start", start)
    graph.add_edge(START, "start")
    for index, phase in enumerate(phases):
        graph.add_node(phase_node_name(phase.key), make_phase(index, phase))
        graph.add_node(f"ask.{phase.key}", make_ask(phase))
        graph.add_node(f"wait.{phase.key}", make_wait(phase))
        if phase.gate:
            graph.add_node(f"gate.{phase.key}", make_gate(index, phase, phase.gate))
    graph.add_node("finish", finish)
    graph.add_node("fail", fail)
    graph.add_node("retry", retry)
    return graph


def compile_graph(
    run: RunContext,
    store: RunStore,
    executors: Mapping[str, Executor],
    checkpointer: BaseCheckpointSaver[Any],
    sandbox: Sandbox | None = None,
) -> CompiledStateGraph[RunState, None, RunState, RunState]:
    return build_graph(run, store, executors, sandbox).compile(checkpointer=checkpointer)


def thread_config(run: RunContext) -> RunnableConfig:
    """One checkpoint thread per run."""
    return {"configurable": {"thread_id": str(run.run_id)}, "recursion_limit": 10_000}


async def pending_interrupts(
    compiled: CompiledStateGraph[RunState, None, RunState, RunState], run: RunContext
) -> list[dict[str, Any]]:
    """What the run is waiting for (a gate, answers, a phase), or [] when it is not interrupted."""
    snapshot = await compiled.aget_state(thread_config(run))
    return [dict(i.value) for i in snapshot.interrupts if isinstance(i.value, dict)]
