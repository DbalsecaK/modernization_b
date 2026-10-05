"""The engine with the in-memory store and checkpointer: gates stop the run, questions wait for an answer without
repeating work, do -> verify -> correct respects the maximum of iterations, a phase without executor waits, and the
preflight asks before spending anything (spec 10.4, 11.1; plan M3 section 5)."""

import io
import json
import uuid
import zipfile
from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nexti_orchestration import (
    AgentSpec,
    Check,
    PhaseSpec,
    RunContext,
    compile_graph,
    executors_for,
    pending_interrupts,
    thread_config,
)
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.preflight import LISTER
from nexti_sandbox import DockerSandbox, Limits, SandboxResult

PHASES = (
    PhaseSpec("preflight", None, False),
    PhaseSpec("ruleExtraction", None, True),
    PhaseSpec("ruleReview", "C1", False),
    PhaseSpec("design", "C3", True),
    PhaseSpec("generation", None, True),
    PhaseSpec("verification", "C4", True),
)
AGENTS = (
    AgentSpec("rules-extractor", "Rules extractor", ("ruleExtraction",), True),
    AgentSpec("architect", "Architect", ("design",), True),
    AgentSpec("coder", "Coder", ("generation",), True),
    AgentSpec("verifier", "Verifier", ("verification",), True),
)


class FakeSandbox:
    """Answers like the sandbox without running anything: the demo test passes when the module adds no offset."""

    def __init__(self, listing: dict[str, Any] | None = None) -> None:
        self.listing = listing
        self.calls = 0

    async def run(
        self, command: list[str], files: Mapping[str, bytes] | None = None, limits: Limits | None = None
    ) -> SandboxResult:
        self.calls += 1
        files = files or {}
        if "module.py" in files:
            ok = b"+ 0\n" in files["module.py"]
            stderr = "" if ok else "AssertionError: expected 42, got 43"
            return SandboxResult(0 if ok else 1, "1 passed" if ok else "", stderr, False, 5)
        return SandboxResult(0, json.dumps(self.listing or {}), "", False, 5)


class FakeProbe:
    def __init__(self, failing: set[str] | None = None, archives: dict[str, bytes] | None = None) -> None:
        self.failing = failing or set()
        self.archives_by_name = archives or {}

    def _check(self, name: str) -> Check:
        return Check(name, name not in self.failing, f"{name} {'missing' if name in self.failing else 'ok'}")

    async def inputs(self) -> Check:
        return self._check("inputs")

    async def secrets(self) -> Check:
        return self._check("secrets")

    async def repository(self) -> Check:
        return self._check("repository")

    async def models(self) -> Check:
        return self._check("models")

    async def budget(self) -> Check:
        return self._check("budget")

    async def archives(self) -> Mapping[str, bytes]:
        return self.archives_by_name


def context(
    kind: str = "demo",
    *,
    gates: tuple[str, ...] = ("C1", "C4"),
    autonomy: str = "balanced",
    max_iterations: int = 3,
    options: dict[str, Any] | None = None,
    phases: tuple[PhaseSpec, ...] = PHASES,
) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        kind=kind,  # type: ignore[arg-type]
        flow="modernization",
        phases=phases,
        template_gates=gates,
        autonomy=autonomy,  # type: ignore[arg-type]
        max_iterations=max_iterations,
        agents=AGENTS,
        options=options or {},
    )


class Harness:
    def __init__(self, run: RunContext, probe: FakeProbe | None = None, sandbox: FakeSandbox | None = None) -> None:
        self.run = run
        self.store = MemoryStore()
        self.sandbox = sandbox or FakeSandbox()
        self.graph = compile_graph(
            run, self.store, executors_for(run, probe or FakeProbe()), InMemorySaver(), self.sandbox
        )

    async def start(self) -> list[dict[str, Any]]:
        await self.graph.ainvoke({}, thread_config(self.run))
        return await pending_interrupts(self.graph, self.run)

    async def resume(self, value: Any) -> list[dict[str, Any]]:
        await self.graph.ainvoke(Command(resume=value), thread_config(self.run))
        return await pending_interrupts(self.graph, self.run)

    async def restart(self, phase: str) -> list[dict[str, Any]]:
        """What the worker does with a finished run queued again with `retry_from` (ADR-0035)."""
        await self.graph.ainvoke({"resume_from": phase}, thread_config(self.run))
        return await pending_interrupts(self.graph, self.run)

    async def answer_all(self, option: str) -> list[dict[str, Any]]:
        (waiting,) = await pending_interrupts(self.graph, self.run)
        return await self.resume({q: {"option": option, "text": "", "by": "tester"} for q in waiting["question_ids"]})

    def invocations(self, phase: str) -> list[dict[str, Any]]:
        return [i for i in self.store.invocations.values() if i["phase"] == phase]


