"""The sync of a project's backlog with Jira or Azure DevOps (spec 7.6, ADR-0019), a job of the worker: after C1, after
each verdict and when a person asks. It reads what the platform knows (the approved stories and the plan, the names of
rules and screens, the newest verdicts and their traces, the bug cycle), plans the actions with code and runs them;
every external write is linked (`work_item_link`) and audited before the next one. The credential is read from the
secrets store for the job and never kept."""

import io
import json
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexti_core.audit import AuditEvent, record
from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore
from nexti_core.secrets import SecretStore
from nexti_integrations.azure_devops import AzureDevOpsTracker
from nexti_integrations.backlog import BacklogTracker, Desired, Linked, State, apply, plan
from nexti_integrations.jira import JiraTracker, TrackerError
from nexti_integrations.spec import StoryItem, VerdictItem, bug_items, desired_items

ACTOR = "backlog-sync"


@dataclass(frozen=True)
class Link:
    integration_id: uuid.UUID
    kind: str
    config: dict[str, Any]
    vault_path: str | None
    external_project: str
    types: dict[str, str]
    states: dict[str, str]
    rules: dict[str, bool]


TrackerFactory = Callable[[Link, str], BacklogTracker]
# The bug cycle (bugfix.fix_bugs) for the open bugs of a linked project, when the worker has the models and sandboxes.
Fixer = Callable[[BacklogTracker, Link], Awaitable[str]]


def tracker_for(http: httpx.AsyncClient) -> TrackerFactory:
    """The real clients, on the runtime's HTTP client."""

    def build(link: Link, token: str) -> BacklogTracker:
        if link.kind == "jira":
            return JiraTracker(http, link.config.get("site", ""), link.config.get("email", ""), token,
                               link.external_project, link.types)  # fmt: skip
        return AzureDevOpsTracker(http, link.config.get("organization", ""), token, link.external_project, link.types,
                                  link.states)  # fmt: skip

    return build


def _db(engine: AsyncEngine, tenant_id: uuid.UUID) -> Any:
    return scoped_connection(engine, DbScope(tenant_id=tenant_id))


async def load_link(engine: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID) -> Link | None:
    async with _db(engine, tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT b.*, i.kind, i.config, i.vault_path FROM project_backlog b JOIN tenant_integration i "
                     "ON i.id = b.integration_id WHERE b.project_id = :p"), {"p": project_id})
        ).mappings().first()  # fmt: skip
    if row is None:
        return None
    rules = {k: bool(v) for k, v in dict(row["rules"]).items()}
    return Link(row["integration_id"], row["kind"], dict(row["config"]), row["vault_path"], row["external_project"],
                dict(row["types"]), dict(row["states"]), rules)  # fmt: skip


async def _stories(conn: AsyncConnection, project_id: uuid.UUID) -> list[StoryItem]:
    rows = (
        await conn.execute(
            text("SELECT DISTINCT ON (s.key) s.key, v.title, v.feature, v.narrative, v.criteria, v.links, v.status "
                 "FROM user_story s JOIN user_story_version v ON v.story_id = s.id WHERE s.project_id = :p "
                 "ORDER BY s.key, v.version DESC"), {"p": project_id})
    ).mappings().all()  # fmt: skip
    return [StoryItem(r["key"], r["title"], r["feature"] or "", r["narrative"] or "", tuple(r["criteria"]),
                      tuple(r["links"]), r["status"]) for r in rows]  # fmt: skip


async def _names(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, str]:
    rows = (
        await conn.execute(
            text("SELECT DISTINCT ON (key) key, data FROM spec_element WHERE project_id = :p "
                 "AND element_type IN ('rule', 'screen') ORDER BY key, version DESC"), {"p": project_id})
    ).mappings().all()  # fmt: skip
    return {r["key"]: str(r["data"].get("name", "")) for r in rows}


