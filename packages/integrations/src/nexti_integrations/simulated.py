"""Simulated Jira and Azure DevOps with state (ADR-0019), for the tests, the acceptance and the local demo: they answer
the same REST calls the clients make, keep the items they create, and refuse a wrong credential. Mount them with
`httpx.MockTransport(server.handle)`. They never touch the network."""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

JIRA_STATUSES = {"To Do": "new", "In Progress": "indeterminate", "In Review": "indeterminate", "Done": "done"}


def _basic(request: httpx.Request) -> str:
    header = request.headers.get("Authorization", "")
    return base64.b64decode(header.removeprefix("Basic ")).decode() if header.startswith("Basic ") else ""


def _text(adf: Any) -> str:
    if not isinstance(adf, dict):
        return ""
    if "content" not in adf:
        return str(adf.get("text", ""))
    return "".join(_text(c) for c in adf["content"]) + ("\n\n" if adf.get("type") == "paragraph" else "")


@dataclass
class FakeJira:
    """A Jira Cloud project: issues keyed <PROJECT>-<n>, labels, parents, a To Do / In Progress / In Review / Done
    workflow."""

    email: str
    token: str
    project: str = "CARDS"
    issues: dict[str, dict[str, Any]] = field(default_factory=dict)
    writes: int = 0

    def _issue(self, issue_id: str) -> dict[str, Any] | None:
        return self.issues.get(issue_id) or next((i for i in self.issues.values() if i["key"] == issue_id), None)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if _basic(request) != f"{self.email}:{self.token}":
            return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else {}
        if path == "/rest/api/3/myself":
            return httpx.Response(200, json={"displayName": "Integración NexTI", "emailAddress": self.email})
        if path == "/rest/api/3/search/jql":
            label = re.search(r'labels = "([^"]+)"', body.get("jql", ""))
            found = [i for i in self.issues.values() if label and label.group(1) in i["labels"]]
            return httpx.Response(200, json={"issues": [{"id": i["id"], "key": i["key"]} for i in found[:1]]})
        if path == "/rest/api/3/issue" and method == "POST":
            fields = body["fields"]
            if fields["project"]["key"] != self.project:
                return httpx.Response(400, json={"errors": {"project": "valid project is required"}})
            number = len(self.issues) + 1
            issue: dict[str, Any] | None = {"id": str(10000 + number), "key": f"{self.project}-{number}",
                     "summary": fields["summary"],
                     "type": fields["issuetype"]["name"], "description": _text(fields.get("description")),
                     "labels": list(fields.get("labels", [])), "parent": (fields.get("parent") or {}).get("key"),
                     "status": "To Do", "comments": []}  # fmt: skip
            assert issue is not None  # noqa: S101
            self.issues[issue["id"]] = issue
            self.writes += 1
            return httpx.Response(201, json={"id": issue["id"], "key": issue["key"]})
        match = re.fullmatch(r"/rest/api/3/issue/([^/]+)(/transitions|/comment)?", path)
        issue = self._issue(match.group(1)) if match else None
        if match is None or issue is None:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
        if match.group(2) is None and method == "PUT":
            fields = body["fields"]
            issue.update(summary=fields["summary"], description=_text(fields["description"]), labels=fields["labels"])
            self.writes += 1
            return httpx.Response(204)
        if match.group(2) == "/transitions" and method == "GET":
            return httpx.Response(200, json={"transitions": [
                {"id": str(n), "name": name, "to": {"name": name, "statusCategory": {"key": category}}}
                for n, (name, category) in enumerate(JIRA_STATUSES.items(), start=11)]})  # fmt: skip
        if match.group(2) == "/transitions":
            names = list(JIRA_STATUSES)
            issue["status"] = names[int(body["transition"]["id"]) - 11]
            self.writes += 1
            return httpx.Response(204)
        if match.group(2) == "/comment":
            issue["comments"].append(_text(body["body"]).strip())
            self.writes += 1
            return httpx.Response(201, json={"id": str(len(issue["comments"]))})
        return httpx.Response(405)


@dataclass
class FakeAzureDevOps:
    """An Azure DevOps organization with one project on the Agile process."""

    token: str
    project: str = "Card Management"
    base: str = "https://dev.azure.com/andesbank"
    items: dict[int, dict[str, Any]] = field(default_factory=dict)
    writes: int = 0

    def _out(self, item: dict[str, Any]) -> dict[str, Any]:
        return {"id": item["id"], "url": f"{self.base}/_apis/wit/workItems/{item['id']}",
                "_links": {"html": {"href": f"{self.base}/{self.project}/_workitems/edit/{item['id']}"}},
                "fields": {"System.Title": item["title"], "System.State": item["state"]}}  # fmt: skip

    def _apply(self, item: dict[str, Any], patch: list[dict[str, Any]]) -> None:
        for op in patch:
            if op["path"] == "/relations/-":
                item["parent"] = int(op["value"]["url"].rsplit("/", 1)[-1])
            else:
                item[op["path"].removeprefix("/fields/System.").lower()] = op["value"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if _basic(request) != f":{self.token}":
            return httpx.Response(401)
        path, method = request.url.path, request.method
        base_path = httpx.URL(self.base).path.rstrip("/")
        path = path.removeprefix(base_path)
        project = "/" + self.project.replace(" ", "%20")
        raw = request.url.raw_path.decode().split("?")[0].removeprefix(base_path)
        body: Any = json.loads(request.content) if request.content else {}
        if path == "/_apis/connectionData":
            return httpx.Response(200, json={"authenticatedUser": {"providerDisplayName": "Integración NexTI"}})
        if raw.startswith(project + "/_apis/wit/workitems/$") and method == "POST":
            kind = path.split("$", 1)[1]
            item: dict[str, Any] | None = {
                "id": len(self.items) + 1,
                "type": kind,
                "state": "New",
                "comments": [],
                "parent": None,
            }
            assert item is not None  # noqa: S101
            self._apply(item, body)
            self.items[item["id"]] = item
            self.writes += 1
            return httpx.Response(200, json=self._out(item))
        if raw == project + "/_apis/wit/wiql":
            tag = re.search(r"Contains '([^']+)'", body["query"])
            found = [i for i in self.items.values() if tag and tag.group(1) in str(i.get("tags", "")).split("; ")]
            return httpx.Response(200, json={"workItems": [{"id": i["id"]} for i in found[:1]]})
        match = re.fullmatch(r"/_apis/wit/workitems/(\d+)", path)
        if match:
            item = self.items.get(int(match.group(1)))
            if item is None:
                return httpx.Response(404)
            if method == "PATCH":
                self._apply(item, body)
                self.writes += 1
            return httpx.Response(200, json=self._out(item))
        comment = re.fullmatch(re.escape(project) + r"/_apis/wit/workItems/(\d+)/comments", raw)
        if comment and method == "POST":
            self.items[int(comment.group(1))]["comments"].append(body["text"])
            self.writes += 1
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)