async def test_a_required_gate_stops_the_run_until_it_is_approved() -> None:
    h = Harness(context())
    waiting = await h.start()
    assert waiting == [{"type": "gate", "gate": "C1", "phase": "ruleReview"}]
    assert (h.store.status, h.store.waiting_reason) == ("waiting", "gate")
    assert h.store.phases["preflight"]["status"] == "succeeded"
    assert "generation" not in h.store.phases

    waiting = await h.resume({"decision": "approved", "by": "reviewer"})
    # C3 is not in the template: recorded for an asynchronous review, the run goes on to C4.
    assert waiting == [{"type": "gate", "gate": "C4", "phase": "verification"}]
    assert h.store.gates["C3"] == {"required": False, "status": "pending"}

    assert await h.resume({"decision": "approved"}) == []
    assert h.store.status == "succeeded"
    assert h.store.kinds()[0] == "runStarted"
    assert h.store.kinds()[-1] == "runFinished"
    assert h.store.kinds().count("gateWaiting") == 2


async def test_a_rejected_gate_fails_the_run_with_the_comment() -> None:
    h = Harness(context())
    await h.start()
    waiting = await h.resume({"decision": "rejected", "comment": "Rules incomplete"})
    assert waiting == [{"type": "failed", "phase": "ruleReview"}]  # a retry would redo the phase before the gate
    assert h.store.status == "failed"
    assert h.store.error == "Gate C1 rejected: Rules incomplete"
    assert "design" not in h.store.phases


async def test_autonomous_projects_only_stop_at_c1_and_c4() -> None:
    h = Harness(context(gates=("C1", "C2", "C3", "C4"), autonomy="autonomous"))
    assert (await h.start())[0]["gate"] == "C1"
    assert (await h.resume({"decision": "approved"}))[0]["gate"] == "C4"
    assert h.store.gates["C3"]["required"] is False


async def test_generation_corrects_itself_in_parallel_shards() -> None:
    h = Harness(context(gates=()))
    assert await h.start() == []
    assert h.store.status == "succeeded"
    generation = h.invocations("generation")
    # Two shards, each fails once (fix_after=1) and passes on the second attempt.
    assert sorted((i["shard"], i["iteration"], i["status"]) for i in generation) == [
        ("module_a", 1, "failed"),
        ("module_a", 2, "succeeded"),
        ("module_b", 1, "failed"),
        ("module_b", 2, "succeeded"),
    ]
    assert h.store.kinds().count("selfCorrected") == 2
    assert h.store.kinds().count("fanOut") == 1
    assert h.store.phases["generation"]["iterations"] == 2
    failed = next(e for e in h.store.events if e.kind == "verificationFailed")
    assert "expected 42" in failed.payload["diagnostic"]


async def test_verification_that_never_passes_escalates_after_exactly_max_iterations() -> None:
    h = Harness(context(gates=(), max_iterations=3, options={"fail_verification": "design"}))
    (waiting,) = await h.start()
    assert waiting["type"] == "questions"
    assert (h.store.status, h.store.waiting_reason) == ("waiting", "escalation")
    attempts = [i for i in h.invocations("design") if i["agent"] == "architect"]
    assert [i["iteration"] for i in sorted(attempts, key=lambda i: i["iteration"])] == [1, 2, 3]
    assert [i["status"] for i in sorted(attempts, key=lambda i: i["iteration"])] == ["failed", "failed", "escalated"]
    (question,) = h.store.questions.values()
    assert question["question"].reason == "retriesExhausted"
    assert "expected 42" in question["question"].context
    assert h.store.kinds().count("escalated") == 1

    # Retry: one more round of exactly three attempts, the first three are not repeated.
    await h.answer_all("retry")
    assert len([i for i in h.invocations("design") if i["agent"] == "architect"]) == 6
    assert h.store.invocation_starts == len(h.store.invocations)

    # Stop: the run fails, and the phase never advances half done.
    assert await h.answer_all("stop") == [{"type": "failed", "phase": "design"}]
    assert h.store.status == "failed"
    assert h.store.phases["design"]["status"] == "failed"
    assert "generation" not in h.store.phases


