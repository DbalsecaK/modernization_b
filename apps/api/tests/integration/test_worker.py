"""The worker on the real database (plan M3 step 5): runs start, stop at gates and questions, resume from the
checkpoint with what people decided, write redacted events, and only see their own tenant."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.jobs import EXECUTE_RUN_TASK, RUNS_QUEUE, defer_run
from nexti_core.redaction import REDACTED
from nexti_worker.loading import RunNotFoundError, load_run
from nexti_worker.queue import create_app
from nexti_worker.runner import Runtime, execute_run
from nexti_worker.store import DbRunStore

from .conftest import Databases, World
from .run_support import execute, fetch, make_config, make_project, make_run, runtime


@pytest.fixture
async def worker(app_engine: AsyncEngine, databases: Databases) -> AsyncIterator[Runtime]:
    async with httpx.AsyncClient() as http:
        yield runtime(app_engine, databases.app_url, http)


async def approve(owner: AsyncEngine, run_id: uuid.UUID, gate: str, by: uuid.UUID) -> None:
    await execute(
        owner,
        "UPDATE gate SET status = 'approved', decided_by = :by, decided_at = now() WHERE run_id = :r AND gate = :g",
        r=run_id,
        g=gate,
        by=by,
    )


async def run_row(owner: AsyncEngine, run_id: uuid.UUID) -> dict[str, object]:
    (row,) = await fetch(owner, "SELECT * FROM run WHERE id = :r", r=run_id)
    return row


async def test_a_demo_run_stops_at_the_gates_and_finishes_after_approval(
    owner_engine: AsyncEngine, world: World, worker: Runtime
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version, started_by=world.shared)

    assert await execute_run(worker, run_id, world.tenant_a) == "waiting"
    run = await run_row(owner_engine, run_id)
    assert (run["waiting_reason"], run["current_phase"]) == ("gate", "ruleReview")
    phases = await fetch(
        owner_engine, "SELECT phase, status FROM phase_run WHERE run_id = :r ORDER BY position", r=run_id
    )
    assert phases[0] == {"phase": "preflight", "status": "succeeded"}
    assert {"phase": "generation", "status": "pending"} in phases
    # A job with nothing new to do leaves the run waiting.
    assert await execute_run(worker, run_id, world.tenant_a) == "still waiting"

    await approve(owner_engine, run_id, "C1", world.a_user)
    assert await execute_run(worker, run_id, world.tenant_a) == "waiting"
    assert (await run_row(owner_engine, run_id))["current_phase"] == "verification"
    gates = await fetch(owner_engine, "SELECT gate, required FROM gate WHERE run_id = :r ORDER BY gate", r=run_id)
    assert gates == [
        {"gate": "C1", "required": True}, {"gate": "C2", "required": False}, {"gate": "C3", "required": False},
        {"gate": "C4", "required": True},
    ]  # fmt: skip

    await approve(owner_engine, run_id, "C4", world.a_user)
    assert await execute_run(worker, run_id, world.tenant_a) == "succeeded"
    generation = await fetch(
        owner_engine,
        "SELECT shard, iteration, status FROM agent_invocation WHERE run_id = :r AND phase = 'generation' "
        "ORDER BY shard, iteration",
        r=run_id,
    )
    assert [(g["shard"], g["iteration"], g["status"]) for g in generation] == [
        ("module_a", 1, "failed"),
        ("module_a", 2, "succeeded"),
        ("module_b", 1, "failed"),
        ("module_b", 2, "succeeded"),
    ]
    kinds = [
        e["kind"]
        for e in await fetch(owner_engine, "SELECT kind FROM activity_event WHERE run_id = :r ORDER BY id", r=run_id)
    ]
    assert kinds[0] == "runStarted"
    assert kinds[-1] == "runFinished"
    assert kinds.count("phaseStarted") == 13  # each phase once, even across three jobs
    assert kinds.count("selfCorrected") == 2
    assert await execute_run(worker, run_id, world.tenant_a) == "already succeeded"


async def test_a_question_waits_for_the_answer_and_the_run_continues(
    owner_engine: AsyncEngine, world: World, worker: Runtime
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version, options={"question_phase": "inventory"})
    await execute_run(worker, run_id, world.tenant_a)
    assert (await run_row(owner_engine, run_id))["waiting_reason"] == "question"
    (question,) = await fetch(owner_engine, "SELECT * FROM question WHERE run_id = :r", r=run_id)
    assert question["status"] == "open"
    assert question["recommended"]["key"] == "halfUp"
    assert question["impact"] == "low"
    invocations = len(await fetch(owner_engine, "SELECT id FROM agent_invocation WHERE run_id = :r", r=run_id))

    await execute(
        owner_engine,
        "UPDATE question SET status = 'answered', answer = 'bankers', was_recommended = false, answered_by = :u, "
        "answered_at = now() WHERE id = :q",
        q=question["id"], u=world.a_user,
    )  # fmt: skip
    await execute_run(worker, run_id, world.tenant_a)
    run = await run_row(owner_engine, run_id)
    assert (run["waiting_reason"], run["current_phase"]) == ("gate", "ruleReview")
    (inventory,) = await fetch(
        owner_engine, "SELECT detail FROM phase_run WHERE run_id = :r AND phase = 'inventory'", r=run_id
    )
    assert "rounding: bankers" in inventory["detail"]
    # The inventory agent's work before the question was not repeated.
    inventory_invocations = await fetch(
        owner_engine, "SELECT id FROM agent_invocation WHERE run_id = :r AND phase = 'inventory'", r=run_id
    )
    assert len(inventory_invocations) == 1
    assert len(await fetch(owner_engine, "SELECT id FROM agent_invocation WHERE run_id = :r", r=run_id)) > invocations


async def test_a_real_pipeline_asks_when_the_preflight_fails(
    owner_engine: AsyncEngine, world: World, worker: Runtime
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version, kind="pipeline")
    await execute_run(worker, run_id, world.tenant_a)
    run = await run_row(owner_engine, run_id)
    assert (run["waiting_reason"], run["current_phase"]) == ("question", "preflight")
    (question,) = await fetch(
        owner_engine, "SELECT question_text, context, reason FROM question WHERE run_id = :r", r=run_id
    )
    assert question["reason"] == "missingInformation"
    assert "inputs: the project has no accepted input" in question["context"]
    assert "models: no model profile for" in question["context"]


async def test_events_and_errors_are_redacted_before_they_are_written(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version)
    loaded = await load_run(app_engine, run_id, world.tenant_a)
    store = DbRunStore(app_engine, loaded.context)
    secret = "sk-or-v1-" + "Qw" * 16
    await store.event(
        "failed", "failed", f"call failed with {secret}", payload={"error": f"401 {secret}", "apiKey": "x"}
    )
    invocation = uuid.uuid4()
    await store.invocation_started(invocation, "generation", "backend-dev", 1)
    await store.invocation_finished(invocation, "failed", error={"message": f"Bearer {secret}"})
    rows = await fetch(owner_engine, "SELECT message, payload FROM activity_event WHERE run_id = :r", r=run_id)
    (errors,) = await fetch(owner_engine, "SELECT error FROM agent_invocation WHERE id = :i", i=invocation)
    assert secret not in str(rows) + str(errors)
    assert rows[0]["payload"]["apiKey"] == REDACTED
    assert REDACTED in rows[0]["message"]


async def test_the_worker_only_sees_the_runs_of_the_job_tenant(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version)
    with pytest.raises(RunNotFoundError):
        await load_run(app_engine, run_id, world.tenant_b)


async def test_a_run_enqueued_with_its_transaction_is_executed_by_a_queue_worker(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World, worker: Runtime
) -> None:
    project = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project)
    run_id = await make_run(owner_engine, world.tenant_a, project, version)
    async with scoped_connection(app_engine, DbScope(tenant_id=world.tenant_a)) as conn:
        assert await defer_run(conn, run_id, world.tenant_a)
        # A second job while the first waits is not queued: the waiting one reads the latest state.
        assert not await defer_run(conn, run_id, world.tenant_a)

    app = create_app(worker.dsn)
    async with app.open_async():
        await app.run_worker_async(
            queues=[RUNS_QUEUE], wait=False, install_signal_handlers=False,
            additional_context={"runtime": worker, "stalled_after_seconds": 20},
        )  # fmt: skip
    run = await run_row(owner_engine, run_id)
    assert (run["status"], run["waiting_reason"]) == ("waiting", "gate")
    (job,) = await fetch(
        owner_engine, "SELECT status, task_name, lock FROM procrastinate_jobs WHERE args->>'run_id' = :r", r=str(run_id)
    )
    assert job == {"status": "succeeded", "task_name": EXECUTE_RUN_TASK, "lock": f"run:{run_id}"}
