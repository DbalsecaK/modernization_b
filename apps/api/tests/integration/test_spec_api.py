"""User stories and the plan by waves through the API (spec 7.7, plan M4 section 4): Gherkin validated on save in
English and Spanish, the plan validated on every change (also by direct API calls), coverage when a story is
discarded, C1 blocked until the stories and the plan are right, everything versioned and audited."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import VALID_CRITERION, execute, fetch, make_config, make_project, make_run, seed_spec
from .test_runs_api import grant, sign_in

NO_WHEN = "Scenario: Missing\n  Given an order\n  Then it is paid"
OUT_OF_ORDER = "Escenario: Desordenado\n  Cuando se paga\n  Dado una orden\n  Entonces queda pagada"
BAD_PLACEHOLDER = (
    "Scenario Outline: Types\n  Given an account of type <type>\n  When it is debited\n  Then the result is <result>\n"
    "  Examples:\n    | type | outcome |\n    | CTE  | ok      |"
)


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def seeded(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_spec(owner, world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


def body(**extra: Any) -> dict[str, Any]:
    return {"title": "Pay an order", "criteria": [VALID_CRITERION], "links": ["RULE-001"], **extra}


async def test_invalid_gherkin_is_rejected_on_save_in_english_and_spanish(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}/stories"
    for criterion, code in ((NO_WHEN, "missing_when"), (OUT_OF_ORDER, "out_of_order"),
                            (BAD_PLACEHOLDER, "unknown_placeholder")):  # fmt: skip
        created = api.post(base, json=body(criteria=[criterion]), headers=headers)
        assert created.status_code == 422, created.text
        assert created.json()["code"] == "invalid_gherkin"
        assert code in {p["code"] for p in created.json()["problems"]}
        edited = api.put(f"{base}/US-001", json=body(criteria=[criterion]), headers=headers)
        assert edited.status_code == 422
    live = api.post("/api/v1/gherkin:validate", json={"criteria": [VALID_CRITERION, NO_WHEN]}, headers=headers).json()
    assert live["valid"] is False
    assert [(p["criterion"], p["code"]) for p in live["problems"]] == [(1, "missing_when")]
    assert api.post(base, json=body(links=["RULE-999"]), headers=headers).json()["code"] == "unknown_link"


async def test_stories_are_versioned_audited_and_can_be_split_merged_discarded_and_restored(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    base = f"/api/v1/projects/{project_id}/stories"
    second = VALID_CRITERION.replace("Scenario: Pay", "Scenario: Reject")

    edited = api.put(f"{base}/US-001", json=body(criteria=[VALID_CRITERION, second], links=["RULE-001", "RULE-003"]),
                     headers=headers).json()  # fmt: skip
    assert (edited["version"], edited["status"], edited["createdByName"]) == (2, "review", "mtorres")
    versions = api.get(f"{base}/US-001/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["action"] == "edit"

    split = api.post(f"{base}/US-001:split", json={"title": "Reject an order", "criteria": [1], "links": ["RULE-003"]},
                     headers=headers).json()  # fmt: skip
    assert [s["key"] for s in split] == ["US-001", "US-004"]
    assert split[1]["criteria"] == [second]
    assert split[0]["links"] == ["RULE-001"]
    assert split[1]["dependsOn"] == []  # US-001 depended on nothing

    merged = api.post(f"{base}/US-004:merge", json={"into": "US-003"}, headers=headers).json()
    assert set(merged["links"]) == {"RULE-003"}
    absorbed = next(s for s in api.get(base).json() if s["key"] == "US-004")
    assert (absorbed["status"], absorbed["mergedInto"]) == ("merged", "US-003")

    discarded = api.post(f"{base}/US-002:discard", json={"reason": "Not needed"}, headers=headers).json()
    assert discarded["status"] == "discarded"
    coverage = api.get(f"/api/v1/projects/{project_id}/coverage").json()
    assert coverage["gaps"] == ["RULE-002"]
    assert not coverage["complete"]
    assert api.post(f"{base}/US-002:restore", headers=headers).json()["status"] == "review"
    api.post(f"{base}/US-002:discard", json={"reason": "Migrates as is", "outOfScope": True}, headers=headers)
    coverage = api.get(f"/api/v1/projects/{project_id}/coverage").json()
    assert (coverage["gaps"], coverage["outOfScope"]) == ([], ["RULE-002"])
    assert api.put(f"{base}/US-002", json=body(), headers=headers).json()["code"] == "story_inactive"

    actions = {r["action"] for r in await fetch(
        owner_engine, "SELECT action FROM audit_log WHERE target = :t", t=f"project:{project_id}"
    )}  # fmt: skip
    assert {"story.edit", "story.split", "story.merge", "story.discard", "story.restore"} <= actions


async def test_the_plan_rejects_a_hard_dependency_and_warns_on_a_soft_one(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    await grant(owner_engine, world, world.shared, "architect", project_id)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.shared)  # the architect changes the plan, not the stories
    base = f"/api/v1/projects/{project_id}/plan"
    assert api.get(base).json()["waves"] == [["US-001"], ["US-002"], ["US-003"]]

    hard = api.put(base, json={"waves": [["US-002"], ["US-001"], ["US-003"]]}, headers=headers)
    assert hard.status_code == 422
    assert hard.json()["code"] == "invalid_plan"
    assert "hard dependency" in hard.json()["detail"]

    soft = api.put(base, json={"waves": [["US-001", "US-003"], ["US-002"]], "changeNote": "notify early"},
                   headers=headers)  # fmt: skip
    assert soft.status_code == 200, soft.text
    plan = soft.json()
    assert (plan["version"], plan["differsFromSuggested"]) == (2, True)
    assert [w["code"] for w in plan["warnings"]] == ["soft_dependency"]
    same_wave = api.put(base, json={"waves": [["US-001", "US-002", "US-003"]]}, headers=headers)
    assert same_wave.status_code == 200
    reset = api.post(f"{base}:reset", headers=headers).json()
    assert (reset["waves"], reset["differsFromSuggested"]) == ([["US-001"], ["US-002"], ["US-003"]], False)

    stories = api.put(f"/api/v1/projects/{project_id}/stories/US-001", json=body(), headers=headers)
    assert stories.status_code == 403  # the architect has plan.edit, not story.edit
    dep = api.post(f"/api/v1/projects/{project_id}/stories/US-001/dependencies",
                   json={"on": "US-003", "strength": "soft"}, headers=headers)  # fmt: skip
    assert dep.status_code == 201


async def test_c1_is_blocked_until_the_stories_and_the_plan_are_ready(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    version = await make_config(owner_engine, world.tenant_a, project_id)
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline", started_by=world.shared)
    await execute(owner_engine, "UPDATE run SET status = 'waiting', waiting_reason = 'gate' WHERE id = :r", r=run_id)
    await execute(owner_engine, "INSERT INTO gate (tenant_id, run_id, gate, required) VALUES (:t, :r, 'C1', true)",
                  t=world.tenant_a, r=run_id)  # fmt: skip
    # An imported story with invalid Gherkin, a story without criteria, an open question on RULE-003, a broken plan.
    await execute(owner_engine, "UPDATE user_story_version SET criteria = CAST(:c AS jsonb) WHERE title = 'Story 1' "
                  "AND tenant_id = :t", c=f'["{NO_WHEN}"]'.replace("\n", "\\n"), t=world.tenant_a)  # fmt: skip
    await execute(owner_engine, "UPDATE user_story_version SET criteria = '[]' WHERE title = 'Story 2' "
                  "AND tenant_id = :t", t=world.tenant_a)  # fmt: skip
    await execute(
        owner_engine,
        "INSERT INTO question (tenant_id, project_id, run_id, phase, agent_key, question_text, reason, impact, "
        "recommended, affects) VALUES (:t, :p, :r, 'ruleExtraction', 'rules-verifier', 'Keep it?', 'lowConfidence', "
        "'high', '{\"key\": \"keep\", \"label\": \"Keep\"}', '[\"RULE-003\"]')",
        t=world.tenant_a, p=project_id, r=run_id,
    )  # fmt: skip
    await execute(owner_engine, "UPDATE migration_plan SET waves = '[[\"US-002\"], [\"US-001\"], [\"US-003\"]]' "
                  "WHERE project_id = :p", p=project_id)  # fmt: skip
    headers = sign_in(api, world.a_user)
    check = api.get(f"/api/v1/projects/{project_id}/c1-check").json()
    assert check["canApprove"] is False
    text = " ".join(check["blockers"])
    for reason in ("US-001 has invalid Gherkin", "US-002 has no acceptance criteria", "US-003 has open questions",
                   "hard dependency"):  # fmt: skip
        assert reason in text
    blocked = api.post(f"/api/v1/projects/{project_id}/runs/{run_id}/gates/C1:approve", json={}, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "c1_blocked"

    base = f"/api/v1/projects/{project_id}/stories"
    for key in ("US-001", "US-002"):
        story = next(s for s in api.get(base).json() if s["key"] == key)
        assert api.put(f"{base}/{key}", json=body(title=story["title"], links=story["links"]),
                       headers=headers).status_code == 200  # fmt: skip
    await execute(owner_engine, "UPDATE question SET status = 'cancelled' WHERE project_id = :p", p=project_id)
    assert api.post(f"/api/v1/projects/{project_id}/plan:reset", headers=headers).status_code == 200
    assert api.get(f"/api/v1/projects/{project_id}/c1-check").json() == {"canApprove": True, "blockers": []}
    approved = api.post(f"/api/v1/projects/{project_id}/runs/{run_id}/gates/C1:approve", json={}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert {s["status"] for s in api.get(base).json()} == {"approved"}