async def test_a_question_waits_and_the_answer_does_not_repeat_the_work() -> None:
    h = Harness(context(gates=(), options={"question_phase": "ruleExtraction"}))
    (waiting,) = await h.start()
    assert waiting["phase"] == "ruleExtraction"
    assert (h.store.status, h.store.waiting_reason) == ("waiting", "question")
    (question,) = h.store.questions.values()
    assert question["question"].recommended.key == "halfUp"
    starts = h.store.invocation_starts

    assert await h.answer_all("bankers") == []
    assert h.store.status == "succeeded"
    assert "rounding: bankers" in (h.store.phases["ruleExtraction"]["detail"] or "")
    assert len(h.invocations("ruleExtraction")) == 1
    assert h.store.invocation_starts - starts == len(h.store.invocations) - starts  # nothing started twice
    assert h.store.kinds().count("questionAsked") == 1
    assert h.store.kinds().count("questionAnswered") == 1


async def test_a_cancelled_run_stops_at_the_next_phase() -> None:
    h = Harness(context())
    await h.start()
    h.store.cancelled = True
    h.store.status = "cancelled"
    assert await h.resume({"decision": "approved"}) == []
    assert h.store.status == "cancelled"
    assert "design" not in h.store.phases


async def test_a_real_pipeline_runs_the_preflight_and_waits_in_phases_from_m4() -> None:
    h = Harness(context("pipeline"))
    (waiting,) = await h.start()
    assert waiting == {"type": "phaseUnavailable", "phase": "ruleExtraction"}
    assert h.store.phases["preflight"] == {"status": "succeeded", "detail": "6 checks passed", "iterations": 0}
    assert h.store.phases["ruleExtraction"]["status"] == "unavailable"
    assert (h.store.status, h.store.waiting_reason) == ("waiting", "phaseUnavailable")
    # Resuming without an executor waits again: never skipped.
    assert (await h.resume({"available": False}))[0]["type"] == "phaseUnavailable"


async def test_a_failing_preflight_asks_and_checks_again_after_the_fix() -> None:
    probe = FakeProbe(failing={"secrets", "budget"})
    h = Harness(context("pipeline"), probe=probe)
    await h.start()
    (question,) = h.store.questions.values()
    assert "secrets: secrets missing" in question["question"].context
    assert "budget" in question["question"].context
    probe.failing = set()
    (waiting,) = await h.answer_all("retry")
    assert waiting["type"] == "phaseUnavailable"
    assert h.store.phases["preflight"]["status"] == "succeeded"


async def test_a_failing_preflight_stopped_by_a_person_fails_the_run() -> None:
    h = Harness(context("pipeline"), probe=FakeProbe(failing={"repository"}))
    await h.start()
    assert await h.answer_all("stop") == [{"type": "failed", "phase": "preflight"}]
    assert h.store.status == "failed"
    assert "repository missing" in (h.store.error or "")


