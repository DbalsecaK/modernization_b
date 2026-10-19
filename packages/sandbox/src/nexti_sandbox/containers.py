"""Containers the platform starts carry the process that owns them, so a container a dead process left behind is
removed by the next start on the same host (2026-10-19: every restart of the worker left its sandboxes and its 3 GB
Sybase engines running, because docker does not stop a container when its client dies; four engines and three
sandboxes of one run were running at once and the host crawled)."""

import os
import socket
import subprocess
import sys
import time

OWNER_LABEL = "nexti.owner"
_REAP_EVERY_SECONDS = 60.0
_last_reap: dict[str, float] = {}


def owner() -> str:
    """This process, as the owner label of the containers it starts: `host:pid`."""
    return f"{socket.gethostname()}:{os.getpid()}"


def process_alive(pid: int) -> bool:
    """Whether a process of this host is still running. On Windows `os.kill(pid, 0)` would terminate it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return bool(kernel32.GetLastError() == 5)  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def orphans(listing: str, host: str | None = None) -> list[str]:
    """The containers of `docker ps` lines `<name> <host:pid>` whose owner ran on this host and is gone."""
    here = host or socket.gethostname()
    found = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2 or ":" not in parts[1]:
            continue
        where, _, pid = parts[1].rpartition(":")
        if where == here and pid.isdigit() and not process_alive(int(pid)):
            found.append(parts[0])
    return found


def reap_orphans(docker: str = "docker") -> list[str]:
    """Removes the containers a dead process of this host left behind; at most once a minute per docker CLI, and
    never failing (docker may be slow or absent)."""
    now = time.monotonic()
    if now - _last_reap.get(docker, -_REAP_EVERY_SECONDS) < _REAP_EVERY_SECONDS:
        return []
    _last_reap[docker] = now
    try:
        listed = subprocess.run(  # noqa: S603 - fixed docker CLI arguments
            [docker, "ps", "-a", "--filter", f"label={OWNER_LABEL}", "--format",
             f'{{{{.Names}}}} {{{{.Label "{OWNER_LABEL}"}}}}'],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout  # fmt: skip
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    removed = []
    for name in orphans(listed):
        try:
            subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=120, check=False)  # noqa: S603
            removed.append(name)
        except subprocess.TimeoutExpired:
            continue
    return removed
