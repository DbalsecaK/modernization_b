"""The execution sandbox (spec 15.5, rule 4 of CLAUDE.md): nothing produced by a model and no customer code runs outside
it. Each job gets an ephemeral container without network, with a read-only root filesystem, no capabilities, an
unprivileged user and limits of CPU, memory, processes, time and output. Inputs are mounted read-only at /input; the
only writable place is a small tmpfs at /work.

Development and CI use the local Docker. Production runs this contract on a separate service with gVisor or
Firecracker (M9); callers only see `Sandbox.run`.
"""

import asyncio
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

# python:3.12-slim, pinned by digest: the image never changes under a running pipeline.
DEFAULT_IMAGE = "python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
NOBODY = "65534:65534"


class SandboxUnavailableError(RuntimeError):
    """The container runtime cannot be reached: the job cannot run (never falls back to running on the host)."""


@dataclass(frozen=True)
class Limits:
    cpus: float = 1.0
    memory_mb: int = 512
    pids: int = 128
    timeout_seconds: float = 120
    work_mb: int = 64
    max_output_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(Protocol):
    async def run(
        self, command: list[str], files: Mapping[str, bytes] | None = None, limits: Limits | None = None
    ) -> SandboxResult: ...


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise ValueError(f"unsafe input file name: {name!r}")
    return path


class DockerSandbox:
    def __init__(self, image: str = DEFAULT_IMAGE, docker: str = "docker", limits: Limits | None = None) -> None:
        self.image = image
        self.docker = docker
        self.limits = limits or Limits()

    def _args(self, name: str, input_dir: Path, limits: Limits) -> list[str]:
        return [
            self.docker, "run", "--rm", "--name", name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", NOBODY,
            "--pids-limit", str(limits.pids),
            "--memory", f"{limits.memory_mb}m",
            "--memory-swap", f"{limits.memory_mb}m",
            "--cpus", str(limits.cpus),
            "--tmpfs", f"/work:rw,size={limits.work_mb}m,mode=1777",
            "--tmpfs", "/tmp:rw,size=16m,mode=1777",  # noqa: S108 - a path inside the container
            "--env", "HOME=/work",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--volume", f"{input_dir}:/input:ro",
            "--workdir", "/work",
            self.image,
        ]  # fmt: skip

    async def run(
        self, command: list[str], files: Mapping[str, bytes] | None = None, limits: Limits | None = None
    ) -> SandboxResult:
        limits = limits or self.limits
        name = f"nexti-sb-{uuid.uuid4().hex[:12]}"
        input_dir = Path(tempfile.mkdtemp(prefix="nexti-sandbox-"))
        started = time.monotonic()
        try:
            for relative, content in (files or {}).items():
                target = input_dir.joinpath(*_safe_relative(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            try:
                process = await asyncio.create_subprocess_exec(
                    *self._args(name, input_dir, limits), *command,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )  # fmt: skip
            except FileNotFoundError as exc:
                raise SandboxUnavailableError(f"{self.docker} is not installed") from exc
            timed_out = False
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=limits.timeout_seconds)
            except TimeoutError:
                timed_out = True
                await self._kill(name)
                stdout, stderr = await process.communicate()
            if process.returncode == 125 and not timed_out and b"Cannot connect" in stderr:
                raise SandboxUnavailableError(stderr.decode("utf-8", "replace")[:300])
            cap = limits.max_output_bytes
            truncated = len(stdout) > cap or len(stderr) > cap
            return SandboxResult(
                exit_code=process.returncode if process.returncode is not None else -1,
                stdout=stdout[:cap].decode("utf-8", "replace"),
                stderr=stderr[:cap].decode("utf-8", "replace"),
                timed_out=timed_out,
                duration_ms=int((time.monotonic() - started) * 1000),
                truncated=truncated,
            )
        finally:
            shutil.rmtree(input_dir, ignore_errors=True)

    async def _kill(self, name: str) -> None:
        killer = await asyncio.create_subprocess_exec(
            self.docker, "kill", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await killer.wait()

    async def available(self) -> bool:
        try:
            probe = await asyncio.create_subprocess_exec(
                self.docker, "version", "--format", "{{.Server.Version}}",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
        except FileNotFoundError:
            return False
        return await probe.wait() == 0


__all__ = ["DEFAULT_IMAGE", "DockerSandbox", "Limits", "Sandbox", "SandboxResult", "SandboxUnavailableError"]