async def _verdicts(conn: AsyncConnection, objects: ObjectStore | None, project_id: uuid.UUID) -> list[VerdictItem]:
    """The newest verdict of each module, with the rules its trace verified and the rules behind each failed check."""
    rows = (
        await conn.execute(
            text("SELECT DISTINCT ON (module) module, verdict, checks, proof_pack_key FROM verdict "
                 "WHERE project_id = :p ORDER BY module, created_at DESC"), {"p": project_id})
    ).mappings().all()  # fmt: skip
    found: list[VerdictItem] = []
    for row in rows:
        verified: set[str] = set()
        unverified: list[str] = []
        if objects is not None and row["proof_pack_key"] and not row["module"].startswith("frontend-"):
            data = b"".join(await objects.read(row["proof_pack_key"]))
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "TRACE.json" in archive.namelist():
                    for trace in json.loads(archive.read("TRACE.json")):
                        if trace.get("verified"):
                            verified.add(trace["rule"])
                        else:
                            unverified.append(trace["rule"])
        checks = tuple((c["key"], c.get("title", c["key"]), c["status"], c.get("detail", "")) for c in row["checks"])
        failed = {c[0]: tuple(unverified) for c in checks if c[2] == "failed"}
        found.append(VerdictItem(row["module"], row["verdict"], checks, row["proof_pack_key"] or "",
                                 frozenset(verified), failed))  # fmt: skip
    return found


async def _linked(conn: AsyncConnection, project_id: uuid.UUID, integration_id: uuid.UUID) -> dict[str, Linked]:
    rows = (
        await conn.execute(
            text("SELECT element, external_id, external_key, url, digest, state FROM work_item_link "
                 "WHERE project_id = :p AND integration_id = :i"), {"p": project_id, "i": integration_id})
    ).mappings().all()  # fmt: skip
    return {r["element"]: Linked(r["element"], r["external_id"], r["external_key"], r["url"], r["digest"],
                                 r["state"]) for r in rows}  # fmt: skip


async def desired_backlog(engine: AsyncEngine, objects: ObjectStore | None, tenant_id: uuid.UUID,
                          project_id: uuid.UUID, link: Link) -> tuple[list[Desired], dict[str, Linked]]:  # fmt: skip
    async with _db(engine, tenant_id) as conn:
        stories = await _stories(conn, project_id)
        plan_row = (
            await conn.execute(text("SELECT waves FROM migration_plan WHERE project_id = :p ORDER BY version DESC "
                                    "LIMIT 1"), {"p": project_id})
        ).scalar_one_or_none()  # fmt: skip
        names = await _names(conn, project_id)
        verdicts = await _verdicts(conn, objects, project_id)
        linked = await _linked(conn, project_id, link.integration_id)
    rules = {"createFromSpec": True, "markDone": True, "bugOnFailure": True, **link.rules}
    desired: list[Desired] = []
    if rules["createFromSpec"] or any(e.startswith("story:") for e in linked):
        items = desired_items(stories, list(plan_row or []), names, verdicts if rules["markDone"] else (),
                              frozenset(linked))  # fmt: skip
        desired += [d for d in items if rules["createFromSpec"] or d.element in linked]
    if rules["bugOnFailure"]:
        states: dict[str, State] = {e: link_.state for e, link_ in linked.items() if e.startswith("bug:")}
        bugs = bug_items(verdicts, states)
        failing = {b.element for b in bugs}
        desired += bugs
        # A bug whose check passes again is done: the verdict that closes it is the evidence.
        desired += [Desired(e, "bug", "", "", state="done", comment="The check passes in the newest verdict.")
                    for e, link_ in linked.items() if e.startswith("bug:") and e not in failing
                    and link_.state != "done"]  # fmt: skip
    return desired, linked


