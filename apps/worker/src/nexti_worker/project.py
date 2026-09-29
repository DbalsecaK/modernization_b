"""The project as the analysis executors see it (nexti_orchestration.modernization.ProjectPort), on the real
services: the source code comes from the accepted zip inputs in the object store (read as text, never executed),
rules / stories / the plan are written as new versions in PostgreSQL (RLS by tenant) and mirrored in the knowledge
graph, and every model call goes through the gateway (CLAUDE.md rule 2)."""

import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.adapters import Edge, Inventory, LegacyRunner, Node, SourceFile
from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore
from nexti_core.spec.characterization import GoldenMaster
from nexti_core.spec.model import Rule
from nexti_graph import GraphStore, Scope
from nexti_model_gateway.gateway import CallContext, NoProfileError
from nexti_model_gateway.service import GatewayService
from nexti_orchestration import RunContext
from nexti_orchestration.extraction import ModelCaller, ModelReply
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories
from nexti_pack_spring_boot import Design
from nexti_sandbox import Sandbox

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
TEXT_SUFFIXES = (".sp", ".sql", ".prc", ".proc", ".tsql", ".syb", ".txt")


class GatewayCaller:
    """ModelCaller on the gateway: the call is labelled with the run, phase, agent and iteration (13.1). A second
    judge asks for the profile of `<agent>:judge2`; without one the cascade falls back to the broader profile."""

    def __init__(self, gateway: GatewayService, run: RunContext) -> None:
        self.gateway = gateway
        self.run = run

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        role = f"{agent}:judge{judge + 1}" if judge else agent
        ctx = CallContext(self.run.tenant_id, self.run.project_id, phase, role, str(self.run.run_id), iteration)
        try:
            completion = await self.gateway.complete(ctx, list(messages))
        except NoProfileError:
            if not judge:
                raise
            ctx = CallContext(self.run.tenant_id, self.run.project_id, phase, agent, str(self.run.run_id), iteration)
            completion = await self.gateway.complete(ctx, list(messages))
        usage = Usage(completion.model or None, completion.usage.input_tokens, completion.usage.output_tokens,
                      completion.cost_usd)  # fmt: skip
        return ModelReply(completion.content, usage)


def read_zip(data: bytes, prefix: str = "") -> list[SourceFile]:
    """The text files of an accepted archive (validated at upload by packages/ingest), with size limits."""
    files: list[SourceFile] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.lower().endswith(TEXT_SUFFIXES) or info.file_size > MAX_FILE_BYTES:
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                break
            raw = archive.read(info)
            if b"\x00" in raw[:4096]:
                continue
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("latin-1")
            files.append(SourceFile(f"{prefix}{name}", content.replace("\r\n", "\n")))
    return files


