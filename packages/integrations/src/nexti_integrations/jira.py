"""Jira Cloud through its REST API v3 (spec 7.6, ADR-0019): basic authentication with the e-mail and an API token of the
tenant's integration. Descriptions and comments go as Atlassian Document Format; an item is found again by its label
(JQL search). The base URL comes from the integration, so tests point it to a simulated Jira."""

import base64
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx

from nexti_integrations.backlog import Created, ItemKind, State

TYPES: dict[str, str] = {"feature": "Epic", "story": "Story", "task": "Subtask", "bug": "Bug"}
# The status category a state reaches; review is a status whose name says so (a workflow may not have one).
TARGETS: dict[State, tuple[str, ...]] = {"done": ("done",), "discarded": ("done",), "open": ("new", "indeterminate"),
                                         "review": ("review",)}  # fmt: skip


class TrackerError(RuntimeError):
    """The external system refused or failed: said in the platform, never with the credential."""


def adf(text: str) -> dict[str, Any]:
    """Plain text as an Atlassian Document Format document: one paragraph per block."""
    blocks = [b for b in text.split("\n\n") if b.strip()] or [""]
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": block}] if block else []} for block in blocks
    ]}  # fmt: skip


class JiraTracker:
    system: Literal["jira"] = "jira"

    def __init__(self, http: httpx.AsyncClient, site: str, email: str, token: str, project: str,
                 types: Mapping[str, str] | None = None) -> None:  # fmt: skip
        self.http = http
        self.base = site.rstrip("/")
        self.project = project
        self.types: dict[str, str] = {**TYPES, **(types or {})}
        credential = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {credential}", "Accept": "application/json"}

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.http.request(method, f"{self.base}{path}", headers=self.headers, timeout=30,
                                               **kwargs)  # fmt: skip
        except httpx.HTTPError as exc:
            raise TrackerError(f"Jira could not be reached: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise TrackerError("Jira refused the credential of the integration")
        if response.status_code >= 400:
            raise TrackerError(f"Jira answered {response.status_code} to {method} {path.split('?')[0]}")
        return response.json() if response.content else None

    def _created(self, data: Mapping[str, Any]) -> Created:
        key = str(data["key"])
        return Created(str(data["id"]), key, f"{self.base}/browse/{key}")

    async def whoami(self) -> str:
        data = await self._call("GET", "/rest/api/3/myself")
        return str(data.get("displayName") or data.get("emailAddress") or "")

    async def find(self, label: str) -> Created | None:
        query = {"jql": f'project = "{self.project}" AND labels = "{label}"', "fields": ["summary"], "maxResults": 1}
        data = await self._call("POST", "/rest/api/3/search/jql", json=query)
        issues = data.get("issues") or []
        return self._created(issues[0]) if issues else None

    async def create(self, kind: ItemKind, title: str, description: str, parent: Created | None,
                     labels: Sequence[str]) -> Created:  # fmt: skip
        fields: dict[str, Any] = {
            "project": {"key": self.project}, "summary": title[:255], "issuetype": {"name": self.types[kind]},
            "description": adf(description), "labels": list(labels),
        }  # fmt: skip
        if parent is not None:
            fields["parent"] = {"key": parent.external_key}
        data = await self._call("POST", "/rest/api/3/issue", json={"fields": fields})
        return self._created(data)

    async def update(self, item: Created, title: str, description: str, labels: Sequence[str]) -> None:
        await self._call("PUT", f"/rest/api/3/issue/{item.external_id}", json={"fields": {
            "summary": title[:255], "description": adf(description), "labels": list(labels)}})  # fmt: skip

    async def transition(self, item: Created, state: State) -> None:
        data = await self._call("GET", f"/rest/api/3/issue/{item.external_id}/transitions")
        wanted = TARGETS[state]
        options = data.get("transitions") or []
        chosen = next((t for t in options if state == "review" and "review" in str(t.get("name", "")).lower()), None)
        chosen = chosen or next((t for t in options if t.get("to", {}).get("statusCategory", {}).get("key") in wanted
                                 and state != "review"), None)  # fmt: skip
        if chosen is None:
            return  # the workflow has no such status: the comment says it
        await self._call("POST", f"/rest/api/3/issue/{item.external_id}/transitions",
                         json={"transition": {"id": chosen["id"]}})  # fmt: skip

    async def comment(self, item: Created, text: str) -> None:
        await self._call("POST", f"/rest/api/3/issue/{item.external_id}/comment", json={"body": adf(text)})
