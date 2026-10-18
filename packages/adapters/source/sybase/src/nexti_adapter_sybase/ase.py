"""Runs the legacy in a throw-away Sybase ASE (plan M4 step 10): one container per suite, without network, with
memory and process limits, removed at the end. The customer's code runs only there (CLAUDE.md: nothing supplied by
the customer runs outside an isolated container). The scripts come from `nexti_adapter_sybase.golden`.

`RecordedRunner` keeps what a live run observed, keyed by the code and the suite, so CI compares against the
recording without starting Sybase (plan M4, golden master decision)."""

import asyncio
import hashlib
import shlex
import subprocess
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from nexti_adapter_sybase import coverage, golden, quirks
from nexti_adapter_sybase.parser import Procedure
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.legacy_execution import Credentials, SybaseConfig
from nexti_core.spec.characterization import (
    Case,
    Coverage,
    CoveredBranch,
    EnvironmentItem,
    GoldenMaster,
    Observation,
    Recorded,
    Schema,
    Suite,
    Table,
    source_digest,
    suite_key,
)
from nexti_core.spec.equivalence import EngineTarget

IMAGE = "datagrip/sybase:16.0"
# The public default of the test image (not a secret): the engine has no network and lives for one suite.
_SA = ("sa", "myPassword", "MYSYBASE")
# stderr joins stdout in order: in a batch of cases, an engine message must stay inside the case that raised it.
_ISQL = ". /opt/sybase/SYBASE.sh && isql -U{0} -P{1} -S{2} -w 32000 -b 2>&1"
# The client of a customer's server (LiveAseRunner): the password is the first line of standard input, never an
# argument (it would show in the process list of the worker's host and in its logs).
_ISQL_CLIENT = '. /opt/sybase/SYBASE.sh && read -r NXPWD && isql -U{0} -P"$NXPWD" -S{1} -w 32000 -b 2>&1'
CASE_MARK = "NXCASE|"
CALL_DEPTH = 8  # levels of calls followed on the customer's server for the tables they touch


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
        # M28: what this engine answered to each quirk probe and the settings it runs under (measured once).
        self._probed: dict[str, str] = {}
        self._asked: set[str] = set()  # probes already run (an unanswered one is not asked again)
        self._environment: list[EnvironmentItem] | None = None

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

    async def _start(self, network: str = "none") -> str:
        name = f"nexti-ase-{uuid.uuid4().hex[:12]}"
        args = ["run", "-d", "--rm", "--name", name, "--network", network, "--memory", f"{self.memory_mb}m",
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
            await self._engine_facts(name, files, plan)
            for start in range(0, len(pending), self.batch_size):
                await self._run_batch(name, plan, pending[start : start + self.batch_size], keys)
            if uncovered:
                await self._cover(name, files, plan, uncovered, keys)
        finally:
            await self._stop(name)
        return self._master(files, suite, keys)

    async def _engine_facts(self, name: str, files: list[SourceFile], plan: golden.Plan) -> None:
        """The environment of the engine and its answer to the probes of the quirks the program relies on (M28):
        measured on the engine that records the golden master, each probe in its own batch."""
        if self._environment is None:
            self._environment = quirks.engine_environment(await self._isql(name, quirks.environment_script(), 120))
        source, procedure = _program_source(files, plan)
        unprobed = [q for q in quirks.detect(source, procedure) if q.probe and q.id not in self._asked]
        if unprobed:
            self._asked.update(q.id for q in unprobed)
            self._probed.update(quirks.probe_answers(await self._isql(name, quirks.probe_script(unprobed), 120)))

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
        self._branch_file = source.path
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
                                        measurable=b.measurable, file=getattr(self, "_branch_file", ""))
                          for b in self._branches],
                executed={c.name: self._covered[keys[c.name]][0] for c in suite.cases},
                unreliable=[c.name for c in suite.cases if not self._covered[keys[c.name]][1]],
            )  # fmt: skip
        source, procedure = _program_source(files, golden.plan(files, suite))
        register = [q.model_copy(update={"observed": self._probed.get(q.id)}) for q in quirks.detect(source, procedure)]
        environment = [*(self._environment or []), *quirks.program_environment(files, source, procedure)]
        return GoldenMaster(program=suite.program, source_sha256=source_digest(files), engine=self.engine,
                            schema_=suite.schema_, results=results, unassigned_outputs=unassigned,
                            coverage=measured, quirks=register, environment=environment,
                            unreachable=dict(suite.unreachable))  # fmt: skip