class WorkerProjectPort:
    def __init__(
        self,
        engine: AsyncEngine,
        run: RunContext,
        gateway: GatewayService,
        objects: ObjectStore | None,
        graph: GraphStore | None,
        sandboxes: Callable[[str], Sandbox] | None = None,
        legacy: Callable[[], LegacyRunner] | None = None,
    ) -> None:
        self.engine = engine
        self.run = run
        self.models: ModelCaller = GatewayCaller(gateway, run)
        self.objects = objects
        self.graph = graph
        self.scope = Scope(run.tenant_id, run.project_id)
        self._files: list[SourceFile] | None = None
        self._sandboxes = sandboxes
        self._legacy = legacy

    def _db(self) -> Any:
        return scoped_connection(self.engine, DbScope(tenant_id=self.run.tenant_id))

    async def source_files(self) -> list[SourceFile]:
        if self._files is not None:
            return self._files
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT name, object_key FROM input_artifact WHERE project_id = :p AND kind = 'source_archive' "
                        "AND status = 'accepted' AND deleted_at IS NULL ORDER BY name, version DESC"
                    ),
                    {"p": self.run.project_id},
                )
            ).all()
        files: list[SourceFile] = []
        seen: set[str] = set()
        for row in rows:
            if row.name in seen or self.objects is None:  # the latest version of each archive only
                continue
            seen.add(row.name)
            data = b"".join(await self.objects.read(row.object_key))
            files += read_zip(data)
        self._files = files
        return files

    # -- graph ---------------------------------------------------------------------------------------------------
    async def save_inventory(self, inventory: Inventory) -> None:
        if self.graph is not None:
            await self.graph.replace_code_layer(self.scope, inventory)

    async def save_domains(self, domains: dict[str, list[str]]) -> None:
        if self.graph is None:
            return
        await self.graph.upsert_nodes(self.scope, [Node(f"domain:{name}", "Domain", name) for name in domains])
        await self.graph.upsert_edges(self.scope, [
            Edge(member, "BELONGS_TO", f"domain:{name}") for name, members in domains.items() for member in members
        ])  # fmt: skip

    # -- rules ---------------------------------------------------------------------------------------------------
    async def save_rules(self, rules: Sequence[Rule]) -> None:
        """A new version of each rule whose content changed; rules no longer found become obsolete."""
        async with self._db() as conn:
            current = {
                r.key: r
                for r in (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT ON (key) key, version, status, data FROM spec_element "
                            "WHERE project_id = :p AND element_type = 'rule' ORDER BY key, version DESC"
                        ),
                        {"p": self.run.project_id},
                    )
                ).all()
            }
            new_keys = {r.id for r in rules}
            for rule in rules:
                data = rule.model_dump(mode="json")
                previous = current.get(rule.id)
                if previous is not None and previous.data == data and previous.status != "obsolete":
                    continue
                await self._insert_element(conn, rule.id, (previous.version + 1) if previous else 1, "review", data)
            for key, previous in current.items():
                if key not in new_keys and previous.status != "obsolete":
                    await self._insert_element(conn, key, previous.version + 1, "obsolete", previous.data)
        if self.graph is not None:
            procs = await self.graph.nodes(self.scope, "StoredProcedure")
            await self.graph.upsert_nodes(self.scope, [
                Node(f"rule:{r.id}", "Rule", r.name, r.sources[0].file, r.sources[0].line_start, r.sources[0].line_end,
                     {"priority": r.priority, "category": r.category}) for r in rules
            ])  # fmt: skip
            edges = []
            for rule in rules:
                ref = rule.sources[0]
                owner = next((p for p in procs if p.properties.get("file") == ref.file
                              and (p.properties.get("line_start") or 0) <= ref.line_start
                              <= (p.properties.get("line_end") or 0)), None)  # fmt: skip
                if owner is not None:
                    edges.append(Edge(f"rule:{rule.id}", "DERIVED_FROM", owner.key, {"lines": str(ref)}))
            await self.graph.upsert_edges(self.scope, edges)

    async def _insert_element(self, conn: Any, key: str, version: int, status: str, data: dict[str, Any]) -> None:
        await conn.execute(
            text(
                "INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data, run_id) "
                "VALUES (:t, :p, 'rule', :k, :v, :s, CAST(:d AS jsonb), :r)"
            ),
            {"t": self.run.tenant_id, "p": self.run.project_id, "k": key, "v": version, "s": status,
             "d": json.dumps(data), "r": self.run.run_id},
        )  # fmt: skip

    async def load_rules(self) -> list[Rule]:
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT ON (key) key, status, data FROM spec_element WHERE project_id = :p "
                        "AND element_type = 'rule' ORDER BY key, version DESC"
                    ),
                    {"p": self.run.project_id},
                )
            ).all()
        return [Rule.model_validate(r.data) for r in rows if r.status != "obsolete"]

    # -- stories and plan ----------------------------------------------------------------------------------------
    async def save_stories(self, stories: Stories) -> None:
        """The first derivation creates the stories, their graph dependencies and plan version 1. Stories that already
        exist belong to people from then on (7.7): a new derivation only refreshes the suggested plan."""
        keys = stories.keys()
        async with self._db() as conn:
            existing = {
                r.key: r.id
                for r in (
                    await conn.execute(
                        text("SELECT key, id FROM user_story WHERE project_id = :p"), {"p": self.run.project_id}
                    )
                ).all()
            }
            ids: dict[str, uuid.UUID] = dict(existing)
            for key, draft in zip(keys, stories.drafts, strict=True):
                if key in existing:
                    continue
                story_id: uuid.UUID = (
                    await conn.execute(
                        text("INSERT INTO user_story (tenant_id, project_id, key) VALUES (:t, :p, :k) RETURNING id"),
                        {"t": self.run.tenant_id, "p": self.run.project_id, "k": key},
                    )
                ).scalar_one()
                ids[key] = story_id
                await conn.execute(
                    text(
                        "INSERT INTO user_story_version (tenant_id, story_id, version, feature, title, narrative, "
                        "criteria, links, priority, estimate, status, origin, action) VALUES (:t, :s, 1, :f, :ti, :n, "
                        "CAST(:c AS jsonb), CAST(:l AS jsonb), :pr, :e, 'review', 'extracted', 'create')"
                    ),
                    {"t": self.run.tenant_id, "s": story_id, "f": draft.feature, "ti": draft.title,
                     "n": draft.narrative, "c": json.dumps(draft.criteria), "l": json.dumps(draft.links),
                     "pr": draft.priority, "e": draft.estimate},
                )  # fmt: skip
            story_ids = list(ids.values())
            await conn.execute(
                text("DELETE FROM story_dependency WHERE origin = 'graph' AND story_id = ANY(:ids)"), {"ids": story_ids}
            )
            for dep in stories.dependencies:
                if dep.story in ids and dep.on in ids:
                    await conn.execute(
                        text(
                            "INSERT INTO story_dependency (tenant_id, story_id, depends_on, strength, reason, origin) "
                            "VALUES (:t, :s, :o, :st, :r, 'graph') ON CONFLICT DO NOTHING"
                        ),
                        {"t": self.run.tenant_id, "s": ids[dep.story], "o": ids[dep.on], "st": dep.strength,
                         "r": dep.reason[:500]},
                    )  # fmt: skip
            plan = (
                await conn.execute(
                    text(
                        "SELECT version, waves FROM migration_plan WHERE project_id = :p ORDER BY version DESC LIMIT 1"
                    ),
                    {"p": self.run.project_id},
                )
            ).first()
            await conn.execute(
                text(
                    "INSERT INTO migration_plan (tenant_id, project_id, version, waves, suggested, change_note) "
                    "VALUES (:t, :p, :v, CAST(:w AS jsonb), CAST(:s AS jsonb), :n)"
                ),
                {"t": self.run.tenant_id, "p": self.run.project_id, "v": (plan.version + 1) if plan else 1,
                 "w": json.dumps(plan.waves if plan else stories.waves), "s": json.dumps(stories.waves),
                 "n": "Suggested by the platform from the dependencies" if not plan else "New suggestion"},
            )  # fmt: skip
        if self.graph is not None:
            await self.graph.upsert_nodes(self.scope, [
                Node(f"story:{k}", "Story", d.title, properties={"priority": d.priority})
                for k, d in zip(keys, stories.drafts, strict=True)
            ])  # fmt: skip
            edges = [Edge(f"story:{k}", "COVERS", f"rule:{link}") for k, d in zip(keys, stories.drafts, strict=True)
                     for link in d.links]  # fmt: skip
            edges += [Edge(f"story:{d.story}", "DEPENDS_ON", f"story:{d.on}", {"strength": d.strength})
                      for d in stories.dependencies]  # fmt: skip
            await self.graph.upsert_edges(self.scope, edges)

    # -- design and generation (M4) ------------------------------------------------------------------------------
    def _key(self, *parts: str) -> str:
        return "/".join(["tenants", str(self.run.tenant_id), "projects", str(self.run.project_id), *parts])

    async def _put(self, key: str, content: str, content_type: str) -> None:
        if self.objects is None:
            raise RuntimeError("the object store is not configured")
        data = content.encode("utf-8")
        await self.objects.put(key, io.BytesIO(data), len(data), content_type)

    async def _get(self, key: str) -> str:
        if self.objects is None:
            raise RuntimeError("the object store is not configured")
        return b"".join(await self.objects.read(key)).decode("utf-8")

    async def inventory_digest(self) -> str:
        from nexti_adapter_sybase import SybaseAdapter

        files = await self.source_files()
        adapter = SybaseAdapter()
        inventory = adapter.inventory(files)
        lines = [f"Metrics: {json.dumps(inventory.metrics)}"]
        for node in inventory.nodes:
            if node.label == "StoredProcedure" and not node.properties.get("external"):
                lines.append(f"Procedure {node.name} ({node.file}:{node.line_start}-{node.line_end})")
            elif node.label == "Field":
                lines.append(f"  parameter {node.name}: {node.properties.get('neutral_type')}"
                             f"{' OUTPUT' if node.properties.get('output') else ''}")  # fmt: skip
            elif node.label == "Table":
                lines.append(f"Table {node.name}")
        for edge in inventory.edges:
            if edge.type in ("READS", "WRITES", "CALLS"):
                lines.append(f"{edge.source} {edge.type} {edge.target}")
        return "\n".join(lines)

    async def save_design(self, design: Design) -> None:
        path = "design/design.json"
        await self.save_artifacts({path: design.model_dump_json(indent=2)}, {path: "docs"},
                                  {path: sorted(design.rules())})  # fmt: skip

    async def load_design(self) -> Design | None:
        async with self._db() as conn:
            key = (
                await conn.execute(
                    text(
                        "SELECT object_key FROM generated_artifact WHERE project_id = :p "
                        "AND path = 'design/design.json' "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"p": self.run.project_id},
                )
            ).scalar_one_or_none()
        return Design.model_validate_json(await self._get(key)) if key else None

    async def save_file(self, path: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = self._key("runs", str(self.run.run_id), "drafts", digest)
        await self._put(key, content, "text/plain; charset=utf-8")
        return key

    async def load_file(self, reference: str) -> str:
        return await self._get(reference)

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        """Every generated file in the object store and one row per file (references only, 10.2)."""
        rows = []
        for path, content in files.items():
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            key = self._key("runs", str(self.run.run_id), "files", path)
            await self._put(key, content, "text/plain; charset=utf-8")
            rows.append({"t": self.run.tenant_id, "p": self.run.project_id, "r": self.run.run_id,
                         "l": layers.get(path, "docs"), "path": path, "k": key, "h": digest,
                         "s": len(content.encode("utf-8")), "ru": json.dumps(rules.get(path, []))})  # fmt: skip
        async with self._db() as conn:
            for row in rows:
                await conn.execute(
                    text(
                        "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, "
                        "sha256, size_bytes, rules) VALUES (:t, :p, :r, :l, :path, :k, :h, :s, CAST(:ru AS jsonb)) "
                        "ON CONFLICT (run_id, path) DO NOTHING"
                    ),
                    row,
                )

    def sandbox(self, image: str) -> Sandbox:
        if self._sandboxes is None:
            raise RuntimeError("no sandbox is configured for the packs")
        return self._sandboxes(image)

    # -- characterization (M4) -----------------------------------------------------------------------------------
    def legacy_runner(self) -> LegacyRunner | None:
        """The engine of the only source adapter of this version (Sybase ASE), when the worker has one."""
        return self._legacy() if self._legacy is not None else None

    async def save_golden_master(self, master: GoldenMaster) -> None:
        path = "characterization/golden_master.json"
        rules = sorted({r for recorded in master.results for r in recorded.case.rules})
        await self.save_artifacts({path: master.model_dump_json(indent=1, by_alias=True)}, {path: "tests"},
                                  {path: rules})  # fmt: skip
