"""Projects through the API (M2 acceptance): the proposed team and skills, Control agents that cannot be removed,
creation with its whole setup, versioned configuration with agents.select / skills.select, and isolation."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import (
    AppUser,
    AuditLog,
    Budget,
    Membership,
    Project,
    ProjectConfig,
    Role,
    RoleAssignment,
    RolePermission,
)

from .conftest import World

TARGET = {"architecture": "microservices-hexagonal", "backend": "spring-boot", "frontend": "angular",
          "database": "postgresql", "cloud": "aws"}  # fmt: skip
CICS = {"sources": ["cobol-cics", "bms"], "target": TARGET, "pipelineTemplate": "bankStandard"}
CONTROL = {"rules-verifier", "equivalence-validator", "acceptance-judge"}
EXPECTED_TEAM = {
    "legacy-analyst", "rules-extractor", "data-analyst", "ui-analyst", "solution-architect", "data-architect",
    "ux-designer", "backend-dev", "frontend-dev", "data-migration", "devops", "test-engineer", "code-reviewer",
    "security-auditor", *CONTROL,
}  # fmt: skip
EXPECTED_SKILLS = {
    "cobol-data-semantics", "exec-cics", "bms-parsing", "cics-to-rest", "bms-to-forms", "spring-hexagonal",
    "angular-material", "postgres", "aws-iac", "owasp", "gherkin", "golden-master", "wcag",
}  # fmt: skip


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    settings = api_settings.model_copy(update={"dev_auth_enabled": True})
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


def sign_in(api: TestClient, user_id: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(user_id)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


def new_project(**extra: Any) -> dict[str, Any]:
    return {**CICS, "name": f"Cards {uuid.uuid4().hex[:8]}", "flow": "modernization", **extra}


async def member_with_permissions(owner: AsyncEngine, world: World, permissions: list[str]) -> uuid.UUID:
    """A new member of tenant A holding a custom project role (with these permissions) in project A."""
    async with owner.begin() as conn:
        user = (
            await conn.execute(
                insert(AppUser)
                .values(email=f"m2test-{uuid.uuid4().hex[:8]}@example.test", display_name="Custom")
                .returning(AppUser.id)
            )
        ).scalar_one()
        await conn.execute(insert(Membership).values(tenant_id=world.tenant_a, user_id=user))
        role = (
            await conn.execute(
                insert(Role)
                .values(tenant_id=world.tenant_a, key=f"r{uuid.uuid4().hex[:8]}", scope="project", name="Custom")
                .returning(Role.id)
            )
        ).scalar_one()
        for key in permissions:
            await conn.execute(
                insert(RolePermission).values(
                    tenant_id=world.tenant_a, role_id=role, permission_key=key, role_scope="project"
                )
            )
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=user, role_id=role, scope="project", project_id=world.project_a
            )
        )
    return user


async def test_compose_proposes_the_expected_team_and_skills(
    api: TestClient, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.shared)
    res = api.post(
        "/api/v1/projects:compose",
        json={"flow": "modernization", "sources": CICS["sources"], "target": TARGET},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["agents"]) == EXPECTED_TEAM
    assert set(body["skills"]) == EXPECTED_SKILLS
    assert body["problems"] == []
    reasons = {r["agent"]: r["reason"] for r in body["recommendedAgents"]}
    assert reasons["ui-analyst"] == "legacyScreens"
    assert reasons["rules-verifier"] == "control"
    # Every agent is checked against the model it would use; nothing configured here, so no profile yet.
    assert {m["agent"] for m in body["models"]} == EXPECTED_TEAM


async def test_creating_a_project_sets_up_everything_in_one_step(
    api: TestClient, owner_engine: AsyncEngine, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    body = new_project(budgetUsd="1500.00", team=[{"userId": str(world.shared), "roleKey": "architect"}])
    res = api.post("/api/v1/projects", json=body, headers=headers)
    assert res.status_code == 201, res.text
    project = res.json()
    assert project["config"]["version"] == 1
    assert {a["key"] for a in project["agents"]} == EXPECTED_TEAM
    assert {s["key"] for s in project["skills"]} == EXPECTED_SKILLS
    assert all(a["version"] for a in project["agents"])  # catalog versions pinned
    assert {(m["email"], m["roleKey"]) for m in project["team"]} == {
        ("mtorres@andesbank.example", "projectOwner"),
        ("cruiz@nexti.example", "architect"),
    }
    assert project["budgetUsd"] == "1500.00"
    assert {"project.configure", "story.edit", "plan.edit", "code.view", "prototype.comment", "prototype.edit"} <= set(
        project["permissions"]
    )
    project_id = uuid.UUID(project["id"])

    # The creator and the team reach the project right away (the OpenFGA tuples were published before answering).
    assert api.get(f"/api/v1/projects/{project_id}").status_code == 200
    sign_in(api, world.shared)
    assert api.get(f"/api/v1/projects/{project_id}").status_code == 200
    assert project_id in {uuid.UUID(p["id"]) for p in api.get("/api/v1/projects").json()}

    async with owner_engine.connect() as conn:
        budget = (await conn.execute(select(Budget.amount_usd).where(Budget.project_id == project_id))).scalar_one()
        audited = (
            await conn.execute(
                select(func.count()).where(
                    AuditLog.action == "project.create", AuditLog.target == f"project:{project_id}"
                )
            )
        ).scalar_one()
    assert str(budget) == "1500.00"
    assert audited == 1


async def test_a_project_cannot_be_created_without_its_control_agents(
    api: TestClient, owner_engine: AsyncEngine, world: World
) -> None:
    headers = sign_in(api, world.a_user)
    proposal = api.post(
        "/api/v1/projects:compose",
        json={"flow": "modernization", "sources": CICS["sources"], "target": TARGET},
        headers=headers,
    ).json()
    body = new_project(agents=[a for a in proposal["agents"] if a != "acceptance-judge"], skills=proposal["skills"])
    res = api.post("/api/v1/projects", json=body, headers=headers)
    assert res.status_code == 422
    assert res.json()["code"] == "control_agent_required"
    assert {"code": "control_agent_required", "subject": "acceptance-judge"} in res.json()["problems"]
    async with owner_engine.connect() as conn:
        assert (await conn.execute(select(Project.id).where(Project.name == body["name"]))).first() is None


async def test_a_configuration_change_is_a_new_version_and_control_stays(
    api: TestClient, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    project = api.post("/api/v1/projects", json=new_project(), headers=headers).json()
    url = f"/api/v1/projects/{project['id']}/config"
    agents = [a["key"] for a in project["agents"]]
    skills = [s["key"] for s in project["skills"]]

    without_control = api.put(
        url, json={**CICS, "agents": [a for a in agents if a != "rules-verifier"], "skills": skills}, headers=headers
    )
    assert without_control.status_code == 422
    assert without_control.json()["code"] == "control_agent_required"

    full_stack = [a for a in agents if a not in {"backend-dev", "frontend-dev"}] + ["fullstack-dev"]
    changed = api.put(
        url,
        json={**CICS, "agents": full_stack, "autonomy": "guided", "changeNote": "One full stack dev"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["config"]["version"] == 2
    assert changed.json()["config"]["autonomy"] == "guided"
    assert {a["key"] for a in changed.json()["agents"]} == set(full_stack)
    versions = api.get(f"/api/v1/projects/{project['id']}/config/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["changeNote"] == "One full stack dev"


async def test_changing_agents_and_skills_needs_their_own_permissions(
    api: TestClient, owner_engine: AsyncEngine, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    configurer = await member_with_permissions(owner_engine, world, ["project.configure"])
    await reconcile(app_engine, fga)
    admin = sign_in(api, world.a_user)
    base = api.put(f"/api/v1/projects/{world.project_a}/config", json=CICS, headers=admin)
    assert base.status_code == 200, base.text
    agents = [a["key"] for a in base.json()["agents"]]
    skills = [s["key"] for s in base.json()["skills"]]
    url = f"/api/v1/projects/{world.project_a}/config"

    headers = sign_in(api, configurer)
    same_team = api.put(url, json={**CICS, "agents": agents, "skills": skills, "maxIterations": 5}, headers=headers)
    assert same_team.status_code == 200, same_team.text
    other_team = [a for a in agents if a != "ux-designer"]
    assert api.put(url, json={**CICS, "agents": other_team, "skills": skills}, headers=headers).status_code == 403
    assert api.put(url, json={**CICS, "agents": agents, "skills": skills[:-1]}, headers=headers).status_code == 403


async def test_choosing_models_at_creation_needs_models_configure(
    api: TestClient, owner_engine: AsyncEngine, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    async with owner_engine.begin() as conn:
        creator_role = (
            await conn.execute(
                insert(Role)
                .values(tenant_id=world.tenant_a, key=f"c{uuid.uuid4().hex[:8]}", scope="tenant", name="Creator")
                .returning(Role.id)
            )
        ).scalar_one()
        await conn.execute(
            insert(RolePermission).values(
                tenant_id=world.tenant_a, role_id=creator_role, permission_key="project.create", role_scope="tenant"
            )
        )
    creator = await member_with_permissions(owner_engine, world, [])
    async with owner_engine.begin() as conn:
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=creator, role_id=creator_role, scope="tenant"
            )
        )
    await reconcile(app_engine, fga)
    headers = sign_in(api, creator)
    choice = [{"agentRole": "backend-dev", "profileId": str(uuid.uuid4())}]
    assert api.post("/api/v1/projects", json=new_project(modelChoices=choice), headers=headers).status_code == 403
    assert api.post("/api/v1/projects", json=new_project(), headers=headers).status_code == 201


async def test_project_names_are_unique_in_a_tenant(api: TestClient, world: World) -> None:
    headers = sign_in(api, world.a_user)
    body = new_project()
    assert api.post("/api/v1/projects", json=body, headers=headers).status_code == 201
    again = api.post("/api/v1/projects", json=body, headers=headers)
    assert again.status_code == 409
    assert again.json()["code"] == "project_name_taken"


async def test_projects_of_another_tenant_are_unreachable(
    api: TestClient, owner_engine: AsyncEngine, fga: OpenFga, app_engine: AsyncEngine, world: World
) -> None:
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    b = world.project_b
    assert api.get(f"/api/v1/projects/{b}").status_code in (403, 404)
    assert api.patch(f"/api/v1/projects/{b}", json={"description": "x"}, headers=headers).status_code in (403, 404)
    assert api.put(f"/api/v1/projects/{b}/config", json=CICS, headers=headers).status_code in (403, 404)
    assert api.get(f"/api/v1/projects/{b}/config/versions").status_code in (403, 404)
    assert str(b) not in {p["id"] for p in api.get("/api/v1/projects").json()}
    # A team member from another tenant cannot be added.
    foreign = api.post(
        "/api/v1/projects",
        json=new_project(team=[{"userId": str(world.b_user), "roleKey": "developer"}]),
        headers=headers,
    )
    assert foreign.status_code == 404
    async with owner_engine.connect() as conn:
        assert (await conn.execute(select(ProjectConfig.version).where(ProjectConfig.project_id == b))).first() is None


async def test_unknown_catalog_keys_are_problems(api: TestClient, world: World) -> None:
    headers = sign_in(api, world.a_user)
    res = api.post(
        "/api/v1/projects",
        json=new_project(sources=["cobol-cics", "rpg"], target={**TARGET, "backend": "cobol"}, pipelineTemplate="x"),
        headers=headers,
    )
    assert res.status_code == 422
    codes = {(p["code"], p["subject"]) for p in res.json()["problems"]}
    assert ("unknown_source", "rpg") in codes
    assert ("unknown_target_option", "backend:cobol") in codes
    assert ("unknown_pipeline_template", "x") in codes


async def test_the_catalog_endpoint_serves_the_synced_catalog(api: TestClient, world: World) -> None:
    sign_in(api, world.shared)
    catalog = api.get("/api/v1/catalog").json()
    assert len(catalog["agents"]) == 19
    assert {a["key"] for a in catalog["agents"] if a["mandatory"]} == CONTROL
    assert "content" not in catalog["skills"][0]
    skill = api.get("/api/v1/catalog/skills/bms-parsing").json()
    assert skill["content"].startswith("# BMS map parsing")
    assert api.get("/api/v1/catalog/skills/nope").status_code == 404
    assert [f["key"] for f in catalog["flows"]] == ["modernization", "newFeature"]
