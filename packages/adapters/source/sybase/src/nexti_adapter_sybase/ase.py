"""Runs the legacy in a throw-away Sybase ASE (plan M4 step 10): one container per suite, without network, with
memory and process limits, removed at the end. The customer's code runs only there (CLAUDE.md: nothing supplied by
the customer runs outside an isolated container). The scripts come from `nexti_adapter_sybase.golden`.

`RecordedRunner` keeps what a live run observed, keyed by the code and the suite, so CI compares against the
recording without starting Sybase (plan M4, golden master decision)."""

import asyncio
import hashlib
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from nexti_adapter_sybase import coverage, golden
from nexti_adapter_sybase.parser import Procedure
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import (
    Case,
    Coverage,
    CoveredBranch,
    GoldenMaster,
    Observation,
    Recorded,
    Suite,
    source_digest,
    suite_key,
)

IMAGE = "datagrip/sybase:16.0"
# The public default of the test image (not a secret): the engine has no network and lives for one suite.
_SA = ("sa", "myPassword", "MYSYBASE")
# stderr joins stdout in order: in a batch of cases, an engine message must stay inside the case that raised it.
_ISQL = ". /opt/sybase/SYBASE.sh && isql -U{0} -P{1} -S{2} -w 32000 -b 2>&1"
CASE_MARK = "NXCASE|"


class LegacyEngineTimeoutError(LegacyUnavailableError):
    """The engine did not start or answer in time: a new try may work (a busy host, ADR-0046)."""

    transient = True


class LegacyEngineError(LegacyUnavailableError):
    """The engine could not be started or did not answer."""


class MissingGoldenMasterError(LegacyUnavailableError):
    """Replay mode found no recording for this code and suite."""


class AseRunner:
    engine = golden.ENGINE

    def __init__(self, image: str = IMAGE, docker: str = "docker", memory_mb: int = 3072, start_seconds: int = 300,
                 case_seconds: int = 120, batch_size: int = 25, coverage: bool = True) -> None:  # fmt: skip
        self.image = image
        self.docker = docker
        self.memory_mb = memory_mb
        self.start_seconds = start_seconds
        self.case_seconds = case_seconds
        self.batch_size = batch_size
        # What a case did with this exact code, schema and stubs (plan step 3b): a correction of the suite runs
        # only the cases that changed, and none at all needs no engine.
        self._observed: dict[str, Observation] = {}
        self.coverage = coverage
        # The branches each case exercised on the instrumented copy, and whether that run matched the original.
        self._covered: dict[str, tuple[list[str], bool]] = {}

    def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
        # Bytes, not text: on Windows text mode turns each newline into CRLF and isql ignores such a `go`.
        done = subprocess.run(  # noqa: S603 - fixed docker CLI arguments
            [self.docker, *args], input=stdin.encode("utf-8") if stdin is not None else None, capture_output=True,
            timeout=timeout, check=False,
        )  # fmt: skip
        return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")

    async def _isql(self, name: str, script: str, seconds: int) -> str:
        command = ["exec", "-i", name, "bash", "-c", _ISQL.format(*_SA)]
        try:
            _, output = await asyncio.to_thread(self._cli, command, script, seconds)
        except subprocess.TimeoutExpired:
            return ""  # no answer in time: the caller decides (a cut case, or an engine that stopped answering)
        return output

    async def _start(self) -> str:
        name = f"nexti-ase-{uuid.uuid4().hex[:12]}"
        args = ["run", "-d", "--rm", "--name", name, "--network", "none", "--memory", f"{self.memory_mb}m",
                "--memory-swap", f"{self.memory_mb}m", "--pids-limit", "512", "--security-opt", "no-new-privileges",
                self.image]  # fmt: skip
        try:
            code, output = await asyncio.to_thread(self._cli, args, None, 600)
        except FileNotFoundError as exc:
            raise LegacyEngineError(f"{self.docker} is not installed") from exc
        if code != 0:
            raise LegacyEngineTimeoutError(f"the Sybase engine did not start: {output[:300]}")
        deadline = time.monotonic() + self.start_seconds
        while time.monotonic() < deadline:
            # The image's entrypoint resizes master and creates its login before it prints this line.
            _, logs = await asyncio.to_thread(self._cli, ["logs", "--tail", "5", name], None, 30)
            if "SYBASE INITIALIZED" in logs and "NXREADY" in await self._isql(name, "select 'NXREADY'\ngo\n", 30):
                return name
            await asyncio.sleep(3)
        await self._stop(name)
        raise LegacyEngineTimeoutError(f"the Sybase engine did not answer within {self.start_seconds} s")

    async def _stop(self, name: str) -> None:
        await asyncio.to_thread(self._cli, ["kill", name], None, 60)

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        plan = golden.plan(files, suite)
        setup_script = golden.setup_script(plan)
        keys = {case.name: _case_key(setup_script, case) for case in suite.cases}
        pending = [case for case in suite.cases if keys[case.name] not in self._observed]
        uncovered = [case for case in suite.cases if self.coverage and keys[case.name] not in self._covered]
        if not pending and not uncovered:  # every case was observed with this code and schema: no engine needed
            return self._master(files, suite, keys)
        name = await self._start()
        try:
            setup = await self._isql(name, setup_script, 600)
            failures = golden.engine_errors(setup)
            if failures:
                detail = "\n".join(failures)[:3000]
                raise golden.GoldenError(f"the code or the schema do not load in Sybase:\n{detail}")
            for start in range(0, len(pending), self.batch_size):
                await self._run_batch(name, plan, pending[start : start + self.batch_size], keys)
            if uncovered:
                await self._cover(name, files, plan, uncovered, keys)
        finally:
            await self._stop(name)
        return self._master(files, suite, keys)

    async def _run_batch(self, name: str, plan: golden.Plan, cases: list[Case], keys: dict[str, str]) -> None:
        """One isql session for several cases (each starts by resetting the data, as alone): a marker before each
        case splits the output. A case cut by the timeout runs again alone."""
        script = "".join(
            f"select '{CASE_MARK}{i}'\ngo\n" + golden.case_script(plan, case) for i, case in enumerate(cases)
        )
        output = await self._isql(name, script, self.case_seconds * len(cases))
        parts = _split_cases(output, len(cases))
        if not parts:
            # Not one case answered: the engine stopped answering (a busy host). Waiting case by case would take
            # hours; the run is cut as transient and the phase tries again with a fresh engine (ADR-0046).
            raise LegacyEngineTimeoutError("the Sybase engine stopped answering during the cases")
        for index, case in enumerate(cases):
            part = parts.get(index)
            if part is None or (index == len(cases) - 1 and not part.strip()):
                part = await self._isql(name, golden.case_script(plan, case), self.case_seconds)
                if not part.strip():
                    raise LegacyEngineTimeoutError(f"the Sybase engine did not answer the case {case.name}")
            self._observed[keys[case.name]] = golden.observe(plan, part)

    async def _cover(
        self, name: str, files: list[SourceFile], plan: golden.Plan, cases: list[Case], keys: dict[str, str]
    ) -> None:
        """The same cases on an instrumented copy of the program (ADR-0047): the marks say which branches ran, and
        a case whose observation differs from the original's is unreliable. The golden master is never taken from
        this pass."""
        source, procedure = _program_source(files, plan)
        copy = coverage.instrument(source.text, procedure)
        install = golden.install_script(procedure.name, copy.text)
        loaded = await self._isql(name, install, 300)
        if golden.engine_errors(loaded):
            return  # the copy does not load: coverage is simply not measured
        self._branches = copy.branches
        for start in range(0, len(cases), self.batch_size):
            batch = cases[start : start + self.batch_size]
            script = "".join(
                f"select '{CASE_MARK}{i}'\ngo\n" + golden.case_script(plan, case) for i, case in enumerate(batch)
            )
            parts = _split_cases(await self._isql(name, script, self.case_seconds * len(batch)), len(batch))
            for index, case in enumerate(batch):
                hits, rest = coverage.executed(parts.get(index, ""))
                same = index in parts and golden.observe(plan, rest) == self._observed[keys[case.name]]
                self._covered[keys[case.name]] = (sorted(hits), same)

    def _master(self, files: list[SourceFile], suite: Suite, keys: dict[str, str]) -> GoldenMaster:
        results = [Recorded(case=case, observation=self._observed[keys[case.name]]) for case in suite.cases]
        unassigned = golden.unassigned_outputs(golden.plan(files, suite).program)
        measured = None
        if (
            self.coverage
            and getattr(self, "_branches", None)
            and all(keys[c.name] in self._covered for c in suite.cases)
        ):
            measured = Coverage(
                branches=[CoveredBranch(id=b.id, kind=b.kind, line_start=b.line_start, line_end=b.line_end,
                                        measurable=b.measurable) for b in self._branches],
                executed={c.name: self._covered[keys[c.name]][0] for c in suite.cases},
                unreliable=[c.name for c in suite.cases if not self._covered[keys[c.name]][1]],
            )  # fmt: skip
        return GoldenMaster(program=suite.program, source_sha256=source_digest(files), engine=self.engine,
                            schema_=suite.schema_, results=results, unassigned_outputs=unassigned,
                            coverage=measured)  # fmt: skip


