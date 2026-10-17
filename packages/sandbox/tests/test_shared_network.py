"""A run may join a network the caller made (ADR-0055): the engine the target talks to is already on it, and the
sandbox neither creates nor removes that network."""

from dataclasses import replace
from pathlib import Path

from nexti_sandbox import DockerSandbox, Limits


def test_the_run_joins_the_callers_network_instead_of_none() -> None:
    box = DockerSandbox(image="img")
    plain = box._args("nexti-sb-1", Path("in"), Limits())
    assert plain[plain.index("--network") + 1] == "none"
    shared = box._args("nexti-sb-1", Path("in"), replace(Limits(), network="nexti-eq-abc"), network="nexti-eq-abc")
    assert shared[shared.index("--network") + 1] == "nexti-eq-abc"
    assert "--read-only" in shared  # nothing else changes: still read-only, no capabilities, nobody
