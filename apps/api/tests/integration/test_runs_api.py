"""The API of runs (plan M3 step 6): launching enqueues the worker in the same transaction, one run at a time; gates
need their permission and respect segregation of duties; answers resume the run; My tasks and the activity stream
only show what the user may see, and the exported JSON carries no secret."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import Role, RoleAssignment

from .conftest import World
from .run_support import execute, fetch, make_config, make_project, make_run

SECRET = "sk-or-v1-" + "Zq" * 16


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(api_settings.model_copy(update={"dev_auth_enabled": True})), base_url="https://testserver"
    ) as client:
        yield client


def sign_in(api: TestClient, user: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


async def grant(owner: AsyncEngine, world: World, user: uuid.UUID, role_key: str, project_id: uuid.UUID) -> None:
    async with owner.begin() as conn:
        role_id = (
            await conn.execute(select(Role.id).where(Role.tenant_id == world.tenant_a, Role.key == role_key))
        ).scalar_one()
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=user, role_id=role_id, scope="project", project_id=project_id
            )
        )


async def configured_project(owner: AsyncEngine, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await make_config(owner, world.tenant_a, project_id)
    return project_id


async def waiting_at(owner: AsyncEngine, run_id: uuid.UUID, gate: str, tenant_id: uuid.UUID) -> None:
    await execute(
        owner, "UPDATE run SET status = 'waiting', waiting_reason = 'gate', current_phase = 'x' WHERE id = :r", r=run_id
    )
    await execute(
        owner, "INSERT INTO gate (tenant_id, run_id, gate, required) VALUES (:t, :r, :g, true)",
        t=tenant_id, r=run_id, g=gate,
    )  # fmt: skip


async def jobs_of(owner: AsyncEngine, run_id: uuid.UUID) -> list[dict[str, Any]]:
    return await fetch(
        owner, "SELECT status, lock FROM procrastinate_jobs WHERE args->>'run_id' = :r ORDER BY id", r=str(run_id)
    )


def sse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


async def test_launching_a_run_enqueues_it_and_only_one_runs_at_a_time(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await configured_project(owner_engine, world)
    unconfigured = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)

    created = api.post(
        f"/api/v1/projects/{project_id}/runs", json={"kind": "demo", "options": {"fixAfter": 2}}, headers=headers
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert (run["status"], run["kind"], run["startedBy"]) == ("queued", "demo", str(world.a_user))
    assert run["options"] == {"fix_after": 2}  # stored as the worker reads it
    assert await jobs_of(owner_engine, uuid.UUID(run["id"])) == [{"status": "todo", "lock": f"run:{run['id']}"}]

    again = api.post(f"/api/v1/projects/{project_id}/runs", json={"kind": "pipeline"}, headers=headers)
    assert again.status_code == 409
    assert again.json()["code"] == "run_active"
    assert api.post(f"/api/v1/projects/{unconfigured}/runs", json={}, headers=headers).json()["code"] == (
        "project_not_configured"
    )
    bad = api.post(f"/api/v1/projects/{project_id}/runs", json={"kind": "pipeline", "options": {}}, headers=headers)
    assert bad.status_code == 422

    assert api.post(f"/api/v1/projects/{project_id}/runs/{run['id']}:cancel", headers=headers).json()["status"] == (
        "cancelled"
    )
    listed = api.get(f"/api/v1/projects/{project_id}/runs").json()
    assert [r["id"] for r in listed] == [run["id"]]


async def test_a_gate_needs_its_permission_and_the_launcher_cannot_decide_it(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await configured_project(owner_engine, world)
    await grant(owner_engine, world, world.shared, "architect", project_id)
    await reconcile(app_engine, fga)
    version = (
        await fetch(owner_engine, "SELECT max(version) AS v FROM project_config WHERE project_id = :p", p=project_id)
    )[0]["v"]
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, started_by=world.a_user)
    await waiting_at(owner_engine, run_id, "C1", world.tenant_a)
    base = f"/api/v1/projects/{project_id}/runs/{run_id}/gates"

    admin = sign_in(api, world.a_user)
    own = api.post(f"{base}/C1:approve", json={}, headers=admin)
    assert own.status_code == 403
    assert own.json()["code"] == "segregation_of_duties"
    denials = await fetch(
        owner_engine,
        "SELECT outcome FROM audit_log WHERE action = 'gate.decide' AND details->>'run_id' = :r",
        r=str(run_id),
    )
    assert denials == [{"outcome": "denied"}]

    architect = sign_in(api, world.shared)
    assert api.post(f"{base}/C1:approve", json={}, headers=architect).status_code == 403  # no gate.c1.approve
    assert api.post(f"{base}/C9:approve", json={}, headers=architect).status_code == 404

    await execute(owner_engine, "UPDATE gate SET gate = 'C4' WHERE run_id = :r", r=run_id)
    assert api.post(f"{base}/C4:reject", json={}, headers=architect).json()["code"] == "comment_required"
    approved = api.post(f"{base}/C4:approve", json={"comment": "Signed"}, headers=architect)
    assert approved.status_code == 200, approved.text
    assert (approved.json()["status"], approved.json()["decidedBy"]) == ("approved", str(world.shared))
    assert [j["status"] for j in await jobs_of(owner_engine, run_id)] == ["todo"]
    assert api.post(f"{base}/C4:approve", json={}, headers=architect).json()["code"] == "gate_decided"

    detail = api.get(f"/api/v1/projects/{project_id}/runs/{run_id}").json()
    assert detail["gates"][0]["decidedByName"]
    assert detail["costVisible"] is False


async def test_answers_resume_the_run_and_low_impact_questions_are_accepted_together(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await configured_project(owner_engine, world)
    await reconcile(app_engine, fga)
    version = (
        await fetch(owner_engine, "SELECT max(version) AS v FROM project_config WHERE project_id = :p", p=project_id)
    )[0]["v"]
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, started_by=world.shared)
    await execute(
        owner_engine, "UPDATE run SET status = 'waiting', waiting_reason = 'question' WHERE id = :r", r=run_id
    )
    ids = []
    for impact in ("high", "low", "low"):
        (row,) = await fetch(
            owner_engine,
            "INSERT INTO question (tenant_id, project_id, run_id, phase, agent_key, question_text, reason, impact, "
            "recommended, alternatives) VALUES (:t, :p, :r, 'inventory', 'legacy-analyst', 'Which rounding?', "
            "'contradiction', :impact, '{\"key\": \"halfUp\", \"label\": \"Half up\"}', "
            "'[{\"key\": \"bankers\", \"label\": \"Bankers\"}]') RETURNING id",
            t=world.tenant_a, p=project_id, r=run_id, impact=impact,
        )  # fmt: skip
        ids.append(row["id"])
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}/questions"

    assert (
        api.post(f"{base}/{ids[0]}:answer", json={"option": "floor"}, headers=headers).json()["code"]
        == "unknown_option"
    )
    assert api.post(f"{base}/{ids[0]}:answer", json={}, headers=headers).status_code == 422
    answered = api.post(f"{base}/{ids[0]}:answer", json={"option": "bankers"}, headers=headers)
    assert answered.status_code == 200, answered.text
    assert (answered.json()["answer"], answered.json()["wasRecommended"]) == ("bankers", False)
    assert await jobs_of(owner_engine, run_id) == []  # two questions still open
    assert (
        api.post(f"{base}/{ids[0]}:answer", json={"text": "again"}, headers=headers).json()["code"] == "question_closed"
    )

    accepted = api.post(f"{base}:accept-recommended", json={}, headers=headers)
    assert accepted.json() == {"answered": 2}
    assert [j["status"] for j in await jobs_of(owner_engine, run_id)] == ["todo"]
    open_left = api.get(base, params={"status": "open"}).json()
    assert open_left == []
    answers = {q["id"]: (q["answer"], q["wasRecommended"]) for q in api.get(base).json()}
    assert answers[str(ids[1])] == ("halfUp", True)


async def test_tasks_and_activity_only_show_authorized_projects_and_exports_carry_no_secret(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    mine = await configured_project(owner_engine, world)
    other = await configured_project(owner_engine, world)
    await grant(owner_engine, world, world.shared, "architect", mine)
    await reconcile(app_engine, fga)
    runs = {}
    for project_id in (mine, other):
        version = (
            await fetch(
                owner_engine, "SELECT max(version) AS v FROM project_config WHERE project_id = :p", p=project_id
            )
        )[0]["v"]
        run_id = await make_run(owner_engine, world.tenant_a, project_id, version, started_by=world.a_user)
        await waiting_at(owner_engine, run_id, "C4", world.tenant_a)
        await execute(
            owner_engine,
            "INSERT INTO question (tenant_id, project_id, run_id, phase, agent_key, question_text, reason, impact, "
            "recommended) VALUES (:t, :p, :r, 'design', 'solution-architect', :q, 'lowConfidence', 'high', "
            "'{\"key\": \"a\", \"label\": \"A\"}')",
            t=world.tenant_a, p=project_id, r=run_id, q=f"Question of {project_id}",
        )  # fmt: skip
        await execute(
            owner_engine,
            "INSERT INTO activity_event (tenant_id, project_id, run_id, kind, status, message, cost_usd, payload) "
            "VALUES (:t, :p, :r, 'failed', 'failed', :m, 0.25, CAST(:payload AS jsonb))",
            t=world.tenant_a, p=project_id, r=run_id, m=f"call failed with {SECRET}",
            payload=json.dumps({"error": f"401 Bearer {SECRET}", "apiKey": SECRET}),
        )  # fmt: skip
        runs[project_id] = run_id

    sign_in(api, world.shared)
    tasks = api.get("/api/v1/tasks").json()
    assert {(t["kind"], t["projectId"]) for t in tasks} == {("question", str(mine)), ("gate", str(mine))}
    assert next(t for t in tasks if t["kind"] == "gate")["gate"] == "C4"

    stream = api.get("/api/v1/activity/events", params={"follow": "false"})
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = sse_events(stream.text)
    assert {e["projectId"] for e in events} == {str(mine)}
    assert SECRET not in stream.text
    assert all(e["costUsd"] is None for e in events)  # the architect has no cost.view
    run_stream = api.get(f"/api/v1/projects/{mine}/runs/{runs[mine]}/events", params={"follow": "false"})
    assert [e["runId"] for e in sse_events(run_stream.text)] == [str(runs[mine])]
    resumed = api.get(
        "/api/v1/activity/events", params={"follow": "false"}, headers={"Last-Event-ID": str(events[-1]["id"])}
    )
    assert sse_events(resumed.text) == []

    exported = api.get(f"/api/v1/activity/events/{events[0]['id']}/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert SECRET not in exported.text
    assert exported.json()["payload"]["apiKey"] == "[REDACTED]"
    others = await fetch(owner_engine, "SELECT id FROM activity_event WHERE project_id = :p", p=other)
    assert api.get(f"/api/v1/activity/events/{others[0]['id']}/export").status_code == 403

    sign_in(api, world.b_user)
    assert sse_events(api.get("/api/v1/activity/events", params={"follow": "false"}).text) == []
    assert api.get(f"/api/v1/activity/events/{events[0]['id']}/export").status_code == 404
    assert api.get("/api/v1/tasks").json() == []

    sign_in(api, world.a_user)
    admin_events = sse_events(api.get("/api/v1/activity/events", params={"follow": "false"}).text)
    assert {str(mine), str(other)} <= {e["projectId"] for e in admin_events}
    assert any(e["costUsd"] is not None for e in admin_events)


async def test_the_event_stream_of_a_run_of_another_project_is_not_found(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await configured_project(owner_engine, world)
    other = await configured_project(owner_engine, world)
    await reconcile(app_engine, fga)
    version = (
        await fetch(owner_engine, "SELECT max(version) AS v FROM project_config WHERE project_id = :p", p=other)
    )[0]["v"]
    run_id = await make_run(owner_engine, world.tenant_a, other, version)
    sign_in(api, world.a_user)
    assert api.get(f"/api/v1/projects/{project_id}/runs/{run_id}/events", params={"follow": "false"}).status_code == 404
    assert api.get(f"/api/v1/projects/{project_id}/runs/{run_id}").status_code == 404