def _program_source(files: list[SourceFile], plan: golden.Plan) -> tuple[SourceFile, Procedure]:
    for source, procedure in golden.procedures(files):
        if procedure is plan.program or procedure.name == plan.program.name:
            return source, procedure
    raise golden.GoldenError(f"the program {plan.program.name} is not in the source files")


def _case_key(setup_script: str, case: Case) -> str:
    return hashlib.sha256((setup_script + "\0" + case.model_dump_json()).encode("utf-8")).hexdigest()


def _split_cases(output: str, count: int) -> dict[int, str]:
    """The output of each case of a batch, by its index; a case whose marker never printed is absent."""
    parts: dict[int, list[str]] = {}
    current: int | None = None
    for line in output.splitlines():
        text = line.strip()
        if text.startswith(CASE_MARK) and text[len(CASE_MARK) :].isdigit():
            current = int(text[len(CASE_MARK) :])
            parts[current] = []
        elif current is not None and current < count:
            parts[current].append(line)
    return {index: "\n".join(lines) for index, lines in parts.items()}


class RecordedRunner:
    """Replay: the recording or MissingGoldenMasterError. Record: run live and keep what it observed."""

    engine = golden.ENGINE

    def __init__(self, directory: Path, mode: Literal["replay", "record"], live: AseRunner | None = None) -> None:
        if mode == "record" and live is None:
            raise ValueError("record mode needs a live runner")
        self.directory = directory
        self.mode = mode
        self.live = live

    def _path(self, files: list[SourceFile], suite: Suite) -> Path:
        source = "\0".join(f"{f.path}\0{f.text}" for f in sorted(files, key=lambda f: f.path))
        return self.directory / f"{suite_key(source, suite)[:32]}.json"

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        path = self._path(files, suite)
        if path.exists():
            return GoldenMaster.model_validate_json(path.read_text(encoding="utf-8"))
        if self.mode == "replay" or self.live is None:
            raise MissingGoldenMasterError(f"no golden master recorded for this code and suite ({path.name})")
        master = await self.live.run(files, suite)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(master.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8")
        return master
