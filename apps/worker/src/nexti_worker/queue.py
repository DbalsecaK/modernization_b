"""The Procrastinate tasks of the worker (ADR-0009). `execute_run` is what the API enqueues (nexti_core.jobs);
`retry_stalled` hands the jobs of a dead worker (no heartbeat) back to the queue, where another worker continues them
from the last checkpoint."""

import uuid

import structlog
from procrastinate import App, Blueprint, JobContext, PsycopgConnector, RetryStrategy

from nexti_core.jobs import BACKLOG_SYNC_TASK, EXECUTE_RUN_TASK, RUNS_QUEUE, UI_CHANGE_TASK
from nexti_worker.backlog import sync_backlog, tracker_for
from nexti_worker.runner import Runtime, execute_run, fail_run
from nexti_worker.ui_chat import apply_ui_change

MAINTENANCE_QUEUE = "maintenance"
NAMESPACE, _, TASK_NAME = EXECUTE_RUN_TASK.partition(":")
MAX_ATTEMPTS = 4

log = structlog.get_logger("nexti_worker")
tasks = Blueprint()


def _runtime(context: JobContext) -> Runtime:
    runtime: Runtime = context.additional_context["runtime"]
    return runtime


@tasks.task(
    name=TASK_NAME,
    queue=RUNS_QUEUE,
    pass_context=True,
    retry=RetryStrategy(max_attempts=MAX_ATTEMPTS, exponential_wait=2),
)
async def execute_run_task(context: JobContext, run_id: str, tenant_id: str) -> None:
    runtime = _runtime(context)
    run, tenant = uuid.UUID(run_id), uuid.UUID(tenant_id)
    structlog.contextvars.bind_contextvars(run_id=run_id, job_id=context.job.id)
    try:
        outcome = await execute_run(runtime, run, tenant)
        log.info("run.job_done", outcome=outcome)
    except Exception as exc:
        # attempts counts the previous failures: the last attempt fails the run instead of retrying.
        if context.job.attempts + 1 >= MAX_ATTEMPTS:
            log.error("run.job_failed", error=type(exc).__name__)
            await fail_run(runtime, run, tenant, exc)
        else:
            log.warning("run.job_retry", error=type(exc).__name__, attempt=context.job.attempts + 1)
        raise
    finally:
        structlog.contextvars.unbind_contextvars("run_id", "job_id")


@tasks.task(name=UI_CHANGE_TASK.partition(":")[2], queue=RUNS_QUEUE, pass_context=True)
async def apply_ui_change_task(context: JobContext, message_id: str, tenant_id: str) -> None:
    """A change asked through the prototype chat (D-24)."""
    runtime = _runtime(context)
    if runtime.gateway is None or runtime.objects is None or runtime.sandboxes is None:
        raise RuntimeError("the prototype chat needs the model gateway, the object store and the sandbox")
    outcome = await apply_ui_change(runtime.engine, runtime.gateway, runtime.objects, runtime.sandboxes,
                                    uuid.UUID(message_id), uuid.UUID(tenant_id))  # fmt: skip
    log.info("ui_change.job_done", outcome=outcome)


@tasks.task(name=BACKLOG_SYNC_TASK.partition(":")[2], queue=RUNS_QUEUE, pass_context=True,
            retry=RetryStrategy(max_attempts=3, exponential_wait=5))  # fmt: skip
async def sync_backlog_task(context: JobContext, project_id: str, tenant_id: str, reason: str = "manual") -> None:
    """The project's backlog in Jira or Azure DevOps (spec 7.6, ADR-0019): after C1, after a verdict, on request."""
    runtime = _runtime(context)
    summary = await sync_backlog(runtime.engine, runtime.objects, runtime.secrets,
                                 runtime.trackers or tracker_for(runtime.http), uuid.UUID(tenant_id),
                                 uuid.UUID(project_id), reason)  # fmt: skip
    log.info("backlog.job_done", project_id=project_id, reason=reason, summary=summary)


@tasks.periodic(cron="* * * * * */5")
@tasks.task(name="retry_stalled", queue=MAINTENANCE_QUEUE, pass_context=True, queueing_lock="retry_stalled")
async def retry_stalled(context: JobContext, timestamp: int) -> None:
    seconds: float = context.additional_context["stalled_after_seconds"]
    manager = context.app.job_manager
    for job in await manager.get_stalled_jobs(seconds_since_heartbeat=seconds):
        log.warning("job.stalled_retry", job_id=job.id, task=job.task_name)
        await manager.retry_job(job)
    await manager.prune_stalled_workers(seconds_since_heartbeat=seconds * 3)


def create_app(dsn: str) -> App:
    app = App(connector=PsycopgConnector(conninfo=dsn))
    app.add_tasks_from(tasks, namespace=NAMESPACE)
    return app
