"""What a phase executor works with: the run, the store, the sandbox, questions to a person and the
do -> verify -> correct loop (spec 10.4, 11.1).

A question never blocks inside a phase node. `ask` raises `NeedsAnswer`; the graph records the question, checkpoints
and waits in a separate node; when the answer arrives the phase runs again. The work done before the question is not
repeated: every step goes through `step`, whose result is kept in the phase's journal (part of the graph state), so
the second run replays the journal instead of calling agents again.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import partial
from typing import Any, TypeVar

from nexti_orchestration.model import Answer, Option, PhaseFailedError, PhaseSpec, QuestionSpec, RunContext
from nexti_orchestration.store import RunStore, Usage
from nexti_sandbox import Sandbox

T = TypeVar("T")
Memo = dict[str, Any]


class RunStoppedError(Exception):
    """A person chose to stop the run (an escalation or a failed preflight answered with "stop")."""


class NeedsAnswer(Exception):
    """The phase cannot go on without a person: the graph records these questions and waits."""

    def __init__(self, questions: Sequence[tuple[uuid.UUID, QuestionSpec]]) -> None:
        super().__init__(f"{len(questions)} question(s) waiting for an answer")
        self.questions = list(questions)


@dataclass(frozen=True)
class Verification:
    ok: bool
    diagnostic: str = ""
    progress: bool = False  # not passed, but closer than before: it does not count against the attempts (ADR-0043)


ATTEMPTS_AT_MOST = 4  # times `max_iterations`: the absolute cap of a round, progress or not


@dataclass(frozen=True)
class Attempt:
    """What a unit of work returns. `artifact` must be JSON-like (references, not data: 10.2)."""

    artifact: Any
    summary: str
    usage: Usage | None = None


def _usage_memo(usage: Usage | None) -> Memo | None:
    if usage is None:
        return None
    data = asdict(usage)
    data["cost_usd"] = str(usage.cost_usd)
    return data


def _usage_from(memo: Memo | None) -> Usage | None:
    if memo is None:
        return None
    return Usage(
        model=memo.get("model"),
        input_tokens=int(memo.get("input_tokens", 0)),
        output_tokens=int(memo.get("output_tokens", 0)),
        cost_usd=Decimal(memo.get("cost_usd", "0")),
    )


def _cut(exc: BaseException) -> bool:
    """The model's answer was cut at the output limit of its profile (extraction.CutReplyError, named here to keep
    the context free of the extraction module)."""
    return type(exc).__name__ == "CutReplyError"


class PhaseContext:
    def __init__(
        self,
        run: RunContext,
        store: RunStore,
        phase: PhaseSpec,
        sandbox: Sandbox | None,
        *,
        journal: dict[str, Memo] | None = None,
        answers: dict[str, Memo] | None = None,
        shard: str | None = None,
        retry: int = 0,
    ) -> None:
        self.run = run
        self.store = store
        self.phase = phase
        self.sandbox = sandbox
        self.journal = journal if journal is not None else {}
        self.answers = answers if answers is not None else {}
        self.shard = shard
        self.retry = retry  # how many times the phase was retried after failing (ADR-0034): new ids each time

    def for_shard(self, shard: str) -> "PhaseContext":
        return PhaseContext(
            self.run, self.store, self.phase, self.sandbox, journal=self.journal, answers=self.answers, shard=shard,
            retry=self.retry,
        )  # fmt: skip

    def _attempt_parts(self) -> tuple[object, ...]:
        return (f"retry{self.retry}",) if self.retry else ()

    def _key(self, *parts: object) -> str:
        return "/".join([self.shard or "", *map(str, parts)])

    def invocation_id(self, agent: str, iteration: int) -> uuid.UUID:
        return self.run.stable_id("invocation", self.phase.key, agent, self.shard or "", iteration,
                                  *self._attempt_parts())  # fmt: skip

    def question_id(self, key: str) -> uuid.UUID:
        return self.run.stable_id("question", self.phase.key, self.shard or "", key, *self._attempt_parts())

    async def step(self, key: str, fn: Callable[[], Awaitable[Memo]]) -> Memo:
        """Run `fn` once per phase: on a replay the journaled result comes back without running it again."""
        full = self._key(key)
        if full in self.journal:
            return self.journal[full]
        result = await fn()
        self.journal[full] = result
        return result

    def ask(self, question: QuestionSpec) -> Answer:
        """The person's answer if it already arrived; otherwise the phase stops here until it does."""
        question_id = self.question_id(question.key)
        answer = self.answers.get(str(question_id))
        if answer is None:
            raise NeedsAnswer([(question_id, question)])
        return Answer(option=answer.get("option"), text=str(answer.get("text", "")), by=answer.get("by"))

    async def fan_out(self, shards: Sequence[str], fn: Callable[["PhaseContext"], Awaitable[T]]) -> list[T]:
        """Run the same work over independent shards in parallel (subagents, 10.3). Questions from several shards
        are asked together; the shards that finished keep their journal and are not repeated."""
        if not self.journal.get(self._key("fanOut")):
            await self.store.event(
                "fanOut", "running", f"{self.phase.key}: {len(shards)} parallel subagents", phase=self.phase.key,
                payload={"shards": list(shards)},
            )  # fmt: skip
            self.journal[self._key("fanOut")] = {"shards": list(shards)}
        outcomes = await asyncio.gather(*(fn(self.for_shard(s)) for s in shards), return_exceptions=True)
        waiting: list[tuple[uuid.UUID, QuestionSpec]] = []
        results: list[T] = []
        for outcome in outcomes:
            if isinstance(outcome, NeedsAnswer):
                waiting.extend(outcome.questions)
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        if waiting:
            raise NeedsAnswer(waiting)
        return results

    async def invoke(
        self, agent: str, work: Callable[[], Awaitable[Attempt]], *, what: str, iteration: int = 1
    ) -> Attempt:
        """One agent invocation without verification, recorded with its usage and events."""

        async def run() -> Memo:
            invocation = self.invocation_id(agent, iteration)
            await self.store.invocation_started(invocation, self.phase.key, agent, iteration, self.shard)
            await self.store.event(
                "started", "running", what, phase=self.phase.key, agent=agent, invocation_id=invocation
            )
            try:
                attempt = await work()
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
                await self.store.invocation_finished(invocation, "failed", error=error)
                await self.store.event(
                    "failed", "failed", f"{what}: {type(exc).__name__}", phase=self.phase.key, agent=agent,
                    invocation_id=invocation, payload={"error": error},
                )  # fmt: skip
                if _cut(exc):  # asking again gives the same cut answer: the phase stops here, with what to do
                    raise PhaseFailedError(str(exc)) from exc
                raise
            await self.store.invocation_finished(invocation, "succeeded", summary=attempt.summary, usage=attempt.usage)
            await self.store.event(
                "completed", "succeeded", f"{what}: {attempt.summary}", phase=self.phase.key, agent=agent,
                invocation_id=invocation, usage=attempt.usage,
            )  # fmt: skip
            return {"artifact": attempt.artifact, "summary": attempt.summary, "usage": _usage_memo(attempt.usage)}

        memo = await self.step(f"invoke/{agent}/{iteration}", run)
        return Attempt(memo["artifact"], memo["summary"], _usage_from(memo["usage"]))

    async def do_verify_correct(
        self,
        agent: str,
        work: Callable[[int, str | None], Awaitable[Attempt]],
        verify: Callable[[Any], Awaitable[Verification]],
        *,
        what: str,
    ) -> Attempt:
        """Work, verify deterministically, correct with the concrete error: at most `max_iterations` attempts per
        round. When they run out, a person decides (retry or stop); the phase never advances half done (11.1)."""
        limit = self.run.max_iterations
        feedback: str | None = None
        round_number = 0
        iteration = 0
        while True:
            first = iteration + 1
            spent = 0  # attempts without progress: the ones that count (ADR-0043)
            while spent < limit and iteration < first - 1 + limit * ATTEMPTS_AT_MOST:
                iteration += 1
                memo = await self.step(
                    f"dvc/{agent}/{iteration}",
                    partial(self._attempt, agent, iteration, first, feedback, work, verify, what, spent),
                )
                if memo["ok"]:
                    return Attempt(memo["artifact"], memo["summary"], _usage_from(memo["usage"]))
                feedback = memo["diagnostic"]
                if not memo.get("progress"):
                    spent += 1
            escalation_key = f"escalation-{agent}-{round_number}"
            await self.step(
                f"escalated/{agent}/{round_number}",
                partial(self._escalated, agent, what, limit, feedback),
            )
            answer = self.ask(
                QuestionSpec(
                    key=escalation_key,
                    agent=agent,
                    text=f"{what} did not pass verification after {limit} attempts. How do we continue?",
                    context=(feedback or "")[:2000],
                    reason="retriesExhausted",
                    impact="high",
                    recommended=Option("retry", "Try again", "The diagnostic is attached; a new round may fix it."),
                    confidence=0.5,
                    alternatives=(Option("stop", "Stop the run", "Review the phase by hand before continuing."),),
                    affects=(self.phase.key,),
                )
            )
            if answer.option != "retry":
                raise RunStoppedError(f"{what} stopped after escalation: {answer.text or answer.option}")
            round_number += 1

    async def _attempt(
        self,
        agent: str,
        iteration: int,
        first: int,
        feedback: str | None,
        work: Callable[[int, str | None], Awaitable[Attempt]],
        verify: Callable[[Any], Awaitable[Verification]],
        what: str,
        spent: int = 0,
    ) -> Memo:
        limit = self.run.max_iterations
        invocation = self.invocation_id(agent, iteration)
        await self.store.invocation_started(invocation, self.phase.key, agent, iteration, self.shard)
        progressing = iteration - first + 1 - spent - 1  # earlier attempts of the round that made progress
        label = (f"attempt {spent + 1} of {limit}" if not progressing
                 else f"attempt {spent + 1} of {limit}, after {progressing} with progress")  # fmt: skip
        await self.store.event(
            "started", "running", f"{what} ({label})", phase=self.phase.key, agent=agent, invocation_id=invocation,
        )  # fmt: skip
        try:
            attempt = await work(iteration, feedback)
        except Exception as exc:
            if not _cut(exc):
                raise
            error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
            await self.store.invocation_finished(invocation, "failed", error=error)
            await self.store.event("failed", "failed", f"{what}: {exc}"[:2000], phase=self.phase.key, agent=agent,
                                   invocation_id=invocation, payload={"error": error})  # fmt: skip
            raise PhaseFailedError(str(exc)) from exc
        verdict = await verify(attempt.artifact)
        memo: Memo = {
            "ok": verdict.ok,
            "artifact": attempt.artifact,
            "summary": attempt.summary,
            "usage": _usage_memo(attempt.usage),
            "diagnostic": verdict.diagnostic[:2000],
            "progress": bool(verdict.progress),
        }
        if verdict.ok:
            await self.store.invocation_finished(invocation, "succeeded", summary=attempt.summary, usage=attempt.usage)
            corrected = iteration > first
            await self.store.event(
                "selfCorrected" if corrected else "completed", "succeeded",
                f"{what}: corrected and verified" if corrected else f"{what}: verified", phase=self.phase.key,
                agent=agent, invocation_id=invocation, usage=attempt.usage,
            )  # fmt: skip
            return memo
        # The round ends when the attempts without progress run out, or at the absolute cap.
        at_cap = iteration >= first - 1 + limit * ATTEMPTS_AT_MOST
        last = at_cap or (not verdict.progress and spent + 1 >= limit)
        await self.store.invocation_finished(
            invocation, "escalated" if last else "failed", summary=attempt.summary,
            error={"verification": verdict.diagnostic[:2000]}, usage=attempt.usage,
        )  # fmt: skip
        await self.store.event(
            "verificationFailed", "failed", f"{what}: verification failed", phase=self.phase.key, agent=agent,
            invocation_id=invocation, usage=attempt.usage, payload={"diagnostic": verdict.diagnostic[:2000]},
        )  # fmt: skip
        return memo

    async def _escalated(self, agent: str, what: str, limit: int, feedback: str | None) -> Memo:
        await self.store.event(
            "escalated", "waiting", f"{what}: {limit} attempts without passing verification", phase=self.phase.key,
            agent=agent, payload={"diagnostic": (feedback or "")[:2000]},
        )  # fmt: skip
        return {}
