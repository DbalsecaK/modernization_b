"""Acceptance of M3 (plan section 5) with real processes: the API launches a run, worker processes execute it from
the queue with the Docker sandbox, a worker killed in the middle of a phase is replaced by another that resumes from
the checkpoint without repeating finished phases, gates stop the run until someone with the permission approves, and
a verification that never passes escalates after exactly max_iterations attempts."""

import asyncio
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_sandbox import DockerSandbox
from nexti_worker.runner import execute_run

from .conftest import Databases, World
from .run_support import fetch, make_config, make_project, make_run, runtime
from .test_runs_api import grant, sign_in

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def docker() -> None:
    if not asyncio.run(DockerSandbox().available()):
        pytest.skip("Docker is not available")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


class Workers:
    """Worker processes on the throwaway database (python -m nexti_worker), killed at the end of the test."""

    def __init__(self, databases: Databases, logs: Path) -> None:
        self.databases = databases
        self.logs = logs
        self.processes: list[subprocess.Popen[bytes]] = []

    def start(self, name: str) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "APP_ENV": "test",
            "DATABASE_URL": self.databases.app_url.render_as_string(hide_password=False),
            "HEARTBEAT_SECONDS": "1",
            "STALLED_AFTER_SECONDS": "4",
            "CONCURRENCY": "2",
            "OBJECT_STORE_URL": "",
            "SECRETS_URL": "",
        }
        log = (self.logs / f"{name}.log").open("wb")
        process = subprocess.Popen(  # noqa: S603 - the worker module of this repository
            [sys.executable, "-m", "nexti_worker", name], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        self.processes.append(process)
        return process

    def stop(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)


@pytest.fixture
def workers(databases: Databases, tmp_path: Path) -> Iterator[Workers]:
    pool = Workers(databases, tmp_path)
    yield pool
    pool.stop()


async def until(check: Callable[[], Awaitable[bool]], seconds: float = 180, what: str = "condition") -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}")


async def run_state(owner: AsyncEngine, run_id: uuid.UUID) -> dict[str, Any]:
    (row,) = await fetch(owner, "SELECT status, waiting_reason, current_phase, error FROM run WHERE id = :r", r=run_id)
    return row


async def test_a_killed_worker_is_replaced_and_the_run_finishes_through_its_gates(
    docker: None,
    api: TestClient,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    fga: OpenFga,
    world: World,
    workers: Workers,
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await make_config(owner_engine, world.tenant_a, project_id)
    await grant(owner_engine, world, world.shared, "projectOwner", project_id)
    await reconcile(app_engine, fga)

    # The tenant admin launches a demo run whose inventory phase takes a while.
    admin = sign_in(api, world.a_user)
    launched = api.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"kind": "demo", "options": {"slowPhase": "inventory", "slowSeconds": 30}},
        headers=admin,
    )
    assert launched.status_code == 201, launched.text
    run_id = uuid.UUID(launched.json()["id"])

    first = workers.start("worker-1")

    async def in_inventory() -> bool:
        rows = await fetch(
            owner_engine, "SELECT status FROM phase_run WHERE run_id = :r AND phase = 'inventory'", r=run_id
        )
        return bool(rows) and rows[0]["status"] == "running"

    await until(in_inventory, what="the inventory phase to start")
    first.kill()  # SIGKILL on POSIX, TerminateProcess on Windows: no chance to clean up
    first.wait(timeout=30)
    workers.start("worker-2")

    def at_gate(gate: str) -> Callable[[], Awaitable[bool]]:
        async def check() -> bool:
            state = await run_state(owner_engine, run_id)
            assert state["status"] != "failed", state
            gates = await fetch(
                owner_engine, "SELECT 1 FROM gate WHERE run_id = :r AND gate = :g AND status = 'pending'",
                r=run_id, g=gate,
            )  # fmt: skip
            return state["status"] == "waiting" and state["waiting_reason"] == "gate" and bool(gates)

        return check

    await until(at_gate("C1"), what="the run to wait at C1")
    # Finished phases were not repeated: preflight started once; the killed phase was redone on the same rows.
    started = await fetch(
        owner_engine,
        "SELECT phase, count(*) AS n FROM activity_event WHERE run_id = :r AND kind = 'phaseStarted' GROUP BY phase",
        r=run_id,
    )
    assert {r["phase"]: r["n"] for r in started}["preflight"] == 1
    inventory = await fetch(
        owner_engine,
        "SELECT agent_key, status FROM agent_invocation WHERE run_id = :r AND phase = 'inventory'",
        r=run_id,
    )
    assert inventory == [{"agent_key": "legacy-analyst", "status": "succeeded"}]
    resumed = await fetch(
        owner_engine, "SELECT message FROM activity_event WHERE run_id = :r AND message LIKE 'Resumed after%'", r=run_id
    )
    assert len(resumed) == 1

    # The launcher cannot approve; the project owner can, and the run goes on to C4.
    base = f"/api/v1/projects/{project_id}/runs/{run_id}/gates"
    assert api.post(f"{base}/C1:approve", json={}, headers=admin).json()["code"] == "segregation_of_duties"
    owner = sign_in(api, world.shared)
    assert api.post(f"{base}/C1:approve", json={"comment": "Rules reviewed"}, headers=owner).status_code == 200
    await until(at_gate("C4"), what="the run to wait at C4")
    assert api.post(f"{base}/C4:approve", json={"comment": "Signed off"}, headers=owner).status_code == 200

    async def finished() -> bool:
        return bool((await run_state(owner_engine, run_id))["status"] == "succeeded")

    await until(finished, what="the run to finish")
    detail = api.get(f"/api/v1/projects/{project_id}/runs/{run_id}").json()
    assert all(p["status"] == "succeeded" for p in detail["phases"]), detail["phases"]
    generation = [i for i in detail["invocations"] if i["phase"] == "generation"]
    # Two modules, each written wrong once, tested in the real sandbox, corrected and verified.
    assert sorted((i["shard"], i["iteration"], i["status"]) for i in generation) == [
        ("module_a", 1, "failed"),
        ("module_a", 2, "succeeded"),
        ("module_b", 1, "failed"),
        ("module_b", 2, "succeeded"),
    ]
    failed = next(i for i in generation if i["status"] == "failed")
    assert "expected 42, got 43" in failed["error"]["verification"]


async def test_a_verification_that_never_passes_escalates_after_exactly_max_iterations(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, databases: Databases, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id, max_iterations=2)
    run_id = await make_run(
        owner_engine, world.tenant_a, project_id, version, max_iterations=2,
        options={"fail_verification": "inventory"},
    )  # fmt: skip
    async with httpx.AsyncClient() as http:
        await execute_run(runtime(app_engine, databases.app_url, http), run_id, world.tenant_a)
    state = await run_state(owner_engine, run_id)
    assert (state["status"], state["waiting_reason"]) == ("waiting", "escalation")
    attempts = await fetch(
        owner_engine,
        "SELECT iteration, status FROM agent_invocation WHERE run_id = :r AND phase = 'inventory' ORDER BY iteration",
        r=run_id,
    )
    assert attempts == [{"iteration": 1, "status": "failed"}, {"iteration": 2, "status": "escalated"}]
    (question,) = await fetch(owner_engine, "SELECT reason, impact, context FROM question WHERE run_id = :r", r=run_id)
    assert (question["reason"], question["impact"]) == ("retriesExhausted", "high")
    assert "expected 42, got 41" in question["context"]
