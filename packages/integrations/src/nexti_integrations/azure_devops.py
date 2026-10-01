"""Azure DevOps Boards through the Work Item Tracking REST API 7.1 (spec 7.6, ADR-0019): basic authentication with a
personal access token of the tenant's integration. Work items are created and updated with JSON Patch, parents are
hierarchy links, tags carry the labels and WIQL finds an item again by its tag. The organization URL comes from the
integration, so tests point it to a simulated Azure DevOps."""

import base64
import html
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import quote

import httpx

from nexti_integrations.backlog import Created, ItemKind, State
from nexti_integrations.jira import TrackerError

API = "api-version=7.1"
TYPES: dict[str, str] = {"feature": "Feature", "story": "User Story", "task": "Task", "bug": "Bug"}
# The states of the Agile process; a project on another process sets its own in the link.
STATES: dict[str, str] = {"open": "New", "review": "Resolved", "done": "Closed", "discarded": "Removed"}


def _html(text: str) -> str:
    return "".join(f"<p>{html.escape(block)}</p>" for block in text.split("\n\n") if block.strip())


class AzureDevOpsTracker:
    system: Literal["azure_devops"] = "azure_devops"

    def __init__(self, http: httpx.AsyncClient, organization: str, token: str, project: str,
                 types: Mapping[str, str] | None = None, states: Mapping[str, str] | None = None) -> None:  # fmt: skip
        self.http = http
        self.base = organization.rstrip("/")
        self.project = project
        self.types: dict[str, str] = {**TYPES, **(types or {})}
        self.states: dict[str, str] = {**STATES, **(states or {})}
        credential = base64.b64encode(f":{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {credential}", "Accept": "application/json"}

    async def _call(self, method: str, path: str, *, patch: list[dict[str, Any]] | None = None,
                    body: dict[str, Any] | None = None) -> Any:  # fmt: skip
        headers = dict(self.headers)
        kwargs: dict[str, Any] = {}
        if patch is not None:
            headers["Content-Type"] = "application/json-patch+json"
            kwargs["content"] = json.dumps(patch).encode("utf-8")
        elif body is not None:
            kwargs["json"] = body
        try:
            response = await self.http.request(method, f"{self.base}{path}", headers=headers, timeout=30, **kwargs)
        except httpx.HTTPError as exc:
            raise TrackerError(f"Azure DevOps could not be reached: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise TrackerError("Azure DevOps refused the credential of the integration")
        if response.status_code >= 400:
            raise TrackerError(f"Azure DevOps answered {response.status_code} to {method} {path.split('?')[0]}")
        return response.json() if response.content else None

    def _project(self) -> str:
        return quote(self.project, safe="")

    def _created(self, data: Mapping[str, Any]) -> Created:
        item_id = str(data["id"])
        url = str((data.get("_links") or {}).get("html", {}).get("href") or data.get("url") or "")
        return Created(item_id, item_id, url)

    async def whoami(self) -> str:
        data = await self._call("GET", f"/_apis/connectionData?{API}")
        user = data.get("authenticatedUser") or {}
        return str(user.get("providerDisplayName") or user.get("customDisplayName") or "")

    async def find(self, label: str) -> Created | None:
        # WIQL, not SQL: the label is ours (nexti-<element>, letters, digits, - and _ only).
        query = ("Select [System.Id] From WorkItems Where [System.TeamProject] = @project "  # noqa: S608
                 f"And [System.Tags] Contains '{label}'")  # fmt: skip
        data = await self._call("POST", f"/{self._project()}/_apis/wit/wiql?{API}", body={"query": query})
        items = data.get("workItems") or []
        if not items:
            return None
        found = await self._call("GET", f"/_apis/wit/workitems/{items[0]['id']}?{API}")
        return self._created(found)

    async def create(self, kind: ItemKind, title: str, description: str, parent: Created | None,
                     labels: Sequence[str]) -> Created:  # fmt: skip
        patch: list[dict[str, Any]] = [
            {"op": "add", "path": "/fields/System.Title", "value": title[:255]},
            {"op": "add", "path": "/fields/System.Description", "value": _html(description)},
            {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(labels)},
        ]
        if parent is not None:
            patch.append({"op": "add", "path": "/relations/-", "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": f"{self.base}/_apis/wit/workItems/{parent.external_id}"}})  # fmt: skip
        kind_name = quote(self.types[kind], safe="")
        data = await self._call("POST", f"/{self._project()}/_apis/wit/workitems/${kind_name}?{API}", patch=patch)
        return self._created(data)

    async def update(self, item: Created, title: str, description: str, labels: Sequence[str]) -> None:
        await self._call("PATCH", f"/_apis/wit/workitems/{item.external_id}?{API}", patch=[
            {"op": "add", "path": "/fields/System.Title", "value": title[:255]},
            {"op": "add", "path": "/fields/System.Description", "value": _html(description)},
            {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(labels)},
        ])  # fmt: skip

    async def transition(self, item: Created, state: State) -> None:
        await self._call("PATCH", f"/_apis/wit/workitems/{item.external_id}?{API}", patch=[
            {"op": "add", "path": "/fields/System.State", "value": self.states[state]}])  # fmt: skip

    async def comment(self, item: Created, text: str) -> None:
        await self._call("POST", f"/{self._project()}/_apis/wit/workItems/{item.external_id}/comments"
                                 "?api-version=7.1-preview.4", body={"text": _html(text)})  # fmt: skip
