"""Explainable escalation (ADR-0045): when the attempts of a step run out, the person sees the files of the last
attempt, the version before, the diagnostic and an analysis with proposed answers; a comment or an option's
instruction steers the next round."""

import json
import uuid
from decimal import Decimal
from typing import Any, cast

import pytest

from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import Attempt, NeedsAnswer, PhaseContext, RunStoppedError, Verification
from nexti_orchestration.escalation import explain_attempts, explainer, many_files, single_file
from nexti_orchestration.extraction import ModelReply
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import Explanation, Option
from nexti_orchestration.store import Usage


class FakeModels:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[list[dict[str, str]]] = []

    async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], **kw: Any) -> ModelReply:
        self.requests.append(messages)
        return ModelReply(self.replies.pop(0), Usage("fake", 10, 10, Decimal(0)))


class FakePort:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    async def save_file(self, path: str, content: str) -> str:
        reference = f"ref/{len(self.objects)}/{path}"
        self.objects[reference] = content
        return reference

    async def load_file(self, reference: str) -> str:
        return self.objects[reference]


ANALYSIS = {
    "cause": "The test file references a field its own helper does not declare.",
    "change": "Every attempt rewrote the service; the error is in the tests.",
    "options": [
        {
            "key": "retryWithInstruction",
            "label": "Fix the tests",
            "rationale": "The field is missing in Req.",
            "instruction": "Declare companyAccountNumber in the Req helper of the test file.",
            "confidence": 0.8,
        },
        {"key": "retry", "label": "Try again", "rationale": "Same inputs, same result.", "confidence": 0.1},
        {"key": "stop", "label": "Stop", "rationale": "Review by hand.", "confidence": 0.3},
        {"key": "bogus", "label": "ignored"},
    ],
}


def _ctx(max_iterations: int = 1) -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("generation", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), (),
                     "balanced", max_iterations, (), options={"guided_extraction": True})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


async def test_the_explanation_carries_the_last_attempt_the_version_before_and_the_analysis() -> None:
    port = FakePort()
    first = await port.save_file("Svc.java", "class Svc { int v = 1; }")
    second = await port.save_file("Svc.java", "class Svc { int v = 2; }")
    memos = [
        {"ok": False, "artifact": {"file": first}, "summary": "Svc", "diagnostic": "expected 2"},
        {"ok": False, "artifact": {"file": second}, "summary": "Svc", "diagnostic": "expected 3"},
    ]
    models = FakeModels([json.dumps(ANALYSIS)])
    found = await explain_attempts(port, cast(Any, models), "Svc", memos, "expected 3", single_file("Svc.java"))
    kinds = [(e.kind, e.reference) for e in found.evidence]
    assert kinds == [("log", "diagnostic"), ("code", "Svc.java#attempt-2"), ("code", "Svc.java#before"),
                     ("analysis", "model")]  # fmt: skip
    assert found.evidence[1].excerpt == "class Svc { int v = 2; }"
    assert found.evidence[2].excerpt == "class Svc { int v = 1; }"
    assert found.recommended is not None
    assert (found.recommended.key, found.recommended.confidence) == ("retryWithInstruction", 0.8)
    assert found.recommended.instruction.startswith("Declare companyAccountNumber")
    assert [o.key for o in found.alternatives] == ["retry", "stop"]  # the bogus key is dropped
    assert found.confidence == 0.8
    assert found.summary.startswith("The test file references")
    request = models.requests[0][1]["content"]
    assert "attempt 1: Svc; verification: expected 2" in request
    assert "### Svc.java (last attempt)" in request
    assert "### Svc.java (version before)" in request
    # Without models (a run that is not guided): the evidence alone, no call, default options.
    plain = await explain_attempts(port, None, "Svc", memos, "expected 3", single_file("Svc.java"))
    assert plain.recommended is None
    assert [e.kind for e in plain.evidence] == ["log", "code", "code"]


async def test_the_convergence_explanation_compares_with_the_kept_base_and_an_unusable_reply_keeps_the_files() -> None:
    port = FakePort()
    ref = await port.save_file("a/Service.java", "v2")
    memos = [
        {"ok": False, "artifact": {"problem": "no usable answer"}, "summary": "none", "diagnostic": "unusable"},
        {"ok": False, "artifact": {"files": {"a/Service.java": ref}}, "summary": "corrected", "diagnostic": "d"},
    ]
    base = {"a/Service.java": "v1", "a/Other.java": "x"}
    explain = explainer(port, cast(Any, FakeModels(["not json at all"])), "what", many_files, lambda: base)
    found = await explain(memos, "d")
    assert [(e.kind, e.reference, e.excerpt) for e in found.evidence] == [
        ("log", "diagnostic", "d"), ("code", "a/Service.java#attempt-2", "v2"), ("code", "a/Service.java#before", "v1"),
    ]  # fmt: skip
    assert found.recommended is None  # no analysis: the defaults apply, the person still decides


