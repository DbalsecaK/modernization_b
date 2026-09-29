"""Preflight (spec 11.1, phase 0): before any agent spends money, check that the run can finish. Inputs present and
clean, credentials resolvable, repository reachable, a model for every agent, budget enough for the estimate, and the
code archives listed inside the sandbox (never opened on the worker's host: a zip is customer content).

When a check fails a person decides: fix and check again, or stop the run.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol

from nexti_orchestration.context import Memo, PhaseContext
from nexti_orchestration.model import Option, PhaseFailedError, PhaseResult, QuestionSpec
from nexti_sandbox import Limits

PLATFORM_AGENT = "platform"
MAX_ENTRIES = 200_000
MAX_UNCOMPRESSED = 4 * 1024**3
MAX_RATIO = 200  # uncompressed / compressed: past this it looks like a zip bomb

# Runs inside the sandbox: reads each /input/archives/<n>.zip and reports what it holds, without extracting.
LISTER = r"""
import json, os, zipfile
report = {}
for name in sorted(os.listdir('/input/archives')):
    path = os.path.join('/input/archives', name)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            unsafe = sum(1 for i in infos
                         if i.filename.startswith('/')
                         or '..' in i.filename.replace('\\', '/').split('/')
                         or (i.external_attr >> 16) & 0o170000 == 0o120000)
            report[name] = {
                'entries': len(infos),
                'uncompressed': sum(i.file_size for i in infos),
                'compressed': sum(i.compress_size for i in infos),
                'encrypted': sum(1 for i in infos if i.flag_bits & 0x1),
                'unsafe': unsafe,
            }
    except (zipfile.BadZipFile, OSError) as exc:
        report[name] = {'error': type(exc).__name__}
print(json.dumps(report))
"""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


class PreflightProbe(Protocol):
    """What the worker can see of the project: implemented on the database, the object store and the vault."""

    async def inputs(self) -> Check: ...

    async def secrets(self) -> Check: ...

    async def repository(self) -> Check: ...

    async def models(self) -> Check: ...

    async def budget(self) -> Check: ...

    async def archives(self) -> Mapping[str, bytes]:
        """The project's code archives by display name (their contents only go into the sandbox)."""
        ...


def _archive_problems(name: str, info: Mapping[str, int | str]) -> list[str]:
    if "error" in info:
        return [f"{name}: not a readable zip ({info['error']})"]
    problems = []
    entries, uncompressed, compressed = int(info["entries"]), int(info["uncompressed"]), int(info["compressed"])
    if entries > MAX_ENTRIES:
        problems.append(f"{name}: {entries} entries (limit {MAX_ENTRIES})")
    if uncompressed > MAX_UNCOMPRESSED:
        problems.append(f"{name}: {uncompressed} bytes uncompressed (limit {MAX_UNCOMPRESSED})")
    if compressed and uncompressed / compressed > MAX_RATIO:
        problems.append(f"{name}: compression ratio {uncompressed // compressed}:1 looks like a zip bomb")
    if int(info["encrypted"]):
        problems.append(f"{name}: {info['encrypted']} encrypted entries cannot be analysed")
    if int(info["unsafe"]):
        problems.append(f"{name}: {info['unsafe']} entries with unsafe paths or links")
    return problems


class Preflight:
    def __init__(self, probe: PreflightProbe) -> None:
        self.probe = probe

    async def __call__(self, ctx: PhaseContext) -> PhaseResult:
        round_number = 0
        while True:
            memo = await ctx.step(f"checks/{round_number}", lambda: self._run(ctx))
            checks = [Check(**c) for c in memo["checks"]]
            failed = [c for c in checks if not c.ok]
            if not failed:
                return PhaseResult(summary=f"{len(checks)} checks passed")
            answer = ctx.ask(
                QuestionSpec(
                    key=f"preflight-{round_number}",
                    agent=PLATFORM_AGENT,
                    text=f"Preflight found {len(failed)} problem(s). Fix them and check again, or stop the run?",
                    context="\n".join(f"{c.name}: {c.detail}" for c in failed)[:2000],
                    reason="missingInformation",
                    impact="high",
                    recommended=Option("retry", "Check again", "After fixing the problems listed."),
                    confidence=0.9,
                    alternatives=(Option("stop", "Stop the run", "Nothing was spent yet."),),
                    affects=("preflight",),
                )
            )
            if answer.option != "retry":
                raise PhaseFailedError("Preflight failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failed))
            round_number += 1

    async def _run(self, ctx: PhaseContext) -> Memo:
        checks = [
            await self.probe.inputs(),
            await self.probe.secrets(),
            await self.probe.repository(),
            await self.probe.models(),
            await self.probe.budget(),
            await self._archives(ctx),
        ]
        for check in checks:
            await ctx.store.event(
                "info", "succeeded" if check.ok else "failed", f"Preflight {check.name}: {check.detail}"[:2000],
                phase=ctx.phase.key, agent=PLATFORM_AGENT, payload={"check": check.name, "ok": check.ok},
            )  # fmt: skip
        return {"checks": [asdict(c) for c in checks]}

    async def _archives(self, ctx: PhaseContext) -> Check:
        archives = await self.probe.archives()
        if not archives:
            return Check("archives", True, "no code archive to list")
        if ctx.sandbox is None:
            return Check("archives", False, "the sandbox is not available to list the archives")
        names = {f"{index}.zip": name for index, name in enumerate(sorted(archives))}
        files = {f"archives/{index}": archives[name] for index, name in names.items()}
        result = await ctx.sandbox.run(["python", "-c", LISTER], files=files, limits=Limits(timeout_seconds=300))
        if not result.ok:
            return Check("archives", False, f"listing failed in the sandbox (exit {result.exit_code})")
        try:
            report: dict[str, dict[str, int | str]] = json.loads(result.stdout)
        except json.JSONDecodeError:
            return Check("archives", False, "the sandbox listing was not readable")
        problems = [p for index, info in report.items() for p in _archive_problems(names.get(index, index), info)]
        if problems:
            return Check("archives", False, "; ".join(problems)[:2000])
        entries = sum(int(info["entries"]) for info in report.values())
        return Check("archives", True, f"{len(report)} archive(s), {entries} entries listed in the sandbox")
