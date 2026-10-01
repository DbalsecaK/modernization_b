"""The backlog in Jira and Azure DevOps (spec 7.6, ADR-0019), against simulated servers that follow their REST APIs:
the approved stories become features, stories and tasks by wave; a re-sync with nothing new writes nothing; an item
written before a crash is found by its label instead of duplicated; verified stories reach Done with the evidence and
a failed check opens a bug."""

import asyncio
import dataclasses
from typing import Any

import httpx
import pytest

from nexti_integrations.azure_devops import AzureDevOpsTracker
from nexti_integrations.backlog import BacklogTracker, Desired, Linked, apply, plan
from nexti_integrations.jira import JiraTracker, TrackerError
from nexti_integrations.simulated import FakeAzureDevOps, FakeJira
from nexti_integrations.spec import StoryItem, VerdictItem, bug_items, desired_items

STORIES = [
    StoryItem("US-001", "Simular la cuota", "Simulación", "Como cliente quiero simular.",
              ("Escenario: Cuota\n  Dado un monto\n  Cuando simulo\n  Entonces veo la cuota",),
              ("RULE-001", "RULE-002", "SCR-SIMULADOR"), "approved"),
    StoryItem("US-002", "Guardar la simulación", "Auditoría", "Como oficial quiero auditar.",
              ("Escenario: Se guarda\n  Dado una simulación\n  Cuando simulo\n  Entonces queda guardada",),
              ("RULE-003",), "approved"),
    StoryItem("US-003", "Exportar a PDF", "Simulación", "Como cliente quiero un PDF.", (), ("SCR-RESULTADO",),
              "review"),
]  # fmt: skip
WAVES = [["US-001"], ["US-002", "US-003"]]
NAMES = {"RULE-001": "Monto dentro del rango", "RULE-002": "Tasa según el plazo", "RULE-003": "Guardar"}


def jira_tracker(server: FakeJira, http: httpx.AsyncClient) -> BacklogTracker:
    return JiraTracker(http, "https://andesbank.atlassian.net", server.email, server.token, server.project)


def ado_tracker(server: FakeAzureDevOps, http: httpx.AsyncClient) -> BacklogTracker:
    return AzureDevOpsTracker(http, server.base, server.token, server.project)


async def sync(tracker: BacklogTracker, desired: list[Desired], linked: dict[str, Linked]) -> dict[str, Linked]:
    recorded: list[tuple[str, str]] = []

    async def record(op: str, item: Desired, link: Linked) -> None:
        recorded.append((op, item.element))

    outcome = await apply(tracker, plan(desired, linked), linked, record)
    return outcome.links


def test_only_approved_stories_enter_with_their_features_tasks_and_wave() -> None:
    items = {d.element: d for d in desired_items(STORIES, WAVES, NAMES)}
    assert [e for e in items if e.startswith("feature:")] == ["feature:simulacion", "feature:auditoria"]
    assert "story:US-003" not in items  # not approved
    story = items["story:US-001"]
    assert (story.parent, story.labels) == ("feature:simulacion", ("nexti", "wave-1"))
    assert "Escenario: Cuota" in story.description
    assert items["story:US-002"].labels == ("nexti", "wave-2")
    assert items["task:US-001:RULE-001"].title == "RULE-001 Monto dentro del rango"
    assert items["task:US-001:RULE-001"].parent == "story:US-001"


@pytest.mark.parametrize("system", ["jira", "azure_devops"])
def test_c1_creates_the_hierarchy_and_a_resync_writes_nothing(system: str) -> None:
    server: Any = FakeJira("ops@andesbank.example", "jira-token-1") if system == "jira" else FakeAzureDevOps("pat-1")

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle)) as http:
            tracker = jira_tracker(server, http) if system == "jira" else ado_tracker(server, http)
            desired = desired_items(STORIES, WAVES, NAMES)
            links = await sync(tracker, desired, {})
            first = server.writes
            assert len(links) == len(desired) == 2 + 2 + 4  # features, stories, tasks
            assert await sync(tracker, desired, links) == links
            assert server.writes == first  # nothing new: nothing written
            assert plan(desired, links) == []

    asyncio.run(go())
    store = server.issues if system == "jira" else server.items
    assert len(store) == 8
    if system == "jira":
        story = next(i for i in server.issues.values() if i["summary"].startswith("US-001"))
        epic = next(i for i in server.issues.values() if i["summary"] == "Simulación")
        assert (story["type"], story["parent"], epic["type"]) == ("Story", epic["key"], "Epic")
        assert "wave-1" in story["labels"]
    else:
        story = next(i for i in server.items.values() if i["title"].startswith("US-001"))
        feature = next(i for i in server.items.values() if i["title"] == "Simulación")
        assert (story["type"], story["parent"], feature["type"]) == ("User Story", feature["id"], "Feature")


