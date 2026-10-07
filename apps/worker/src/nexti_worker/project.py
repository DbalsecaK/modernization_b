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
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_adapter_cobol import TraceRunner, is_trace
from nexti_core.adapters import Edge, Inventory, LegacyRunner, LegacyUnavailableError, Node, SourceFile
from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.jobs import defer_backlog_sync
from nexti_core.object_store import ObjectStore
from nexti_core.run_phase import CURRENT_PHASE
from nexti_core.secrets import SecretStore
from nexti_core.spec.characterization import CoveredBranch, GoldenMaster, Suite
from nexti_core.spec.model import Capability, Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_graph import GraphStore, Scope
from nexti_ingest import documents as document_reader
from nexti_ingest import figma
from nexti_ingest.archive import read_all_files, read_text_files
from nexti_ingest.documents import Document
from nexti_model_gateway.gateway import CallContext, NoProfileError
from nexti_model_gateway.service import GatewayService
from nexti_orchestration import RunContext
from nexti_orchestration.extraction import ModelCaller, ModelReply
from nexti_orchestration.feature import FeatureStory
from nexti_orchestration.modernization import pick_adapter
from nexti_orchestration.release import ReleaseRecord, Repository
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories
from nexti_pack_spring_boot import Design
from nexti_sandbox import Sandbox
from nexti_ui import PrototypeBuild, base_tokens
from nexti_verification import Verdict
from nexti_verification.evaluation import Evaluation
from nexti_worker.ui_chat import insert_prototype, store_draft


def _branches(files: list[SourceFile], program: str) -> list[CoveredBranch]:
    """The branches of a traced program from its source adapter, when it has the capability (step 11 of the plan)."""
    try:
        found = getattr(pick_adapter(files), "coverage_branches", None)
    except Exception:
        return []
    return list(found(files, program)) if callable(found) else []


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
        limit = completion.output_limit
        cut = limit if limit and completion.usage.output_tokens >= limit else None
        return ModelReply(completion.content, usage, cut)


def read_zip(data: bytes, prefix: str = "") -> list[SourceFile]:
    """The text files of an accepted archive (validated at upload by packages/ingest), with size limits."""
    return [SourceFile(path, text) for path, text in read_text_files(data, prefix)]


class SourceRunner:
    """The legacy runner chosen by the inputs: recorded CICS traces when the archive has them (the legacy cannot run
    here, ADR-0015), otherwise the engine the worker was given (Sybase ASE, live or recorded)."""

    def __init__(self, engine: Callable[[], LegacyRunner] | None) -> None:
        self._engine = engine
        self.engine = "none"

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        runner: LegacyRunner
        if any(is_trace(f) for f in files):
            runner = TraceRunner(branches=_branches)
        elif self._engine is not None:
            runner = self._engine()
        else:
            raise LegacyUnavailableError("there is no engine to run this legacy and no recorded traces")
        self.engine = runner.engine
        return await runner.run(files, suite)


class LiveFigma:
    """Figma read with the tenant's integration (ADR-0018): the newest Figma integration that has a token; the token
    is read from the secrets store for each file and never kept."""

    def __init__(self, engine: AsyncEngine, tenant_id: uuid.UUID, secrets: SecretStore | None,
                 http: Any, base_url: str = figma.API) -> None:  # fmt: skip
        self.engine = engine
        self.tenant_id = tenant_id
        self.secrets = secrets
        self.http = http
        self.base_url = base_url

    async def file(self, key: str) -> dict[str, Any]:
        if not self.base_url:
            raise figma.FigmaError("Figma is not read in this deployment (air-gapped profile)")
        async with scoped_connection(self.engine, DbScope(tenant_id=self.tenant_id)) as conn:
            path = (
                await conn.execute(
                    text("SELECT vault_path FROM tenant_integration WHERE kind = 'figma' AND vault_path IS NOT NULL "
                         "ORDER BY (status = 'ok') DESC, updated_at DESC LIMIT 1")
                )
            ).scalar_one_or_none()  # fmt: skip
        if path is None or self.secrets is None or self.http is None:
            raise figma.FigmaError("The tenant has no Figma integration: connect it in Administration > Integrations")
        token = await self.secrets.get(path)
        if not token:
            raise figma.FigmaError("The Figma integration has no token: set it in Administration > Integrations")
        return await figma.FigmaClient(self.http, token, self.base_url).file(key)


