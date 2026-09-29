"""One execution of a run's job: rebuild the graph, decide from the database what resumes it, and run it until it
finishes or waits for a person again.

    no checkpoint             -> start
    interrupted at a gate     -> resume with the decision, if the gate was decided
    interrupted by questions  -> resume with the answers that arrived
    waiting for a phase       -> resume when this version has an executor for it
    checkpoint mid-way        -> continue (the worker died; LangGraph restarts the interrupted node)
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore
from nexti_core.secrets import SecretStore
from nexti_orchestration import Executor, compile_graph, executors_for, pending_interrupts, thread_config
from nexti_sandbox import Sandbox
from nexti_worker.loading import load_run
from nexti_worker.probe import ServicesProbe
from nexti_worker.store import DbRunStore

log = structlog.get_logger("nexti_worker")
FINAL = ("succeeded", "failed", "cancelled")


@dataclass
class Runtime:
    """What every job shares: the database, the checkpointer's DSN, the sandbox and the services."""

    engine: AsyncEngine
    dsn: str
    sandbox: Sandbox | None
    http: httpx.AsyncClient
    objects: ObjectStore | None = None
    secrets: SecretStore | None = None
    allow_private_hosts: bool = False


async def _resume_value(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    waiting: Mapping[str, Any],
    executors: Mapping[str, Executor],
) -> Any | None:
    kind = waiting.get("type")
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
        if kind == "gate":
            row = (
                await conn.execute(
                    text("SELECT status, comment, decided_by FROM gate WHERE run_id = :run AND gate = :gate"),
                    {"run": run_id, "gate": waiting["gate"]},
                )
            ).one_or_none()
            if row is None or row.status == "pending":
                return None
            return {"decision": row.status, "comment": row.comment, "by": str(row.decided_by)}
        if kind == "questions":
            ids = [uuid.UUID(q) for q in waiting.get("question_ids", [])]
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, answer, recommended, alternatives, answered_by FROM question "
                        "WHERE run_id = :run AND id = ANY(:ids) AND status = 'answered'"
                    ),
                    {"run": run_id, "ids": ids},
                )
            ).all()
            if not rows:
                return None
            return {str(r.id): _answer(r) for r in rows}
    if kind == "phaseUnavailable":
        return {"available": True} if waiting.get("phase") in executors else None
    return None


def _answer(row: Any) -> dict[str, Any]:
    """The answer as the executor reads it: the chosen option's key (the API stores the key when an option was
    chosen, the person's text otherwise)."""
    keys = {row.recommended.get("key")} | {a.get("key") for a in row.alternatives}
    answer = str(row.answer)
    return {"option": answer if answer in keys else None, "text": answer, "by": str(row.answered_by)}


async def execute_run(runtime: Runtime, run_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Run the job; returns what happened (for the logs and tests)."""
    loaded = await load_run(runtime.engine, run_id, tenant_id)
    if loaded.status in FINAL:
        return f"already {loaded.status}"
    run = loaded.context
    store = DbRunStore(runtime.engine, run)
    probe = ServicesProbe(
        runtime.engine, run, loaded.relative_cost, objects=runtime.objects, secrets=runtime.secrets,
        http=runtime.http, allow_private_hosts=runtime.allow_private_hosts,
    )  # fmt: skip
    executors = executors_for(run, probe)
    async with await AsyncConnection.connect(
        runtime.dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        graph = compile_graph(run, store, executors, AsyncPostgresSaver(conn), runtime.sandbox)
        config = thread_config(run)
        snapshot = await graph.aget_state(config)
        stopped = await store.prepare()
        if stopped:
            await store.event("info", "running", f"Resumed after the worker stopped ({stopped} invocation(s) redone)")
        if not snapshot.values and not snapshot.next:
            log.info("run.start", run_id=str(run_id))
            await graph.ainvoke({}, config)
        else:
            waiting = await pending_interrupts(graph, run)
            if waiting:
                value = await _resume_value(runtime.engine, tenant_id, run_id, waiting[0], executors)
                if value is None:
                    return "still waiting"
                log.info("run.resume", run_id=str(run_id), waiting=waiting[0].get("type"))
                await graph.ainvoke(Command(resume=value), config)
            elif snapshot.next:
                log.info("run.continue", run_id=str(run_id), next=list(snapshot.next))
                await graph.ainvoke(None, config)
            else:
                return "nothing to do"
    return str(await store.status())


async def fail_run(runtime: Runtime, run_id: uuid.UUID, tenant_id: uuid.UUID, error: BaseException) -> None:
    """The job gave up after its retries: the run fails with the (redacted) reason."""
    loaded = await load_run(runtime.engine, run_id, tenant_id)
    store = DbRunStore(runtime.engine, loaded.context)
    reason = f"The run stopped after repeated errors: {type(error).__name__}: {error}"
    await store.run_finished("failed", reason)
    await store.event("runFinished", "failed", reason, payload={"error": type(error).__name__})
