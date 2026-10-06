"""Runs the legacy in a throw-away Sybase ASE (plan M4 step 10): one container per suite, without network, with
memory and process limits, removed at the end. The customer's code runs only there (CLAUDE.md: nothing supplied by
the customer runs outside an isolated container). The scripts come from `nexti_adapter_sybase.golden`.

`RecordedRunner` keeps what a live run observed, keyed by the code and the suite, so CI compares against the
recording without starting Sybase (plan M4, golden master decision)."""

import asyncio
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from nexti_adapter_sybase import golden
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Recorded, Suite, source_digest, suite_key

IMAGE = "datagrip/sybase:16.0"
# The public default of the test image (not a secret): the engine has no network and lives for one suite.
_SA = ("sa", "myPassword", "MYSYBASE")
_ISQL = ". /opt/sybase/SYBASE.sh && isql -U{0} -P{1} -S{2} -w 32000 -b"


class LegacyEngineError(LegacyUnavailableError):
    """The engine could not be started or did not answer."""


class MissingGoldenMasterError(LegacyUnavailableError):
    """Replay mode found no recording for this code and suite."""


class AseRunner:
    engine = golden.ENGINE

    def __init__(self, image: str = IMAGE, docker: str = "docker", memory_mb: int = 3072, start_seconds: int = 300,
                 case_seconds: int = 120) -> None:  # fmt: skip
        self.image = image
        self.docker = docker
        self.memory_mb = memory_mb
        self.start_seconds = start_seconds
        self.case_seconds = case_seconds

    def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
        # Bytes, not text: on Windows text mode turns each newline into CRLF and isql ignores such a `go`.
        done = subprocess.run(  # noqa: S603 - fixed docker CLI arguments
            [self.docker, *args], input=stdin.encode("utf-8") if stdin is not None else None, capture_output=True,
            timeout=timeout, check=False,
        )  # fmt: skip
        return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")

    async def _isql(self, name: str, script: str, seconds: int) -> str:
        command = ["exec", "-i", name, "bash", "-c", _ISQL.format(*_SA)]
        _, output = await asyncio.to_thread(self._cli, command, script, seconds)
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
            raise LegacyEngineError(f"the Sybase engine did not start: {output[:300]}")
        deadline = time.monotonic() + self.start_seconds
        while time.monotonic() < deadline:
            # The image's entrypoint resizes master and creates its login before it prints this line.
            _, logs = await asyncio.to_thread(self._cli, ["logs", "--tail", "5", name], None, 30)
            if "SYBASE INITIALIZED" in logs and "NXREADY" in await self._isql(name, "select 'NXREADY'\ngo\n", 30):
                return name
            await asyncio.sleep(3)
        await self._stop(name)
        raise LegacyEngineError(f"the Sybase engine did not answer within {self.start_seconds} s")

    async def _stop(self, name: str) -> None:
        await asyncio.to_thread(self._cli, ["kill", name], None, 60)

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        plan = golden.plan(files, suite)
        name = await self._start()
        try:
            setup = await self._isql(name, golden.setup_script(plan), 600)
            failures = golden.engine_errors(setup)
            if failures:
                detail = "\n".join(failures)[:3000]
                raise golden.GoldenError(f"the code or the schema do not load in Sybase:\n{detail}")
            results = []
            for case in suite.cases:
                output = await self._isql(name, golden.case_script(plan, case), self.case_seconds)
                results.append(Recorded(case=case, observation=golden.observe(plan, output)))
        finally:
            await self._stop(name)
        return GoldenMaster(program=suite.program, source_sha256=source_digest(files), engine=self.engine,
                            schema_=suite.schema_, results=results,
                            unassigned_outputs=golden.unassigned_outputs(plan.program))  # fmt: skip


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
