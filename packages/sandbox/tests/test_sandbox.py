"""The sandbox against the real local Docker (spec 15.5): no network, read-only root, unprivileged user, limits of
memory, processes and time, inputs read-only. Skipped when Docker is not available."""

import pytest

from nexti_sandbox import DockerSandbox, Limits, SandboxUnavailableError


@pytest.fixture(scope="module")
async def sandbox() -> DockerSandbox:
    box = DockerSandbox(limits=Limits(timeout_seconds=60, memory_mb=128))
    if not await box.available():
        pytest.skip("Docker is not available")
    return box


def python(code: str) -> list[str]:
    return ["python", "-c", code]


async def test_a_command_runs_and_its_output_comes_back(sandbox: DockerSandbox) -> None:
    result = await sandbox.run(python("print('hello from the sandbox')"))
    assert result.ok
    assert result.stdout.strip() == "hello from the sandbox"


async def test_there_is_no_network(sandbox: DockerSandbox) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\n"
        "except OSError as exc:\n"
        "    print('no network:', type(exc).__name__)\n"
    )
    result = await sandbox.run(python(code))
    assert "no network" in result.stdout
    assert "connected" not in result.stdout


async def test_it_runs_as_nobody_on_a_read_only_root(sandbox: DockerSandbox) -> None:
    code = (
        "import os\n"
        "print(os.getuid())\n"
        "open('/work/ok.txt', 'w').write('x')\n"
        "try:\n"
        "    open('/etc/evil', 'w')\n"
        "    print('root writable')\n"
        "except OSError:\n"
        "    print('root read-only')\n"
    )
    result = await sandbox.run(python(code))
    assert result.ok, result.stderr
    assert result.stdout.split() == ["65534", "root", "read-only"]


async def test_inputs_are_mounted_read_only(sandbox: DockerSandbox) -> None:
    code = (
        "print(open('/input/src/CARD01.cbl').read())\n"
        "try:\n"
        "    open('/input/src/CARD01.cbl', 'a').write('tampered')\n"
        "    print('input writable')\n"
        "except OSError:\n"
        "    print('input read-only')\n"
    )
    result = await sandbox.run(python(code), files={"src/CARD01.cbl": b"MOVE 1 TO WS-X."})
    assert result.stdout.split("\n")[0] == "MOVE 1 TO WS-X."
    assert "input read-only" in result.stdout


async def test_a_job_past_its_time_is_killed(sandbox: DockerSandbox) -> None:
    result = await sandbox.run(python("import time; time.sleep(60)"), limits=Limits(timeout_seconds=3))
    assert result.timed_out
    assert not result.ok
    assert result.duration_ms < 30_000


async def test_memory_is_limited(sandbox: DockerSandbox) -> None:
    result = await sandbox.run(
        python("x = bytearray(400 * 1024 * 1024); print('allocated')"), limits=Limits(memory_mb=64)
    )
    assert not result.ok
    assert "allocated" not in result.stdout


async def test_unsafe_input_names_are_refused(sandbox: DockerSandbox) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        await sandbox.run(python("print(1)"), files={"../escape.txt": b"x"})


async def test_without_a_runtime_the_job_does_not_run() -> None:
    with pytest.raises(SandboxUnavailableError):
        await DockerSandbox(docker="docker-that-does-not-exist").run(python("print(1)"))