async def sync_backlog(engine: AsyncEngine, objects: ObjectStore | None, secrets: SecretStore | None,
                       trackers: TrackerFactory, tenant_id: uuid.UUID, project_id: uuid.UUID,
                       reason: str = "manual", fixer: Fixer | None = None) -> str:  # fmt: skip
    """Sync the project's backlog; returns a summary (also kept as the link's last sync detail)."""
    link = await load_link(engine, tenant_id, project_id)
    if link is None:
        return "the project is not linked to Jira or Azure DevOps"
    token = await secrets.get(link.vault_path) if secrets is not None and link.vault_path else None
    if not token:
        return await _finish(engine, tenant_id, project_id, "the integration has no credential", ok=False)
    tracker = trackers(link, token)
    desired, linked = await desired_backlog(engine, objects, tenant_id, project_id, link)
    # A closing transition of a bug the planner only knows by its link keeps the item's title and description.
    desired = [d if d.title or d.element not in linked else Desired(
        d.element, d.kind, "", "", state=d.state, comment=d.comment) for d in desired]  # fmt: skip
    actions = [a for a in plan(desired, linked) if not (a.op == "update" and not a.desired.title)]

    async def write(op: str, item: Desired, current: Linked) -> None:
        async with _db(engine, tenant_id) as conn:
            await conn.execute(
                text("INSERT INTO work_item_link (tenant_id, project_id, integration_id, element, kind, title, "
                     "external_id, external_key, url, digest, state) VALUES (:t, :p, :i, :e, :k, :ti, :x, :xk, :u, :d, "
                     ":s) ON CONFLICT (project_id, integration_id, element) DO UPDATE SET title = COALESCE(NULLIF("
                     "EXCLUDED.title, ''), work_item_link.title), digest = CASE WHEN EXCLUDED.title = '' THEN "
                     "work_item_link.digest ELSE EXCLUDED.digest END, state = EXCLUDED.state, updated_at = now()"),
                {"t": tenant_id, "p": project_id, "i": link.integration_id, "e": item.element, "k": item.kind,
                 "ti": item.title, "x": current.external_id, "xk": current.external_key, "u": current.url,
                 "d": current.digest, "s": current.state},
            )  # fmt: skip
            await record(conn, AuditEvent(
                action=f"backlog.{op}", outcome="success", actor_kind="system", actor_label=ACTOR,
                target=f"project:{project_id}", tenant_id=tenant_id,
                details={"system": link.kind, "element": item.element, "kind": item.kind,
                         "external_key": current.external_key, "state": current.state, "reason": reason},
            ))  # fmt: skip

    try:
        outcome = await apply(tracker, actions, linked, write)
    except TrackerError as exc:
        return await _finish(engine, tenant_id, project_id, str(exc), ok=False)
    summary = (f"{outcome.created} created, {outcome.updated} updated, {outcome.transitioned} moved"
               + (f", {outcome.recovered} recovered by label" if outcome.recovered else ""))  # fmt: skip
    if fixer is not None and link.rules.get("autoFix", True):
        try:
            summary += f"; bugs: {await fixer(tracker, link)}"
        except TrackerError as exc:
            summary += f"; bugs: {exc}"
    return await _finish(engine, tenant_id, project_id, summary, ok=True)


async def _finish(engine: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, detail: str, *, ok: bool) -> str:
    async with _db(engine, tenant_id) as conn:
        await conn.execute(text("UPDATE project_backlog SET last_synced_at = now(), last_sync_detail = :d "
                                "WHERE project_id = :p"), {"p": project_id, "d": detail[:500]})  # fmt: skip
        if not ok:
            await record(conn, AuditEvent(action="backlog.sync", outcome="failure", actor_kind="system",
                                          actor_label=ACTOR, target=f"project:{project_id}", tenant_id=tenant_id,
                                          details={"detail": detail[:300]}))  # fmt: skip
    return detail


def bug_fixer(runtime: Any, tenant_id: uuid.UUID, project_id: uuid.UUID) -> Fixer | None:
    """The bug cycle when the runtime has the models, the object store and the sandboxes; None otherwise."""
    if runtime.gateway is None or runtime.objects is None or runtime.sandboxes is None:
        return None
    from nexti_worker.bugfix import fix_bugs

    async def fix(tracker: BacklogTracker, link: Link) -> str:
        return await fix_bugs(runtime.engine, runtime.objects, runtime.gateway, runtime.sandboxes, tracker, tenant_id,
                              project_id, link.integration_id)  # fmt: skip

    return fix
