"""Acceptance of M7b (plan section 3, ADR-0019), with a Jira and an Azure DevOps project simulated with state (they
answer the public REST APIs the clients call):

1. Approving C1 through the API queues the sync; the worker's job creates the expected hierarchy (features, the
   approved stories with their Gherkin and a task per linked rule, by wave). Syncing again writes nothing, and every
   external write is in the audit log.
2. A failed test opens a bug: the verdict of a generated project whose service was broken has a failed check; the
   sync opens the bug, the developer agent proposes a correction in the Java sandbox, the tests pass with it and the
   bug ends in review, waiting for a person.

The developer's answer is recorded (ADR-0012): NEXTI_RECORD_M7B=1 calls OpenRouter (OPENROUTER_API_KEY_FOR_TESTS)."""

import hashlib
import io
import json
import os
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.secrets import SecretsConfig, SecretStore, integration_path
from nexti_integrations.azure_devops import AzureDevOpsTracker
from nexti_integrations.backlog import BacklogTracker
from nexti_integrations.jira import JiraTracker
from nexti_integrations.simulated import FakeAzureDevOps, FakeJira
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_pack_spring_boot import Design
from nexti_pack_spring_boot.build import IMAGE as JAVA_IMAGE
from nexti_pack_spring_boot.pack import PACK, wiring
from nexti_sandbox import DockerSandbox
from nexti_worker.backlog import Link, sync_backlog
from nexti_worker.bugfix import fix_bugs

from .conftest import SETTINGS, World
from .run_support import TARGET, execute, fetch, make_config, make_project, make_run, seed_spec
from .test_acceptance_m4 import _api_key, _image, model_for, object_store, spending_cap
from .test_runs_api import grant, sign_in, waiting_at

RECORDINGS = Path(__file__).parent / "recordings" / "m7b"
REFERENCE = Path(__file__).resolve().parents[4] / "packages/packs/target/spring_boot/tests/fixtures/pago_orden"
RECORD = os.environ.get("NEXTI_RECORD_M7B") == "1"
BUDGET_USD = Decimal("1.00")
JIRA = FakeJira("ops@andesbank.example", "jira-token-acceptance")
ADO = FakeAzureDevOps("ado-pat-acceptance")


