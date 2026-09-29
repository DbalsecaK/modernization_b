"""The demonstration pipeline (development and test only, plan M3 decision 3): deterministic executors that exercise
the whole engine without models. Generation writes a small module per shard and runs its test in the sandbox,
failing on purpose the first attempts so the do -> verify -> correct loop corrects itself.

Behaviour comes from `run.options`:
    slow_phase / slow_seconds      one phase that takes time (to kill the worker inside it)
    fail_verification              a phase whose verification never passes (to reach the escalation)
    question_phase                 a phase whose agent asks a low-impact question
    fix_after                      failing attempts before generation gets it right (default 1)
    shards                         the modules generation works on in parallel (default two)
"""

import asyncio
import hashlib
from dataclasses import dataclass
from functools import partial
from typing import Any

from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.model import Option, PhaseFailedError, PhaseResult, QuestionSpec, RunContext
from nexti_orchestration.store import Usage

DEMO_MODEL = "demo-deterministic"
GENERATION_PHASES = ("generation",)


@dataclass(frozen=True)
class DemoOptions:
    slow_phase: str | None = None
    slow_seconds: float = 0
    fail_verification: str | None = None
    question_phase: str | None = None
    fix_after: int = 1
    shards: tuple[str, ...] = ("module_a", "module_b")

    @classmethod
    def of(cls, options: dict[str, Any]) -> "DemoOptions":
        shards = tuple(str(s) for s in options.get("shards") or cls.shards)
        if not all(s.isidentifier() for s in shards):
            raise ValueError("demo shards must be identifiers")
        return cls(
            slow_phase=options.get("slow_phase"),
            slow_seconds=min(float(options.get("slow_seconds", 0)), 600),
            fail_verification=options.get("fail_verification"),
            question_phase=options.get("question_phase"),
            fix_after=max(0, int(options.get("fix_after", 1))),
            shards=shards,
        )


def module_source(shard: str, buggy: bool) -> str:
    """The code the demo "generates": deterministic from the shard and whether this attempt is the buggy one."""
    offset = 1 if buggy else 0
    return f"def total(values):\n    return sum(values) + {offset}\n\nNAME = {shard!r}\n"


TEST_SOURCE = (
    "import sys\n"
    "sys.path.insert(0, '/input')\n"
    "from module import total\n"
    "assert total([20, 22]) == 42, f'expected 42, got {total([20, 22])}'\n"
    "print('1 passed')\n"
)


def _usage(text: str) -> Usage:
    return Usage(model=DEMO_MODEL, input_tokens=len(text) // 4, output_tokens=len(text) // 8)


class DemoPhase:
    def __init__(self, options: DemoOptions) -> None:
        self.options = options

    def agents(self, ctx: PhaseContext) -> list[str]:
        return [a.key for a in ctx.run.agents_of(ctx.phase.key)] or ["platform"]

    async def __call__(self, ctx: PhaseContext) -> PhaseResult:
        phase = ctx.phase.key
        if phase in GENERATION_PHASES:
            return await self.generation(ctx)
        agents = self.agents(ctx)
        checked = agents[0] if phase == self.options.fail_verification else None
        for agent in agents:
            if agent == checked:
                await ctx.do_verify_correct(
                    agent, partial(self.attempt, ctx, agent), self.never_passes, what=f"{phase} checks"
                )
            else:
                await ctx.invoke(agent, partial(self.work, ctx, agent), what=f"{agent} works on {phase}")
        if phase == self.options.question_phase:
            answer = ctx.ask(
                QuestionSpec(
                    key="demo-question",
                    agent=agents[0],
                    text="Which rounding applies to the monthly interest?",
                    context="The legacy program rounds half up; the business document says bankers' rounding.",
                    reason="contradiction",
                    impact="low",
                    recommended=Option("halfUp", "Round half up", "What the legacy code does today."),
                    confidence=0.8,
                    alternatives=(Option("bankers", "Bankers' rounding", "What the document says."),),
                    affects=(phase,),
                )
            )
            return PhaseResult(summary=f"{len(agents)} agent(s) done; rounding: {answer.option or answer.text}")
        return PhaseResult(summary=f"{len(agents)} agent(s) done")

    async def work(self, ctx: PhaseContext, agent: str) -> Attempt:
        if ctx.phase.key == self.options.slow_phase and self.options.slow_seconds:
            await asyncio.sleep(self.options.slow_seconds)
        note = f"{agent} on {ctx.phase.key}"
        return Attempt({"note": note}, f"{ctx.phase.key} output ready", _usage(note))

    async def attempt(self, ctx: PhaseContext, agent: str, iteration: int, feedback: str | None) -> Attempt:
        return await self.work(ctx, agent)

    async def never_passes(self, artifact: Any) -> Verification:
        return Verification(False, "AssertionError: expected 42, got 41 (demo: this verification never passes)")

    async def generation(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.sandbox is None:
            raise PhaseFailedError("The demo generation runs its tests in the sandbox, which is not available")
        agent = self.agents(ctx)[0]
        always_fail = ctx.phase.key == self.options.fail_verification

        async def one(shard_ctx: PhaseContext) -> dict[str, Any]:
            shard = shard_ctx.shard or ""

            async def work(iteration: int, feedback: str | None) -> Attempt:
                buggy = always_fail or iteration <= self.options.fix_after
                source = module_source(shard, buggy)
                digest = hashlib.sha256(source.encode()).hexdigest()
                # Only a reference goes into the state; the code is rebuilt from it to be verified.
                return Attempt({"shard": shard, "buggy": buggy, "sha256": digest}, f"{shard} written", _usage(source))

            async def verify(artifact: dict[str, Any]) -> Verification:
                if shard_ctx.sandbox is None:
                    raise PhaseFailedError("The sandbox is not available")
                files = {
                    "module.py": module_source(shard, artifact["buggy"]).encode(),
                    "test_module.py": TEST_SOURCE.encode(),
                }
                result = await shard_ctx.sandbox.run(["python", "/input/test_module.py"], files=files)
                if result.ok:
                    return Verification(True)
                tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
                return Verification(False, "\n".join(tail) or f"exit {result.exit_code}")

            attempt = await shard_ctx.do_verify_correct(agent, work, verify, what=f"{shard} generation")
            return dict(attempt.artifact)

        results = await ctx.fan_out(self.options.shards, one)
        return PhaseResult(summary=f"{len(results)} module(s) generated and tested in the sandbox")


def demo_executors(run: RunContext) -> dict[str, DemoPhase]:
    executor = DemoPhase(DemoOptions.of(run.options))
    return {phase.key: executor for phase in run.phases}