async def test_when_attempts_run_out_the_question_shows_the_evidence_and_the_answer_steers_the_next_round() -> None:
    port = FakePort()
    seen: list[str | None] = []

    async def work(iteration: int, feedback: str | None) -> Attempt:
        seen.append(feedback)
        return Attempt({"file": await port.save_file("Svc.java", f"v{iteration}")}, f"v{iteration}", None)

    async def verify(artifact: dict[str, Any]) -> Verification:
        return Verification(len(seen) >= 3, "expected 42")

    async def explain(memos: Any, feedback: str | None) -> Explanation:
        found = await explain_attempts(port, cast(Any, FakeModels([json.dumps(ANALYSIS)])), "Svc", memos, feedback,
                                       single_file("Svc.java"))  # fmt: skip
        return found

    ctx, _store = _ctx(max_iterations=1)
    with pytest.raises(NeedsAnswer) as asked:
        await ctx.do_verify_correct("backend-dev", work, verify, what="Svc", explain=explain)
    (question_id, question) = asked.value.questions[0]
    assert question.reason == "retriesExhausted"
    assert question.context.startswith("The test file references a field")
    assert "expected 42" in question.context
    assert question.recommended.key == "retryWithInstruction"
    assert question.confidence == 0.8
    assert [o.key for o in question.alternatives] == ["retry", "stop"]
    assert [e.kind for e in question.evidence] == ["log", "code", "analysis"]
    # The recommended option carries its instruction: the next round is told.
    ctx.answers[str(question_id)] = {"option": "retryWithInstruction", "text": "retryWithInstruction", "by": "u"}
    with pytest.raises(NeedsAnswer) as asked:
        await ctx.do_verify_correct("backend-dev", work, verify, what="Svc", explain=explain)
    assert seen[1] is not None
    assert seen[1].endswith(
        "Instruction from the reviewer: Declare companyAccountNumber in the Req helper of the test file."
    )
    # A comment with a plain retry is the instruction too; stop ends the run.
    (question_id, _) = asked.value.questions[0]
    ctx.answers[str(question_id)] = {"option": "retry", "text": "retry", "by": "u", "comment": "Round the amount."}
    attempt = await ctx.do_verify_correct("backend-dev", work, verify, what="Svc", explain=explain)
    assert attempt.summary == "v3"
    assert seen[2] is not None
    assert seen[2].endswith("Instruction from the reviewer: Round the amount.")


async def test_an_explanation_that_fails_never_blocks_the_question() -> None:
    port = FakePort()

    async def work(iteration: int, feedback: str | None) -> Attempt:
        return Attempt({"file": await port.save_file("Svc.java", "v")}, "v", None)

    async def verify(artifact: dict[str, Any]) -> Verification:
        return Verification(False, "no")

    async def explain(memos: Any, feedback: str | None) -> Explanation:
        raise RuntimeError("the analyst is down")

    ctx, store = _ctx(max_iterations=1)
    with pytest.raises(NeedsAnswer) as asked:
        await ctx.do_verify_correct("backend-dev", work, verify, what="Svc", explain=explain)
    (_, question) = asked.value.questions[0]
    assert (question.recommended.key, [o.key for o in question.alternatives]) == ("retry", ["stop"])
    assert question.evidence == ()
    assert any("could not be explained" in e.message for e in store.events)
    (question_id, _) = asked.value.questions[0]
    ctx.answers[str(question_id)] = {"option": "stop", "text": "stop", "by": "u"}
    with pytest.raises(RunStoppedError):
        await ctx.do_verify_correct("backend-dev", work, verify, what="Svc", explain=explain)


def test_options_are_kept_only_with_known_keys_and_an_instruction_when_they_need_one() -> None:
    from nexti_orchestration.escalation import _option

    assert _option({"key": "retryWithInstruction", "label": "x"}) is None  # no instruction: not actionable
    assert _option({"key": "stop", "confidence": "high"}) == Option("stop", "Stop the run", "", 0.5, "")
    assert _option({"key": "retry", "confidence": 7}) == Option("retry", "Try again", "", 1.0, "")
