"""Platform operations (spec 18.4 "Operación de plataforma", NexTI only): the health of the workers and the queues,
the runs in progress across tenants, and the jobs that failed in the last day.

Workers and jobs are Procrastinate's own tables (ADR-0009): a worker is alive while its heartbeat is recent. Runs are
read with platform scope. Each API and worker instance registers its version and deployment profile (ADR-0024)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_platform
from nexti_api.schemas import ApiModel
from nexti_core.instances import deployed_version

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])
Operator = Annotated[Authorized, Depends(require_platform("superAdmin", "supportOperator"))]
ALIVE = timedelta(seconds=30)
INSTANCE_ALIVE = timedelta(minutes=3)  # three missed beats of a minute
DAY = timedelta(hours=24)
MAX_FAILURES = 10


class WorkerOut(ApiModel):
    id: int
    last_heartbeat: datetime
    alive: bool
    running_jobs: int


class QueueOut(ApiModel):
    queue: str
    waiting: int
    running: int


class FailedJobOut(ApiModel):
    id: int
    task: str
    queue: str
    attempts: int
    failed_at: datetime


class InstanceOut(ApiModel):
    name: str
    component: str
    version: str
    profile: str
    started_at: datetime
    last_seen_at: datetime
    alive: bool


class PlatformStatus(ApiModel):
    api_version: str
    instances: list[InstanceOut]
    workers: list[WorkerOut]
    queues: list[QueueOut]
    active_runs: int
    waiting_runs: int
    failed_last_day: int
    recent_failures: list[FailedJobOut]


@router.get("/status", response_model=PlatformStatus)
async def status(request: Request, auth: Operator) -> PlatformStatus:
    now = datetime.now(UTC)
    async with transaction(request, auth) as conn:
        workers = (await conn.execute(text(
            "SELECT w.id, w.last_heartbeat, count(j.id) FILTER (WHERE j.status = 'doing') AS running "
            "FROM procrastinate_workers w LEFT JOIN procrastinate_jobs j ON j.worker_id = w.id "
            "GROUP BY w.id, w.last_heartbeat ORDER BY w.id"))).all()  # fmt: skip
        queues = (await conn.execute(text(
            "SELECT queue_name, count(*) FILTER (WHERE status = 'todo') AS waiting, "
            "count(*) FILTER (WHERE status = 'doing') AS running FROM procrastinate_jobs "
            "WHERE status IN ('todo', 'doing') GROUP BY queue_name ORDER BY queue_name"))).all()  # fmt: skip
        runs = (await conn.execute(text(
            "SELECT count(*) FILTER (WHERE status = 'running') AS active, "
            "count(*) FILTER (WHERE status = 'waiting') AS waiting FROM run"))).one()  # fmt: skip
        instances = (await conn.execute(text(
            "SELECT name, component, version, profile, started_at, last_seen_at FROM platform_instance "
            "ORDER BY component, name"))).all()  # fmt: skip
        failed = (await conn.execute(text(
            "SELECT j.id, j.task_name, j.queue_name, j.attempts, e.at FROM procrastinate_events e "
            "JOIN procrastinate_jobs j ON j.id = e.job_id WHERE e.type = 'failed' AND e.at >= :since "
            "ORDER BY e.at DESC"), {"since": now - DAY})).all()  # fmt: skip
    return PlatformStatus(
        api_version=deployed_version("nexti-api"),
        instances=[InstanceOut(name=i.name, component=i.component, version=i.version, profile=i.profile,
                               started_at=i.started_at, last_seen_at=i.last_seen_at,
                               alive=now - i.last_seen_at <= INSTANCE_ALIVE) for i in instances],
        workers=[WorkerOut(id=w.id, last_heartbeat=w.last_heartbeat, alive=now - w.last_heartbeat <= ALIVE,
                           running_jobs=w.running) for w in workers],
        queues=[QueueOut(queue=q.queue_name, waiting=q.waiting, running=q.running) for q in queues],
        active_runs=runs.active,
        waiting_runs=runs.waiting,
        failed_last_day=len(failed),
        recent_failures=[FailedJobOut(id=f.id, task=f.task_name, queue=f.queue_name, attempts=f.attempts,
                                      failed_at=f.at) for f in failed[:MAX_FAILURES]],
    )  # fmt: skip
