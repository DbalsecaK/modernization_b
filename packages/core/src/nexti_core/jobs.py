"""The queue contract between the API and the worker (ADR-0009). The API enqueues the execution of a run in the same
transaction that creates or changes it (a decided gate, an answered question); the worker registers the task under
the same name. Neither side imports the other.

One job per run at a time: the Procrastinate `lock` makes the jobs of a run execute one after the other, and the
`queueing_lock` keeps at most one waiting job per run (the waiting one reads the latest state when it starts).
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

RUNS_QUEUE = "runs"
EXECUTE_RUN_TASK = "nexti:execute_run"

_DEFER = text(
    "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW(:queue, :task, 0, :lock, :queueing_lock, CAST(:args AS jsonb), "
    "NULL)::procrastinate_job_to_defer_v1])"
)


def run_lock(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


async def defer_run(conn: AsyncConnection, run_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """Enqueue the execution of the run in the caller's transaction. False when a job of the run is already
    waiting (it will see the change when it starts)."""
    args = json.dumps({"run_id": str(run_id), "tenant_id": str(tenant_id)})
    lock = run_lock(run_id)
    try:
        async with conn.begin_nested():
            await conn.execute(
                _DEFER,
                {"queue": RUNS_QUEUE, "task": EXECUTE_RUN_TASK, "lock": lock, "queueing_lock": lock, "args": args},
            )
    except IntegrityError:
        return False
    return True


UI_CHANGE_TASK = "nexti:apply_ui_change"


async def defer_ui_change(
    conn: AsyncConnection, message_id: uuid.UUID, tenant_id: uuid.UUID, project_id: uuid.UUID, screen: str
) -> None:
    """Enqueue a change asked through the prototype chat (D-24) in the caller's transaction. The changes of one
    screen run one after the other (each starts from the version the previous one produced)."""
    args = json.dumps({"message_id": str(message_id), "tenant_id": str(tenant_id)})
    lock = f"ui:{project_id}:{screen}"
    await conn.execute(
        _DEFER, {"queue": RUNS_QUEUE, "task": UI_CHANGE_TASK, "lock": lock, "queueing_lock": None, "args": args}
    )


BACKLOG_SYNC_TASK = "nexti:sync_backlog"


async def defer_backlog_sync(conn: AsyncConnection, project_id: uuid.UUID, tenant_id: uuid.UUID, reason: str) -> bool:
    """Enqueue the sync of the project's backlog with Jira or Azure DevOps (spec 7.6, ADR-0019) in the caller's
    transaction. One sync per project at a time and at most one waiting (it reads the latest state when it starts)."""
    args = json.dumps({"project_id": str(project_id), "tenant_id": str(tenant_id), "reason": reason})
    lock = f"backlog:{project_id}"
    try:
        async with conn.begin_nested():
            await conn.execute(
                _DEFER, {"queue": RUNS_QUEUE, "task": BACKLOG_SYNC_TASK, "lock": lock, "queueing_lock": lock,
                         "args": args},
            )  # fmt: skip
    except IntegrityError:
        return False
    return True
