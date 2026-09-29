"""Live activity (spec 18.8): the events the worker writes, served as Server-Sent Events, and the JSON of one event.
Only projects the user may see (OpenFGA ListObjects) and only the active tenant (RLS). The stream polls every second
from the last id it sent; a client that reconnects sends Last-Event-ID and misses nothing. Events are redacted by the
worker and once more on the way out."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import RowMapping, func, select

from nexti_api.admin.common import not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, deny, require_project, require_tenant
from nexti_api.runs.router import cost_visible
from nexti_api.runs.schemas import FINAL, ActivityEventOut
from nexti_core.db.models import ActivityEvent, Run
from nexti_core.redaction import redact

router = APIRouter(tags=["activity"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
BATCH = 200
VISIBILITY_REFRESH_SECONDS = 30.0
# A fresh activity stream starts with the latest events, not the whole history.
BACKLOG = 100


def event_out(event: RowMapping, money: bool) -> ActivityEventOut:
    return ActivityEventOut.model_validate(
        {
            **event,
            "message": str(redact(event["message"])),
            "cost_usd": event["cost_usd"] if money else None,
            "payload": redact(event["payload"]),
        }
    )


def _sse(event: ActivityEventOut) -> str:
    return f"id: {event.id}\nevent: activity\ndata: {event.model_dump_json(by_alias=True)}\n\n"


async def _visible_projects(request: Request, auth: Authorized) -> list[uuid.UUID]:
    objects = await request.app.state.fga.list_objects(names.user(auth.user_id), "viewer", "project")
    return [uuid.UUID(o.split(":", 1)[1]) for o in objects]


def _start(after: int | None, last_event_id: str | None) -> int | None:
    """Where the client left off (a reconnecting EventSource sends Last-Event-ID), or None for a fresh stream."""
    if last_event_id and last_event_id.isdigit():
        return int(last_event_id)
    return after


async def _batch(
    request: Request, auth: Authorized, after: int, projects: Sequence[uuid.UUID], run_id: uuid.UUID | None
) -> list[RowMapping]:
    query = select(ActivityEvent).where(ActivityEvent.id > after, ActivityEvent.project_id.in_(projects))
    if run_id is not None:
        query = query.where(ActivityEvent.run_id == run_id)
    async with transaction(request, auth) as conn:
        return list((await conn.execute(query.order_by(ActivityEvent.id).limit(BATCH))).mappings().all())


async def _backlog_start(request: Request, auth: Authorized, projects: Sequence[uuid.UUID]) -> int:
    recent = (
        select(ActivityEvent.id)
        .where(ActivityEvent.project_id.in_(projects))
        .order_by(ActivityEvent.id.desc())
        .limit(BACKLOG)
        .subquery()
    )
    async with transaction(request, auth) as conn:
        oldest = (await conn.execute(select(func.min(recent.c.id)))).scalar_one_or_none()
    return int(oldest) - 1 if oldest is not None else 0


async def _stream(
    request: Request,
    auth: Authorized,
    start: int | None,
    follow: bool,
    project_filter: uuid.UUID | None,
    run_id: uuid.UUID | None,
) -> AsyncIterator[str]:
    money = await cost_visible(request, auth)
    loop = asyncio.get_running_loop()
    refreshed = 0.0
    projects: list[uuid.UUID] = []
    last_sent = loop.time()
    yield "retry: 3000\n\n"
    while True:
        if loop.time() - refreshed > VISIBILITY_REFRESH_SECONDS:
            visible = await _visible_projects(request, auth)
            projects = [p for p in visible if project_filter is None or p == project_filter]
            refreshed = loop.time()
        if start is None:
            # A run's stream starts at its beginning; the activity of every project, at its latest events.
            start = 0 if run_id is not None or not projects else await _backlog_start(request, auth, projects)
        after = start
        events = await _batch(request, auth, after, projects, run_id) if projects else []
        for event in events:
            yield _sse(event_out(event, money))
            start = int(event["id"])
            last_sent = loop.time()
        if len(events) == BATCH:
            continue
        if not follow:
            return
        if run_id is not None:
            async with transaction(request, auth) as conn:
                status = (await conn.execute(select(Run.status).where(Run.id == run_id))).scalar_one_or_none()
            if status in FINAL and not events:
                return
        if await request.is_disconnected():
            return
        if loop.time() - last_sent > HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_sent = loop.time()
        await asyncio.sleep(POLL_SECONDS)


def _response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/projects/{project_id}/runs/{run_id}/events")
async def run_events(
    request: Request,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    auth: ViewProject,
    after: Annotated[int | None, Query(ge=0)] = None,
    follow: bool = True,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    async with transaction(request, auth) as conn:
        found = (await conn.execute(select(Run.id).where(Run.id == run_id, Run.project_id == project_id))).first()
    if found is None:
        raise not_found("run")
    return _response(_stream(request, auth, _start(after, last_event_id), follow, project_id, run_id))


@router.get("/api/v1/activity/events")
async def activity_events(
    request: Request,
    auth: TenantMember,
    after: Annotated[int | None, Query(ge=0)] = None,
    follow: bool = True,
    project_id: Annotated[uuid.UUID | None, Query(alias="projectId")] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    return _response(_stream(request, auth, _start(after, last_event_id), follow, project_id, None))


@router.get("/api/v1/activity/events/{event_id}/export", responses={200: {"model": ActivityEventOut}})
async def export_event(request: Request, event_id: int, auth: TenantMember) -> JSONResponse:
    """The JSON of one event, without secrets, as a download."""
    async with transaction(request, auth) as conn:
        event = (await conn.execute(select(ActivityEvent).where(ActivityEvent.id == event_id))).mappings().one_or_none()
    if event is None:
        raise not_found("event")
    project = names.project(event["project_id"])
    if not await request.app.state.fga.check(names.user(auth.user_id), "viewer", project):
        await deny(request, auth.session, auth.tenant_id, "project.view", project)
    body: dict[str, Any] = json.loads(
        event_out(event, await cost_visible(request, auth)).model_dump_json(by_alias=True)
    )
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="activity-event-{event_id}.json"'})