@pytest.fixture
def api(api_settings: Settings) -> Any:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def trackers(server: Any) -> Any:
    """The real clients on a transport that answers like the simulated system."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(server.handle))

    def build(link: Link, token: str) -> BacklogTracker:
        if link.kind == "jira":
            return JiraTracker(http, link.config["site"], link.config["email"], token, link.external_project)
        return AzureDevOpsTracker(http, link.config["organization"], token, link.external_project)

    return build


async def integration(owner: AsyncEngine, tenant_id: uuid.UUID, kind: str) -> uuid.UUID:
    """A Jira or Azure DevOps integration of the tenant, its token in OpenBao."""
    integration_id = uuid.uuid4()
    path = integration_path(tenant_id, integration_id)
    token = JIRA.token if kind == "jira" else ADO.token
    config = ({"site": "https://andesbank.atlassian.net", "email": JIRA.email} if kind == "jira"
              else {"organization": ADO.base})  # fmt: skip
    async with httpx.AsyncClient(timeout=10) as http:
        await SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http).put(
            path, token)  # fmt: skip
    await execute(owner, "INSERT INTO tenant_integration (id, tenant_id, kind, name, vault_path, config, status) "
                         "VALUES (:i, :t, :k, :n, :v, CAST(:c AS jsonb), 'ok')",
                  i=integration_id, t=tenant_id, k=kind, n=f"{kind} {integration_id.hex[:6]}", v=path,
                  c=json.dumps(config))  # fmt: skip
    return integration_id


def secrets(http: httpx.AsyncClient) -> SecretStore:
    return SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http)


@pytest.mark.parametrize("kind", ["jira", "azure_devops"])
async def test_approving_c1_creates_the_hierarchy_without_duplicates(
    kind: Literal["jira", "azure_devops"], api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine,
    fga: OpenFga, world: World,
) -> None:  # fmt: skip
    server: Any = JIRA if kind == "jira" else ADO
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id)
    await seed_spec(owner_engine, world.tenant_a, project_id)
    await grant(owner_engine, world, world.a_user, "projectOwner", project_id)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    integration_id = await integration(owner_engine, world.tenant_a, kind)
    external = "CARDS" if kind == "jira" else ADO.project
    body = {"integrationId": str(integration_id), "externalProject": external}
    linked = api.put(f"/api/v1/projects/{project_id}/backlog", json=body, headers=headers)
    assert linked.status_code == 200, linked.text
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    await waiting_at(owner_engine, run_id, "C1", world.tenant_a)

    approved = api.post(f"/api/v1/projects/{project_id}/runs/{run_id}/gates/C1:approve", json={}, headers=headers)
    assert approved.status_code == 200, approved.text
    (job,) = await fetch(owner_engine, "SELECT args FROM procrastinate_jobs WHERE task_name = 'nexti:sync_backlog' "
                                       "AND args->>'project_id' = :p", p=str(project_id))  # fmt: skip
    assert job["args"]["reason"] == "C1"

    before = server.writes
    async with httpx.AsyncClient(timeout=10) as http:
        build = trackers(server)
        first = await sync_backlog(app_engine, object_store(), secrets(http), build, world.tenant_a, project_id, "C1")
        writes = server.writes - before
        again = await sync_backlog(app_engine, object_store(), secrets(http), build, world.tenant_a, project_id, "C1")
    assert first.startswith("7 created"), first  # the feature "General", 3 stories, a task per linked rule
    assert again.startswith("0 created, 0 updated, 0 moved"), again
    assert server.writes - before == writes  # the second sync wrote nothing

    items = {i["element"]: i for i in api.get(f"/api/v1/projects/{project_id}/backlog").json()["items"]}
    assert {e.split(":")[0] for e in items} == {"feature", "story", "task"}
    assert {e for e in items if e.startswith("story:")} == {"story:US-001", "story:US-002", "story:US-003"}
    assert all(i["externalKey"] for i in items.values())
    if kind == "jira":
        story = next(i for i in JIRA.issues.values() if i["summary"].startswith("US-002"))
        assert story["type"] == "Story"
        assert "wave-2" in story["labels"]
        assert "Scenario: Pay" in story["description"]
    audited = await fetch(owner_engine, "SELECT count(*) AS n FROM audit_log WHERE action = 'backlog.create' "
                                        "AND target = :t", t=f"project:{project_id}")  # fmt: skip
    assert audited[0]["n"] == len(items)


def broken_project(design: Design) -> dict[str, str]:
    """The reference target of the fictitious application with one line of its service broken: the overdraft limit."""
    files = PACK.skeleton(design)
    path, content = wiring(design)
    files[path] = content
    use_case = design.use_cases[0]
    service = (REFERENCE / "PayOrderService.java").read_text(encoding="utf-8")
    files[PACK.service_path(design, use_case)] = service.replace('new BigDecimal("100.00")', 'new BigDecimal("10.00")')
    files[PACK.test_path(design, use_case)] = (REFERENCE / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        reference = REFERENCE / f"Jdbc{port.name}.java"
        if reference.exists():
            files[PACK.adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


async def store_generated(owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID,
                          files: dict[str, str]) -> None:  # fmt: skip
    store = object_store()
    for path, content in files.items():
        key = f"tenants/{tenant_id}/projects/{project_id}/runs/{run_id}/files/{path}"
        data = content.encode("utf-8")
        await store.put(key, io.BytesIO(data), len(data), "text/plain; charset=utf-8")
        await execute(owner, "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, "
                             "sha256, size_bytes, rules) VALUES (:t, :p, :r, 'domain', :path, :k, :h, :s, '[]')",
                      t=tenant_id, p=project_id, r=run_id, path=path, k=key, h=hashlib.sha256(data).hexdigest(),
                      s=len(data))  # fmt: skip


async def test_a_failed_test_opens_a_bug_and_the_cycle_ends_in_human_review(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    if not _image(JAVA_IMAGE):
        pytest.skip(f"Docker or the image {JAVA_IMAGE} is not available")
    if RECORD and not _api_key():
        pytest.skip("recording needs OPENROUTER_API_KEY_FOR_TESTS")
    if not RECORD and not any((RECORDINGS / "models").glob("*.json")):
        pytest.skip("nothing recorded yet: run once with NEXTI_RECORD_M7B=1")
    mode: Literal["record", "replay"] = "record" if RECORD else "replay"
    design = Design.model_validate_json((REFERENCE / "design.json").read_text(encoding="utf-8"))
    project_id = await make_project(owner_engine, world.tenant_a)
    version = await make_config(owner_engine, world.tenant_a, project_id, target={**TARGET, "frontend": "none"})
    run_id = await make_run(owner_engine, world.tenant_a, project_id, version, kind="pipeline")
    files = {"design/design.json": design.model_dump_json(indent=2), **broken_project(design)}
    await store_generated(owner_engine, world.tenant_a, project_id, run_id, files)
    # The verdict the verification saved: the tests failed (the overdraft limit), with its trace.
    pack = io.BytesIO()
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("TRACE.json", json.dumps([{"rule": "RULE-007", "verified": False}]))
    proof_key = f"tenants/{world.tenant_a}/projects/{project_id}/runs/{run_id}/verification/PayOrder/proof-pack.zip"
    await object_store().put(proof_key, io.BytesIO(pack.getvalue()), len(pack.getvalue()), "application/zip")
    failure = "1 test(s) failed of 7: a_virtual_account_cannot_overdraw_but_others_can_up_to_100"
    checks = [{"key": "tests_ran", "title": "Tests ran", "status": "failed", "detail": failure}]
    await execute(owner_engine, "INSERT INTO verdict (tenant_id, project_id, run_id, module, verdict, checks, "
                                "not_proven, proof_pack_key) VALUES (:t, :p, :r, 'PayOrder', 'NOT PROVEN', "
                                "CAST(:c AS jsonb), '[]', :k)",
                  t=world.tenant_a, p=project_id, r=run_id, c=json.dumps(checks), k=proof_key)  # fmt: skip
    integration_id = await integration(owner_engine, world.tenant_a, "jira")
    await execute(owner_engine, "INSERT INTO project_backlog (tenant_id, project_id, integration_id, "
                                "external_project) VALUES (:t, :p, :i, 'CARDS')",
                  t=world.tenant_a, p=project_id, i=integration_id)  # fmt: skip

    async with httpx.AsyncClient(timeout=120) as http:
        keys = GatewaySecrets(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        gateway = GatewayService(app_engine, http, keys, cassettes=(RECORDINGS / "models", mode))
        path = await model_for(owner_engine, gateway, world.tenant_a, project_id, live=RECORD)
        cap = await spending_cap(owner_engine, world.tenant_a, project_id, BUDGET_USD) if RECORD else None
        build = trackers(JIRA)

        async def fixer(tracker: BacklogTracker, link: Link) -> str:
            return await fix_bugs(app_engine, object_store(), gateway, lambda image: DockerSandbox(image=image),
                                  tracker, world.tenant_a, project_id, link.integration_id)  # fmt: skip

        try:
            summary = await sync_backlog(app_engine, object_store(), secrets(http), build, world.tenant_a,
                                         project_id, "verdict PayOrder", fixer)  # fmt: skip
        finally:
            await gateway.delete_credential(path)
            if cap is not None:
                await execute(owner_engine, "DELETE FROM budget WHERE id = :b", b=cap)

    print(summary)
    assert "1 created" in summary, summary
    assert "in review" in summary, summary
    (link,) = await fetch(owner_engine, "SELECT external_key, state FROM work_item_link WHERE project_id = :p "
                                        "AND kind = 'bug'", p=project_id)  # fmt: skip
    assert link["state"] == "review"
    bug = next(i for i in JIRA.issues.values() if i["key"] == link["external_key"])
    assert (bug["type"], bug["status"]) == ("Bug", "In Review")
    assert "Obtained: 1 test(s) failed of 7" in bug["description"]
    assert any("a person reviews it" in c for c in bug["comments"])
    fixes = await fetch(owner_engine, "SELECT status, files_key FROM bug_fix WHERE project_id = :p "
                                      "ORDER BY iteration", p=project_id)  # fmt: skip
    assert fixes[-1]["status"] == "proposed"
    assert fixes[-1]["files_key"]
    actions = {r["action"] for r in await fetch(owner_engine, "SELECT action FROM audit_log WHERE target = :t",
                                                 t=f"project:{project_id}")}  # fmt: skip
    assert {"backlog.create", "backlog.bug_in_review"} <= actions