class SameEngine:
    """The engine a target runs its golden master against (ADR-0055, point 10): the platform's Sybase ASE with the
    suite's tables, the transactional substitutes of the called programs and the call log, on a private network of
    its own (`--internal`: no route out) that the sandbox of the target joins. The legacy program itself is not
    installed: the target is what runs. Used as `async with SameEngine(files, suite) as engine`."""

    PORT = 5000

    def __init__(self, files: list[SourceFile], suite: Suite, runner: AseRunner | None = None) -> None:
        self.files = files
        self.suite = suite
        self.runner = runner or AseRunner()
        self.network = f"nexti-eq-{uuid.uuid4().hex[:12]}"
        self.name: str | None = None

    async def __aenter__(self) -> EngineTarget:
        plan = golden.plan(self.files, self.suite)
        code, output = await asyncio.to_thread(self.runner._cli, ["network", "create", "--internal", self.network],
                                               None, 60)  # fmt: skip
        if code != 0:
            raise LegacyEngineError(f"the network of the engine could not be created: {output[:300]}")
        try:
            self.name = await self.runner._start(self.network)
            setup = await self.runner._isql(self.name, golden.setup_script(plan, with_sources=False), 600)
            failures = golden.engine_errors(setup)
            if failures:
                raise golden.GoldenError("the schema or the substitutes do not load in Sybase:" + chr(10)
                                         + chr(10).join(failures)[:3000])  # fmt: skip
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        programs = {program: [s.name for s in stub.parameters if not s.output] for program, stub in plan.stubs.items()}
        # The neutral type of each logged argument (phase F): the comparison canonicalises what the substitute
        # logged as the characterization did (`char(4)` without its trailing blanks).
        types = {program: [golden._neutral(s.type) for s in stub.parameters if not s.output]
                 for program, stub in plan.stubs.items()}  # fmt: skip
        return EngineTarget(
            name=self.name, network=self.network, jdbc_url=f"jdbc:jtds:sybase://{self.name}:{self.PORT}/{plan.work}",
            user=_SA[0], password=_SA[1], setup_for=lambda case: golden.case_setup_batches(plan, case),
            calls_query=golden.CALLS_QUERY, programs=programs, parse_args=golden.read_values, types=types,
        )  # fmt: skip

    async def __aexit__(self, *_: object) -> None:
        if self.name is not None:
            await self.runner._stop(self.name)
            self.name = None
        await asyncio.to_thread(self.runner._cli, ["network", "rm", self.network], None, 60)