async def test_a_failed_run_is_retried_from_the_failed_phase_without_repeating_the_rest() -> None:
    probe = FakeProbe(failing={"repository"})
    h = Harness(context("pipeline"), probe=probe)
    await h.start()
    assert await h.answer_all("stop") == [{"type": "failed", "phase": "preflight"}]
    assert h.store.status == "failed"
    # A person fixes the cause and retries: the API queues the run again and the worker resumes it with the retry.
    probe.failing = set()
    h.store.status = "queued"
    (waiting,) = await h.resume({"retry": True})
    assert waiting["type"] == "phaseUnavailable"  # the preflight passed; the next phase has no executor here
    assert h.store.phases["preflight"]["status"] == "succeeded"
    assert h.store.kinds().count("runStarted") == 1  # not started again
    assert "Retrying from phase preflight" in [e.message for e in h.store.events]
    # A retry may start from an earlier phase: the phases from it on run again and their gates are asked again.
    h2 = Harness(context(gates=("C1",), max_iterations=1, options={"fail_verification": "design"}))
    (waiting,) = await h2.start()
    assert waiting["type"] == "gate"  # C1 after ruleReview
    await h2.resume({"decision": "approved", "by": "reviewer"})
    assert (await h2.answer_all("stop")) == [{"type": "failed", "phase": "design"}]
    before = len(h2.invocations("ruleExtraction"))
    h2.store.status = "queued"
    (again,) = await h2.resume({"retry": True, "phase": "ruleExtraction"})
    assert again == {"type": "gate", "gate": "C1", "phase": "ruleReview"}  # asked again after the redo
    assert len(h2.invocations("ruleExtraction")) > before
    assert h2.store.gates["C1"]["status"] == "pending"
    assert "preflight" in h2.store.phases  # what came before kept its results
    # Without a retry (the person launches a new run instead) the failed run stays as it is.
    other = Harness(context("pipeline"), probe=FakeProbe(failing={"repository"}))
    await other.start()
    await other.answer_all("stop")
    assert await other.resume({"retry": False}) == []
    assert other.store.status == "failed"


async def test_a_finished_run_starts_again_from_a_chosen_phase_keeping_what_came_before() -> None:
    h = Harness(context(gates=("C1",)))
    (waiting,) = await h.start()
    assert waiting["type"] == "gate"
    assert await h.resume({"decision": "approved", "by": "reviewer"}) == []
    assert h.store.status == "succeeded"
    before = len(h.invocations("ruleExtraction"))
    started = h.store.kinds().count("runStarted")
    # The API queues the finished run with the chosen phase; the worker invokes the graph again with it.
    h.store.status = "queued"
    (again,) = await h.restart("ruleExtraction")
    assert again == {"type": "gate", "gate": "C1", "phase": "ruleReview"}  # asked again after the redo
    assert len(h.invocations("ruleExtraction")) > before
    assert h.store.kinds().count("runStarted") == started  # not started again: it went on from the phase
    assert h.store.phases["preflight"]["status"] == "succeeded"  # what came before kept its results
    assert "Retrying from phase ruleExtraction" in [e.message for e in h.store.events]
    assert await h.resume({"decision": "approved", "by": "reviewer"}) == []
    assert h.store.status == "succeeded"
    assert h.store.phases["generation"]["status"] == "succeeded"  # redone after the chosen phase


async def test_the_preflight_rejects_an_archive_that_looks_like_a_zip_bomb() -> None:
    listing = {"0.zip": {"entries": 3, "uncompressed": 10**9, "compressed": 10**5, "encrypted": 0, "unsafe": 1}}
    h = Harness(context("pipeline"), probe=FakeProbe(archives={"code.zip": b"PK"}), sandbox=FakeSandbox(listing))
    await h.start()
    (question,) = h.store.questions.values()
    assert "code.zip: compression ratio 10000:1" in question["question"].context
    assert "unsafe paths" in question["question"].context


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


async def test_the_archive_listing_runs_in_the_real_sandbox() -> None:
    sandbox = DockerSandbox(limits=Limits(timeout_seconds=60))
    if not await sandbox.available():
        pytest.skip("Docker is not available")
    files = {
        "archives/0.zip": _zip({"src/CARD01.cbl": b"MOVE 1 TO WS-X.\n", "../evil.sh": b"x"}),
        "archives/1.zip": b"not a zip",
    }
    result = await sandbox.run(["python", "-c", LISTER], files=files)
    assert result.ok, result.stderr
    report = json.loads(result.stdout)
    assert report["0.zip"]["entries"] == 2
    assert report["0.zip"]["unsafe"] == 1
    assert report["1.zip"] == {"error": "BadZipFile"}
