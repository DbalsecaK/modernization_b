"""The execution sandbox (spec 15.5, rule 4 of CLAUDE.md): nothing produced by a model and no customer code runs outside
it. Each job gets an ephemeral container without network, with a read-only root filesystem, no capabilities, an
unprivileged user and limits of CPU, memory, processes, time and output. Inputs are mounted read-only at /input; the
only writable place is a small tmpfs at /work.

Development and CI use the local Docker. Production runs this contract on a separate service with gVisor or
Firecracker (M9); callers only see `Sandbox.run`.
"""

import asyncio
import shutil
import subprocess
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
    # More writable tmpfs mounts, (path, size in MB): for an engine that must write where it was installed (SQL
    # Server in /var/opt/mssql). The root filesystem stays read-only.
    scratch: tuple[tuple[str, int], ...] = ()
    # Whether native executables may run from /work (tmpfs mounts are noexec by default). Only for a toolchain that
    # must launch the programs it builds (xUnit v3 test hosts); the container stays without network or privileges.
    work_exec: bool = False
    # Exceptions for database engines that need them (ADR-0021), off by default:
    # - a Docker network of its own for the run, `--internal` (no route out, no other container), for an engine that
    #   will not start with loopback only (Oracle);
    # - the container's writable layer instead of a read-only root, for an engine that writes its data files in place;
    # - the engine's own unprivileged user instead of nobody. Capabilities stay dropped and privileges cannot grow.
    internal_network: bool = False
    writable_root: bool = False
    user: str | None = None


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


def _write_inputs(input_dir: Path, files: Mapping[str, bytes]) -> None:
    """The container runs as nobody: the inputs must be world-readable (mkdtemp creates the folder 0700). They are
    mounted read-only, so readable is all they need to be."""
    input_dir.chmod(0o755)
    for relative, content in files.items():
        target = input_dir.joinpath(*_safe_relative(relative).parts)
        for parent in reversed(target.relative_to(input_dir).parents[:-1]):
            (input_dir / parent).mkdir(mode=0o755, exist_ok=True)
            (input_dir / parent).chmod(0o755)
        target.write_bytes(content)
        target.chmod(0o644)


class DockerSandbox:
    def __init__(self, image: str = DEFAULT_IMAGE, docker: str = "docker", limits: Limits | None = None) -> None:
        self.image = image
        self.docker = docker
        self.limits = limits or Limits()

    def _args(self, name: str, input_dir: Path, limits: Limits, network: str = "none") -> list[str]:
        return [
            self.docker, "run", "--rm", "--name", name,
            "--network", network,
            *([] if limits.writable_root else ["--read-only"]),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", limits.user or NOBODY,
            "--pids-limit", str(limits.pids),
            "--memory", f"{limits.memory_mb}m",
            "--memory-swap", f"{limits.memory_mb}m",
            "--cpus", str(limits.cpus),
            "--tmpfs", f"/work:rw,{'exec,' if limits.work_exec else ''}size={limits.work_mb}m,mode=1777",
            "--tmpfs", "/tmp:rw,size=16m,mode=1777",  # noqa: S108 - a path inside the container
            *[arg for path, size in limits.scratch for arg in ("--tmpfs", f"{path}:rw,size={size}m,mode=1777")],
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
        network = f"{name}-net" if limits.internal_network else "none"
        try:
            if limits.internal_network:
                await self._network("create", "--internal", network)
            await asyncio.to_thread(_write_inputs, input_dir, files or {})
            timed_out = False
            try:
                # The docker CLI runs in a thread: this works on any event loop (psycopg needs the selector loop on
                # Windows, where asyncio subprocesses need the proactor loop).
                process = await asyncio.to_thread(
                    subprocess.run, [*self._args(name, input_dir, limits, network), *command], capture_output=True,
                    timeout=limits.timeout_seconds, check=False,
                )  # fmt: skip
                returncode, stdout, stderr = process.returncode, process.stdout, process.stderr
            except FileNotFoundError as exc:
                raise SandboxUnavailableError(f"{self.docker} is not installed") from exc
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                await self._kill(name)
                returncode, stdout, stderr = -1, exc.stdout or b"", exc.stderr or b""
            if returncode == 125 and not timed_out and b"Cannot connect" in stderr:
                raise SandboxUnavailableError(stderr.decode("utf-8", "replace")[:300])
            cap = limits.max_output_bytes
            truncated = len(stdout) > cap or len(stderr) > cap
            return SandboxResult(
                exit_code=returncode,
                stdout=stdout[:cap].decode("utf-8", "replace"),
                stderr=stderr[:cap].decode("utf-8", "replace"),
                timed_out=timed_out,
                duration_ms=int((time.monotonic() - started) * 1000),
                truncated=truncated,
            )
        finally:
            shutil.rmtree(input_dir, ignore_errors=True)
            if limits.internal_network:
                await self._network("rm", network)

    async def _network(self, action: str, *args: str) -> None:
        """Create or remove the run's own internal network (ADR-0021)."""
        await asyncio.to_thread(
            subprocess.run, [self.docker, "network", action, *args], capture_output=True, timeout=60, check=False
        )

    async def _kill(self, name: str) -> None:
        await asyncio.to_thread(
            subprocess.run, [self.docker, "kill", name], capture_output=True, timeout=30, check=False
        )

    async def available(self) -> bool:
        try:
            probe = await asyncio.to_thread(
                subprocess.run, [self.docker, "version", "--format", "{{.Server.Version}}"], capture_output=True,
                timeout=30, check=False,
            )  # fmt: skip
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return probe.returncode == 0


__all__ = ["DEFAULT_IMAGE", "DockerSandbox", "Limits", "Sandbox", "SandboxResult", "SandboxUnavailableError"]
