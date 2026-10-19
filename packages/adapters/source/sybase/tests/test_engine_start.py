"""The engine's start and stop on a loaded host (2026-10-19): a boot that crashed is started again, a stop that times
out never escapes, and an engine a dead process left behind is removed by the next start once its expiry passed."""

import asyncio
import subprocess
import time

import pytest

from nexti_adapter_sybase import ase
from nexti_adapter_sybase.ase import AseRunner, LegacyEngineTimeoutError


class FakeDocker(AseRunner):
    """The docker CLI as a script: each boot either crashes (initialized, never answers) or answers."""

    def __init__(self, boots: list[str], listed: str = "", stop_times_out: bool = False) -> None:
        super().__init__(start_seconds=60)
        self.boots = boots
        self.listed = listed
        self.stop_times_out = stop_times_out
        self.started: list[str] = []
        self.removed: list[str] = []

    def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
        if args[0] == "run":
            self.started.append(args[args.index("--name") + 1])
            return 0, "id"
        if args[0] == "logs":
            return 0, "SYBASE INITIALIZED"
        if args[0] == "exec":
            return 0, "NXREADY" if self.boots[len(self.started) - 1] == "ok" else "ct_connect(): failed"
        if args[0] == "rm":
            if self.stop_times_out:
                raise subprocess.TimeoutExpired(args, timeout)
            self.removed.append(args[-1])
            return 0, ""
        if args[0] == "ps":
            return 0, self.listed
        raise AssertionError(args)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ase, "CRASHED_BOOT_SECONDS", 0)
    monkeypatch.setattr(ase, "reap_orphans", lambda docker: [])  # no real docker here

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(ase.asyncio, "sleep", no_wait)


def test_a_crashed_boot_is_stopped_and_started_again() -> None:
    docker = FakeDocker(["crash", "ok"])
    name = asyncio.run(docker._start())
    assert docker.started == [docker.started[0], name]
    assert docker.removed == [docker.started[0]]  # the crashed engine does not stay behind


def test_after_every_attempt_crashed_the_start_fails_and_leaves_nothing_running() -> None:
    docker = FakeDocker(["crash"] * ase.START_ATTEMPTS)
    with pytest.raises(LegacyEngineTimeoutError, match="a crashed boot"):
        asyncio.run(docker._start())
    assert docker.removed == docker.started


def test_a_stop_that_times_out_never_escapes() -> None:
    asyncio.run(FakeDocker([], stop_times_out=True)._stop("nexti-ase-x"))


def test_every_engine_carries_an_expiry_and_the_next_start_removes_the_expired_ones() -> None:
    past, future = int(time.time()) - 10, int(time.time()) + 3600
    docker = FakeDocker(["ok"], listed=f"nexti-ase-old {past}\nnexti-ase-busy {future}\n")
    asyncio.run(docker._start())
    assert docker.removed == ["nexti-ase-old"]  # an engine still in its lifetime belongs to a running case
