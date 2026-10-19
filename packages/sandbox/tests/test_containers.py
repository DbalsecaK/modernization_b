"""Containers carry the process that owns them; the next start on the same host removes those of a dead process."""

import os
import socket

from nexti_sandbox.containers import orphans, owner, process_alive


def test_the_owner_is_this_process_on_this_host() -> None:
    assert owner() == f"{socket.gethostname()}:{os.getpid()}"
    assert process_alive(os.getpid())
    assert not process_alive(0)


def test_only_the_containers_of_a_dead_process_of_this_host_are_orphans() -> None:
    here = socket.gethostname()
    dead = 2**22 + 12345  # no process has this id
    listing = "\n".join([
        f"nexti-sb-alive {here}:{os.getpid()}",
        f"nexti-ase-dead {here}:{dead}",
        f"nexti-sb-elsewhere other-host:{dead}",
        "nexti-sb-unlabelled",
    ])  # fmt: skip
    assert orphans(listing) == ["nexti-ase-dead"]