@dataclass(frozen=True)
class DeliveryServices:
    """What hardening and delivery need from the worker (ADR-0023)."""

    http: httpx.AsyncClient | None = None
    secrets: SecretStore | None = None
    osv_url: str | None = None  # None: dependencies are not checked (offline, tests)
    allow_private_hosts: bool = False  # local only: the test Git server


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
        figma_reader: figma.FigmaReader | None = None,
        delivery: DeliveryServices | None = None,
    ) -> None:
        self.engine = engine
        self.run = run
        self.models: ModelCaller = GatewayCaller(gateway, run)
        self.objects = objects
        self.graph = graph
        self.scope = Scope(run.tenant_id, run.project_id)
        self._files: list[SourceFile] | None = None
        self._target: dict[str, bytes] | None = None
        self._sandboxes = sandboxes
        self._legacy = legacy
        self._figma = figma_reader
        self._delivery = delivery or DeliveryServices()

    def _db(self) -> Any:
        return scoped_connection(self.engine, DbScope(tenant_id=self.run.tenant_id))

    async def source_files(self) -> list[SourceFile]:
        if self._files is None:
            self._files = await self._archive_files("source_archive")
        return self._files

    async def target_archive(self) -> dict[str, bytes]:
        """Flow 4 (ADR-0025): every file of the newest third-party target, binary included, never mixed with the
        legacy code."""
        if self._target is None:
            self._target = {}
            for data in await self._archives("target_archive"):
                self._target |= read_all_files(data)
        return self._target

    async def application_files(self) -> dict[str, str]:
        """Flow 3 (ADR-0026): every text file of the existing application (its Java, resources and build file), not
        only the legacy suffixes `source_files` reads."""
        found: dict[str, str] = {}
        for data in await self._archives("source_archive"):
            for path, raw in read_all_files(data).items():
                if b"\x00" in raw[:4096]:
                    continue  # binary (jars, images): not part of the code a delta reads or writes
                try:
                    found[path] = raw.decode("utf-8").replace("\r\n", "\n")
                except UnicodeDecodeError:
                    found[path] = raw.decode("latin-1").replace("\r\n", "\n")
        return found

    async def _archive_files(self, kind: str) -> list[SourceFile]:
        files: list[SourceFile] = []
        for data in await self._archives(kind):
            files += read_zip(data)
        return files

    async def _archives(self, kind: str) -> list[bytes]:
        """The bytes of the latest version of each accepted archive of a kind."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT name, object_key FROM input_artifact WHERE project_id = :p AND kind = :k "
                        "AND status = 'accepted' AND deleted_at IS NULL ORDER BY name, version DESC"
                    ),
                    {"p": self.run.project_id, "k": kind},
                )
            ).all()
        found: list[bytes] = []
        seen: set[str] = set()
        for row in rows:
            if row.name in seen or self.objects is None:  # the latest version of each archive only
                continue
            seen.add(row.name)
            found.append(b"".join(await self.objects.read(row.object_key)))
        return found

    # -- inputs of Flow 2 (M7) -----------------------------------------------------------------------------------
    async def _accepted(self, kind: str) -> list[Any]:
        """The newest accepted version of each input of a kind."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (name) name, object_key, url FROM input_artifact WHERE project_id = :p "
                         "AND kind = :k AND status = 'accepted' AND deleted_at IS NULL ORDER BY name, version DESC"),
                    {"p": self.run.project_id, "k": kind},
                )
            ).all()  # fmt: skip
        return list(rows)

    async def documents(self) -> list[Document]:
        found = []
        for row in await self._accepted("document"):
            if row.object_key and self.objects is not None:
                found.append((row.name, b"".join(await self.objects.read(row.object_key))))
        binary = any(not name.lower().endswith(document_reader.TEXT_SUFFIXES) for name, _ in found)
        sandbox = self.sandbox(document_reader.IMAGE) if binary and self._sandboxes is not None else None
        return await document_reader.convert(sandbox, found)

    async def figma_files(self) -> list[tuple[str, dict[str, Any]]]:
        keys = sorted({k for row in await self._accepted("figma_link") if (k := figma.file_key(row.url or ""))})
        if not keys:
            return []
        if self._figma is None:
            raise figma.FigmaError("Figma cannot be read by this worker")
        return [(key, await self._figma.file(key)) for key in keys]

    async def input_names(self, kind: str) -> list[str]:
        return [row.url or row.name for row in await self._accepted(kind)]

    async def load_inputs(self) -> dict[str, str]:
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (path) path, object_key FROM generated_artifact WHERE project_id = :p "
                         "AND path LIKE 'inputs/%' ORDER BY path, created_at DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return {row.path: await self._get(row.object_key) for row in rows}

    async def open_questions(self) -> list[str]:
        async with self._db() as conn:
            rows = (
                await conn.execute(text("SELECT question_text FROM question WHERE project_id = :p AND status = 'open' "
                                        "ORDER BY created_at"), {"p": self.run.project_id})
            ).scalars()  # fmt: skip
            return [str(r) for r in rows]

    async def save_capabilities(self, capabilities: Sequence[Capability]) -> None:
        await self._save_elements("capability", [(c.id, c.model_dump(mode="json")) for c in capabilities])

    async def load_stories(self) -> list[FeatureStory]:
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (s.key) s.key, v.title, v.criteria, v.links, v.status FROM user_story s "
                         "JOIN user_story_version v ON v.story_id = s.id WHERE s.project_id = :p "
                         "ORDER BY s.key, v.version DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return [FeatureStory(r.key, r.title, list(r.criteria), list(r.links), r.status) for r in rows]

    async def _save_elements(self, element_type: str, items: Sequence[tuple[str, dict[str, Any]]]) -> None:
        """A new version of each element whose content changed."""
        async with self._db() as conn:
            current = {
                r.key: r
                for r in (
                    await conn.execute(
                        text("SELECT DISTINCT ON (key) key, version, data FROM spec_element WHERE project_id = :p "
                             "AND element_type = :e ORDER BY key, version DESC"),
                        {"p": self.run.project_id, "e": element_type},
                    )
                ).all()
            }  # fmt: skip
            for key, data in items:
                previous = current.get(key)
                if previous is not None and previous.data == data:
                    continue
                await self._insert_element(conn, key, (previous.version + 1) if previous else 1, "review", data,
                                           element_type)  # fmt: skip

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

    async def _insert_element(
        self, conn: Any, key: str, version: int, status: str, data: dict[str, Any], element_type: str = "rule"
    ) -> None:
        await conn.execute(
            text(
                "INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data, run_id) "
                "VALUES (:t, :p, :e, :k, :v, :s, CAST(:d AS jsonb), :r)"
            ),
            {"t": self.run.tenant_id, "p": self.run.project_id, "e": element_type, "k": key, "v": version,
             "s": status, "d": json.dumps(data), "r": self.run.run_id},
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
                        "CAST(:c AS jsonb), CAST(:l AS jsonb), :pr, :e, 'review', :o, 'create')"
                    ),
                    {"t": self.run.tenant_id, "s": story_id, "f": draft.feature, "ti": draft.title,
                     "n": draft.narrative, "c": json.dumps(draft.criteria), "l": json.dumps(draft.links),
                     "pr": draft.priority, "e": draft.estimate, "o": stories.origin},
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
            edges = [Edge(f"story:{k}", "COVERS", f"{'screen' if link.startswith('SCR-') else 'rule'}:{link}")
                     for k, d in zip(keys, stories.drafts, strict=True) for link in d.links]  # fmt: skip
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
        files = await self.source_files()
        return pick_adapter(files).digest(files)

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
                         "s": len(content.encode("utf-8")), "ru": json.dumps(rules.get(path, [])),
                         "ph": CURRENT_PHASE.get() or None})  # fmt: skip
        async with self._db() as conn:
            for row in rows:
                # A retried phase writes the same paths again (ADR-0035): the row follows the new content.
                await conn.execute(
                    text(
                        "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, "
                        "sha256, size_bytes, rules, phase) VALUES (:t, :p, :r, :l, :path, :k, :h, :s, "
                        "CAST(:ru AS jsonb), :ph) ON CONFLICT (run_id, path) DO UPDATE SET layer = EXCLUDED.layer, "
                        "object_key = EXCLUDED.object_key, sha256 = EXCLUDED.sha256, size_bytes = EXCLUDED.size_bytes, "
                        "rules = EXCLUDED.rules, phase = EXCLUDED.phase, created_at = now()"
                    ),
                    row,
                )

    def sandbox(self, image: str) -> Sandbox:
        if self._sandboxes is None:
            raise RuntimeError("no sandbox is configured for the packs")
        return self._sandboxes(image)

    # -- hardening and delivery (M9a, ADR-0023) --------------------------------------------------------------------
    def delivery_services(self) -> tuple[httpx.AsyncClient | None, str | None, bool]:
        return self._delivery.http, self._delivery.osv_url, self._delivery.allow_private_hosts

    async def load_test_report(self) -> str | None:
        """The JUnit XML of the clean build, from the proof pack of the run's own verdict (not frontend nor IaC)."""
        async with self._db() as conn:
            key = (
                await conn.execute(
                    text("SELECT proof_pack_key FROM verdict WHERE run_id = :r AND module NOT LIKE 'frontend-%' "
                         "AND module NOT LIKE 'iac-%' ORDER BY created_at DESC LIMIT 1"),
                    {"r": self.run.run_id},
                )
            ).scalar()  # fmt: skip
        if not key or self.objects is None:
            return None
        data = b"".join(await self.objects.read(key))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read("junit.xml").decode("utf-8") if "junit.xml" in archive.namelist() else None

    async def repository(self) -> Repository | None:
        async with self._db() as conn:
            row = (
                await conn.execute(text("SELECT url, branch, vault_path FROM project_repository WHERE project_id = :p"),
                                   {"p": self.run.project_id})
            ).first()  # fmt: skip
        if row is None:
            return None
        token = None
        if row.vault_path and self._delivery.secrets is not None:
            token = await self._delivery.secrets.get(row.vault_path)
        return Repository(row.url, row.branch or "main", token)

    async def may_push(self) -> bool:
        async with self._db() as conn:
            found = (
                await conn.execute(
                    text("SELECT 1 FROM role_assignment ra JOIN role_permission rp ON rp.role_id = ra.role_id "
                         "WHERE ra.user_id = (SELECT started_by FROM run WHERE id = :r) "
                         "AND rp.permission_key = 'code.push' AND (ra.project_id IS NULL OR ra.project_id = :p) "
                         "LIMIT 1"),
                    {"r": self.run.run_id, "p": self.run.project_id},
                )
            ).first()  # fmt: skip
        return found is not None

    async def save_release(self, release: ReleaseRecord) -> None:
        async with self._db() as conn:
            await conn.execute(
                text("INSERT INTO release (tenant_id, project_id, run_id, kind, status, repository_url, branch, "
                     "commit_sha, base_sha, files, findings, error, created_by) VALUES (:t, :p, :r, :k, :s, :u, :b, "
                     ":c, :base, :f, CAST(:fi AS jsonb), :e, (SELECT started_by FROM run WHERE id = :r))"),
                {"t": self.run.tenant_id, "p": self.run.project_id, "r": self.run.run_id, "k": release.kind,
                 "s": release.status, "u": release.repository_url, "b": release.branch, "c": release.commit_sha,
                 "base": release.base_sha, "f": release.files, "fi": json.dumps(release.findings),
                 "e": release.error},
            )  # fmt: skip

    # -- characterization (M4) -----------------------------------------------------------------------------------
    def legacy_runner(self) -> LegacyRunner | None:
        """How this legacy is observed, chosen by its inputs (see SourceRunner)."""
        return SourceRunner(self._legacy)

    async def save_golden_master(self, master: GoldenMaster) -> None:
        path = "characterization/golden_master.json"
        rules = sorted({r for recorded in master.results for r in recorded.case.rules})
        await self.save_artifacts({path: master.model_dump_json(indent=1, by_alias=True)}, {path: "tests"},
                                  {path: rules})  # fmt: skip

    # -- verification (M4) ---------------------------------------------------------------------------------------
    async def _artifact_key(self, path: str) -> str | None:
        async with self._db() as conn:
            key: str | None = (
                await conn.execute(
                    text("SELECT object_key FROM generated_artifact WHERE project_id = :p AND path = :path "
                         "ORDER BY created_at DESC LIMIT 1"),
                    {"p": self.run.project_id, "path": path},
                )
            ).scalar_one_or_none()  # fmt: skip
        return key

    async def load_artifact(self, path: str) -> str | None:
        """The newest version of one generated file (the IV&V inventory, mapping and comparison, ADR-0025); for the
        mapping, a person's correction before C2 when it is newer than the intake's."""
        if path == "ivv/mapping.yaml":
            async with self._db() as conn:
                row = (
                    await conn.execute(
                        text("SELECT v.object_key FROM ivv_mapping_version v WHERE v.project_id = :p "
                             "AND v.created_at >= (SELECT max(created_at) FROM generated_artifact "
                             "WHERE project_id = :p AND path = :path) ORDER BY v.version DESC LIMIT 1"),
                        {"p": self.run.project_id, "path": path},
                    )
                ).scalar_one_or_none()  # fmt: skip
            if row is not None:
                return await self._get(row)
        key = await self._artifact_key(path)
        return await self._get(key) if key else None

    async def load_golden_master(self) -> GoldenMaster | None:
        key = await self._artifact_key("characterization/golden_master.json")
        return GoldenMaster.model_validate_json(await self._get(key)) if key else None

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        """The latest version of every generated file of the project (the design and the golden master apart)."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (path) path, object_key, rules FROM generated_artifact "
                         "WHERE project_id = :p AND path NOT LIKE 'design/%' AND path NOT LIKE 'characterization/%' "
                         "AND path NOT LIKE 'frontend/%' AND path NOT LIKE 'inputs/%' AND path NOT LIKE 'infra/%' "
                         "AND path NOT LIKE 'ivv/%' AND path NOT LIKE 'delta/%' "
                         "ORDER BY path, created_at DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        files = {row.path: await self._get(row.object_key) for row in rows}
        return files, {row.path: list(row.rules) for row in rows if row.rules}

    async def load_frontend(self) -> dict[str, str]:
        """The newest generated frontend files, paths relative to the frontend project (M6b, ADR-0016)."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (path) path, object_key FROM generated_artifact WHERE project_id = :p "
                         "AND path LIKE 'frontend/%' ORDER BY path, created_at DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return {row.path.removeprefix("frontend/"): await self._get(row.object_key) for row in rows}

    async def load_infrastructure(self) -> dict[str, str]:
        """The newest generated IaC files, paths under infra/<cloud>/ (ADR-0021)."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (path) path, object_key FROM generated_artifact WHERE project_id = :p "
                         "AND path LIKE 'infra/%' ORDER BY path, created_at DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return {row.path: await self._get(row.object_key) for row in rows}

    async def load_screens(self) -> list[ScreenSpec]:
        """The newest version of every screen spec of the project."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (key) key, data FROM spec_element WHERE project_id = :p "
                         "AND element_type = 'screen' ORDER BY key, version DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return [ScreenSpec.model_validate(row.data) for row in sorted(rows, key=lambda r: r.key)]

    async def load_prototypes(self) -> dict[str, str]:
        """The TSX of each screen's prototype: the newest approved version, else the newest one."""
        async with self._db() as conn:
            rows = (
                await conn.execute(
                    text("SELECT DISTINCT ON (screen_key) screen_key, source_key FROM prototype WHERE project_id = :p "
                         "ORDER BY screen_key, (status = 'approved') DESC, version DESC"),
                    {"p": self.run.project_id},
                )
            ).all()  # fmt: skip
        return {row.screen_key: await self._get(row.source_key) for row in rows}

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        if self.objects is None:
            raise RuntimeError("the object store is not configured")
        checks = [{"key": c.key, "title": c.title, "status": c.status, "detail": c.detail} for c in verdict.checks]
        async with self._db() as conn:
            # A verdict is evidence, never rewritten: a retried verification (ADR-0035) adds its own attempt, with
            # its own proof pack, and the newest one is the module's verdict.
            attempt = (
                await conn.execute(
                    text("SELECT COALESCE(MAX(attempt), 0) + 1 FROM verdict WHERE run_id = :r AND module = :m"),
                    {"r": self.run.run_id, "m": verdict.module},
                )
            ).scalar_one()
            parts = ("runs", str(self.run.run_id), "verification", verdict.module)
            key = self._key(*parts, "proof-pack.zip" if attempt == 1 else f"attempt-{attempt}/proof-pack.zip")
            await self.objects.put(key, io.BytesIO(proof_pack), len(proof_pack), "application/zip")
            await conn.execute(
                text("INSERT INTO verdict (tenant_id, project_id, run_id, module, verdict, checks, not_proven, "
                     "proof_pack_key, attempt) VALUES (:t, :p, :r, :m, :v, CAST(:c AS jsonb), CAST(:n AS jsonb), "
                     ":k, :a)"),
                {"t": self.run.tenant_id, "p": self.run.project_id, "r": self.run.run_id, "m": verdict.module,
                 "v": verdict.verdict, "c": json.dumps(checks), "n": json.dumps(verdict.not_proven), "k": key,
                 "a": int(attempt)},
            )  # fmt: skip
            # The linked backlog follows the verdict (7.6): verified items to Done, a failed check opens a bug.
            linked = (
                await conn.execute(text("SELECT 1 FROM project_backlog WHERE project_id = :p"),
                                   {"p": self.run.project_id})
            ).first()  # fmt: skip
            if linked is not None:
                await defer_backlog_sync(conn, self.run.project_id, self.run.tenant_id, f"verdict {verdict.module}")
        return key

    # -- evaluation against a reference (M4) ---------------------------------------------------------------------
    async def save_evaluation(self, evaluation: Evaluation) -> None:
        """The metrics with the name and hash of the reference, never its content (ADR-0011)."""
        async with self._db() as conn:
            await conn.execute(
                text("INSERT INTO evaluation (tenant_id, project_id, run_id, reference, reference_sha256, metrics) "
                     "VALUES (:t, :p, :r, :n, :h, CAST(:m AS jsonb))"),
                {"t": self.run.tenant_id, "p": self.run.project_id, "r": self.run.run_id,
                 "n": evaluation.reference[:200], "h": evaluation.reference_sha256,
                 "m": json.dumps(evaluation.metrics())},
            )  # fmt: skip

    # -- screens and prototypes (M5) -----------------------------------------------------------------------------
    async def save_screens(self, screens: Sequence[ScreenSpec]) -> None:
        """A new version of each screen spec whose content changed (like rules: people may edit them later)."""
        async with self._db() as conn:
            current = {
                r.key: r
                for r in (
                    await conn.execute(
                        text("SELECT DISTINCT ON (key) key, version, status, data FROM spec_element "
                             "WHERE project_id = :p AND element_type = 'screen' ORDER BY key, version DESC"),
                        {"p": self.run.project_id},
                    )
                ).all()
            }  # fmt: skip
            for screen in screens:
                data = screen.model_dump(mode="json")
                previous = current.get(screen.id)
                if previous is not None and previous.data == data:
                    continue
                await self._insert_element(conn, screen.id, (previous.version + 1) if previous else 1, "review", data,
                                           "screen")  # fmt: skip

    async def ensure_design_system(self) -> int:
        async with self._db() as conn:
            version: int | None = (
                await conn.execute(text("SELECT max(version) FROM design_system WHERE project_id = :p"),
                                   {"p": self.run.project_id})
            ).scalar_one_or_none()  # fmt: skip
            if version:
                return version
            await conn.execute(
                text("INSERT INTO design_system (tenant_id, project_id, version, source, tokens) "
                     "VALUES (:t, :p, 1, 'nexti-base', CAST(:k AS jsonb))"),
                {"t": self.run.tenant_id, "p": self.run.project_id, "k": json.dumps(base_tokens())},
            )  # fmt: skip
        return 1

    async def save_prototype(self, screen: str, source: str, built: PrototypeBuild, origin: str, notes: str) -> int:
        """The code and the page of a new prototype version in the object store; the row keeps their references."""
        if self.objects is None:
            raise RuntimeError("the object store is not configured")
        keys = await store_draft(self.objects, self.run.tenant_id, self.run.project_id, screen,
                                 f"run-{self.run.run_id}-{uuid.uuid4().hex[:8]}", source, built)  # fmt: skip
        async with self._db() as conn:
            return await insert_prototype(conn, self.run.tenant_id, self.run.project_id, screen, keys, origin, notes,
                                          self.run.run_id)  # fmt: skip