class LiveAseRunner(AseRunner):
    """The legacy on a Sybase ASE test server of the customer (`kind = sybase` of ADR-0052, ADR-0055): the same
    scripts, sent by a throw-away client container (the isql of the platform's image, no engine) to the customer's
    server. Nothing of the platform is installed there but the call log in the program's database: the program,
    its tables and the programs it calls are the customer's and run for real, so no case may stub a call and no
    instrumented copy replaces the program (coverage is not measured). A test server, never production: the cases
    empty and reload the tables they set up."""

    engine = "sybase-ase-customer"

    def __init__(self, config: dict[str, Any] | SybaseConfig, credentials: Credentials, image: str = IMAGE,
                 docker: str = "docker", case_seconds: int = 120, batch_size: int = 25) -> None:  # fmt: skip
        super().__init__(image=image, docker=docker, case_seconds=case_seconds, batch_size=batch_size, coverage=False)
        self.config = config if isinstance(config, SybaseConfig) else SybaseConfig.model_validate(config)
        self.credentials = credentials

    async def _start(self, network: str = "none") -> str:
        name = f"nexti-ase-client-{uuid.uuid4().hex[:12]}"
        limits = ["--memory", "512m", "--memory-swap", "512m", "--pids-limit", "128", "--security-opt",
                  "no-new-privileges"]  # fmt: skip
        args = ["run", "-d", "--rm", "--name", name, *limits, "--entrypoint", "sleep", self.image, "infinity"]
        try:
            code, output = await asyncio.to_thread(self._cli, args, None, 120)
        except FileNotFoundError as exc:
            raise LegacyEngineError(f"{self.docker} is not installed") from exc
        if code != 0:
            raise LegacyEngineError(f"the Sybase client did not start: {output[:300]}")
        return name

    async def _isql(self, name: str, script: str, seconds: int) -> str:
        server = f"{self.config.host}:{self.config.port}"
        command = ["exec", "-i", name, "bash", "-c", _ISQL_CLIENT.format(shlex.quote(self.credentials.user), server)]
        try:
            _, output = await asyncio.to_thread(self._cli, command, self.credentials.password + "\n" + script, seconds)
        except subprocess.TimeoutExpired:
            return ""
        return output

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        stubbed = sorted({c.name for c in suite.cases if c.stubs})
        if stubbed:
            raise ValueError("on the customer's Sybase the programs it calls run for real: these cases cannot stub "
                             "calls: " + ", ".join(stubbed))  # fmt: skip
        full = replace(golden.plan(files, suite), work=self.config.database)
        plan = replace(full, stubs={})  # the called programs are the customer's: nothing to install or answer
        setup_script = golden.live_setup_script(full)
        name = await self._start()
        try:
            setup = await self._isql(name, setup_script, 300)
            if not setup.strip():
                raise LegacyEngineTimeoutError(f"{self.config.host}:{self.config.port} did not answer the setup")
            missing = golden.missing_objects(setup)
            if missing:
                raise golden.GoldenError("the customer's Sybase lacks what the program needs: " + ", ".join(missing))
            failures = golden.engine_errors(setup)
            if failures:
                raise golden.GoldenError("the customer's Sybase refused the setup:\n" + "\n".join(failures)[:3000])
            # ADR-0055 (point 8): the final state includes the tables the called programs touch, found on the
            # server itself; the cases dump them as they dump the program's own.
            called = await self._called_tables(name, full)
            plan = replace(plan, schema=Schema(tables=[*plan.schema.tables, *called]))
            keys = {case.name: _case_key(setup_script + "\0" + ",".join(t.name for t in called), case)
                    for case in suite.cases}  # fmt: skip
            pending = [case for case in suite.cases if keys[case.name] not in self._observed]
            if pending:
                await self._engine_facts(name, files, plan)
                for start in range(0, len(pending), self.batch_size):
                    await self._run_batch(name, plan, pending[start : start + self.batch_size], keys)
        finally:
            await self._stop(name)
        master = self._master(files, suite, keys)
        return master.model_copy(update={"schema_": plan.schema, "called_tables": [t.name for t in called]})

    async def _called_tables(self, name: str, plan: golden.Plan) -> list[Table]:
        """The tables the called programs touch, as the customer's server keeps them: the text of each program from
        syscomments, parsed as the inputs are, the calls followed level by level; their columns from the catalog.
        Tables the suite already names are not repeated."""
        known = {t.name.lower() for t in plan.schema.tables}
        pending = sorted(plan.stubs)
        seen: set[str] = set()
        tables: dict[str, None] = {}
        for _ in range(CALL_DEPTH):
            programs = [p for p in pending if p.lower() not in seen]
            if not programs:
                break
            seen.update(p.lower() for p in programs)
            texts = golden.read_sources(await self._isql(name, golden.source_script(programs, plan.work), 120))
            pending = []
            for program, text in texts.items():
                touched, calls = golden.dependencies(program, text, plan.work)
                tables.update({t: None for t in sorted(touched) if t.lower() not in known})
                pending += sorted(c for c in calls if c.lower() not in seen)
        if not tables:
            return []
        columns = golden.read_columns(await self._isql(name, golden.columns_script(list(tables), plan.work), 120))
        return [Table(name=table, columns=found) for table in tables if (found := columns.get(table))]

    async def check(self) -> tuple[bool, str]:
        """Signs on and uses the program's database without running anything (the project's connection test,
        ADR-0052): (ok, what happened)."""
        try:
            name = await self._start()
        except LegacyUnavailableError as exc:
            return False, str(exc)
        try:
            output = await self._isql(name, golden.live_check_script(self.config.database), 60)
        finally:
            await self._stop(name)
        version = next((x.strip()[len("NXREADY|") :] for x in output.splitlines() if x.strip().startswith("NXREADY|")),
                       None)  # fmt: skip
        where = f"{self.config.host}:{self.config.port}"
        if version is None:
            errors = golden.engine_errors(output)
            detail = "; ".join(errors) if errors else (output.strip()[-300:] or "no answer")
            return False, f"{where} did not sign on: {detail}"
        return True, f"signed on to {where}, database {self.config.database} usable ({version[:60]})"


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