@pytest.mark.parametrize("system", ["jira", "azure_devops"])
def test_an_item_written_before_a_crash_is_found_by_its_label(system: str) -> None:
    server: Any = FakeJira("ops@andesbank.example", "jira-token-1") if system == "jira" else FakeAzureDevOps("pat-1")

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle)) as http:
            tracker = jira_tracker(server, http) if system == "jira" else ado_tracker(server, http)
            desired = desired_items(STORIES, WAVES, NAMES)
            links = await sync(tracker, desired, {})
            lost = {k: v for k, v in links.items() if k != "story:US-002" and not k.startswith("task:US-002")}
            again = await sync(tracker, desired, lost)  # the link of US-002 was never saved
            assert again["story:US-002"].external_id == links["story:US-002"].external_id

    asyncio.run(go())
    assert len(server.issues if system == "jira" else server.items) == 8


@pytest.mark.parametrize("system", ["jira", "azure_devops"])
def test_verified_stories_reach_done_with_the_evidence_and_a_failed_check_opens_a_bug(system: str) -> None:
    server: Any = FakeJira("ops@andesbank.example", "jira-token-1") if system == "jira" else FakeAzureDevOps("pat-1")
    verdicts = [
        VerdictItem("loans", "NOT PROVEN", (("tests_ran", "Tests ran", "failed", "1 test(s) failed of 20"),
                                            ("criteria_covered", "Criteria covered", "passed", "6 criteria")),
                    "proof/pack.zip", frozenset({"RULE-003"}), {"tests_ran": ("RULE-001",)}),
        VerdictItem("frontend-react", "PROVEN", (("compiles", "Compiles", "passed", "ok"),), "proof/front.zip"),
    ]  # fmt: skip

    async def go() -> dict[str, Linked]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle)) as http:
            tracker = jira_tracker(server, http) if system == "jira" else ado_tracker(server, http)
            links = await sync(tracker, desired_items(STORIES, WAVES, NAMES), {})
            later = desired_items(STORIES, WAVES, NAMES, verdicts) + bug_items(verdicts)
            return await sync(tracker, later, links)

    links = asyncio.run(go())
    assert links["story:US-002"].state == "done"  # RULE-003 verified
    assert links["story:US-001"].state == "open"  # RULE-001 failed
    assert links["task:US-001:SCR-SIMULADOR"].state == "done"  # the frontend passed
    assert links["bug:loans:tests_ran"].state == "open"
    if system == "jira":
        done = next(i for i in server.issues.values() if i["summary"].startswith("US-002"))
        bug = next(i for i in server.issues.values() if i["type"] == "Bug")
        assert done["status"] == "Done"
        assert "Verified by the platform" in done["comments"][0]
        assert "Obtained: 1 test(s) failed of 20" in bug["description"]
    else:
        done = next(i for i in server.items.values() if i["title"].startswith("US-002"))
        assert done["state"] == "Closed"


def test_a_wrong_credential_is_refused_without_saying_it() -> None:
    server = FakeJira("ops@andesbank.example", "jira-token-1")

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle)) as http:
            tracker = JiraTracker(http, "https://andesbank.atlassian.net", server.email, "wrong-token", "CARDS")
            with pytest.raises(TrackerError) as refused:
                await tracker.whoami()
            assert "wrong-token" not in str(refused.value)
            assert await jira_tracker(server, http).whoami() == "Integración NexTI"

    asyncio.run(go())


def test_a_story_discarded_after_c1_is_marked_not_deleted() -> None:
    linked = frozenset({"story:US-002"})
    gone = [STORIES[0], dataclasses.replace(STORIES[1], status="discarded")]
    items = {d.element: d for d in desired_items(gone, WAVES, NAMES, linked=linked)}
    assert items["story:US-002"].state == "discarded"
    assert "task:US-002:RULE-003" not in items
