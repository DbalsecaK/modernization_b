"""What the preflight checks, on the real services (spec 11.1): the database (inputs, models, budget), the secrets
store (the repository token) and the repository itself. Archives are read from the object store only to be handed
to the sandbox."""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.composition.loader import core_data
from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore, ObjectStoreError
from nexti_core.secrets import SecretsError, SecretStore
from nexti_ingest.errors import Rejection
from nexti_ingest.git import check_repository
from nexti_model_gateway.rules import AssignmentRow, resolve_profile
from nexti_orchestration import Check, RunContext

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


class ServicesProbe:
    def __init__(
        self,
        engine: AsyncEngine,
        run: RunContext,
        relative_cost: int,
        *,
        objects: ObjectStore | None,
        secrets: SecretStore | None,
        http: httpx.AsyncClient,
        allow_private_hosts: bool = False,
    ) -> None:
        self.engine = engine
        self.run = run
        self.relative_cost = relative_cost
        self.object_store = objects
        self.secret_store = secrets
        self.http = http
        self.allow_private_hosts = allow_private_hosts

    def _scope(self) -> DbScope:
        return DbScope(tenant_id=self.run.tenant_id)

    async def _rows(self, sql: str, **params: object) -> list[dict[str, object]]:
        async with scoped_connection(self.engine, self._scope()) as conn:
            result = await conn.execute(text(sql), {"project": self.run.project_id, **params})
            return [dict(r) for r in result.mappings().all()]

    async def inputs(self) -> Check:
        rows = await self._rows(
            "SELECT kind, status FROM input_artifact WHERE project_id = :project AND deleted_at IS NULL"
        )
        accepted = [r for r in rows if r["status"] == "accepted"]
        repository = await self._rows("SELECT 1 FROM project_repository WHERE project_id = :project")
        if not accepted and not repository:
            return Check("inputs", False, "the project has no accepted input and no repository")
        return Check(
            "inputs", True, f"{len(accepted)} accepted input(s)" + (", repository linked" if repository else "")
        )

    async def _repository(self) -> dict[str, object] | None:
        rows = await self._rows("SELECT url, branch, vault_path FROM project_repository WHERE project_id = :project")
        return rows[0] if rows else None

    async def secrets(self) -> Check:
        repository = await self._repository()
        if repository is None or not repository["vault_path"]:
            return Check("secrets", True, "no credential to resolve")
        if self.secret_store is None:
            return Check("secrets", False, "the secrets store is not configured")
        try:
            token = await self.secret_store.get(str(repository["vault_path"]))
        except (SecretsError, httpx.HTTPError):
            return Check("secrets", False, "the secrets store cannot be reached")
        if not token:
            return Check("secrets", False, "the repository token is missing from the secrets store")
        return Check("secrets", True, "the repository token resolves")

    async def repository(self) -> Check:
        repository = await self._repository()
        if repository is None:
            return Check("repository", True, "no repository linked")
        token = None
        if repository["vault_path"] and self.secret_store is not None:
            try:
                token = await self.secret_store.get(str(repository["vault_path"]))
            except (SecretsError, httpx.HTTPError):
                token = None
        try:
            result = await check_repository(
                str(repository["url"]), str(repository["branch"]), token, self.http,
                allow_private_hosts=self.allow_private_hosts,
            )  # fmt: skip
        except Rejection as exc:
            return Check("repository", False, exc.detail)
        return Check("repository", result.ok, result.detail)

    async def models(self) -> Check:
        rows = await self._rows("SELECT project_id, phase, agent_role, profile_id FROM model_assignment")
        assignments = [AssignmentRow(r["project_id"], r["phase"], r["agent_role"], r["profile_id"]) for r in rows]  # type: ignore[arg-type]
        missing = [
            agent.key
            for agent in self.run.agents
            if resolve_profile(assignments, self.run.project_id, agent.phases[0] if agent.phases else None, agent.key)
            is None
        ]
        if missing:
            return Check("models", False, f"no model profile for: {', '.join(missing)}")
        return Check("models", True, f"a model profile for each of the {len(self.run.agents)} agents")

    async def budget(self) -> Check:
        estimate = Decimal(self.relative_cost) * Decimal(str(core_data()["flows"]["cost_unit_usd"]))
        budgets = await self._rows(
            "SELECT project_id, period, amount_usd, hard_stop FROM budget "
            "WHERE project_id = :project OR project_id IS NULL ORDER BY project_id NULLS LAST"
        )
        if not budgets:
            return Check("budget", True, f"no budget configured; estimate {estimate:.2f} USD")
        budget = budgets[0]
        since = datetime(1970, 1, 1, tzinfo=UTC)
        if budget["period"] == "monthly":
            now = datetime.now(UTC)
            since = datetime(now.year, now.month, 1, tzinfo=UTC)
        scope = "project_id = :project" if budget["project_id"] else "true"
        spent_rows = await self._rows(
            f"SELECT COALESCE(sum(cost_usd), 0) AS spent FROM usage_ledger WHERE {scope} AND occurred_at >= :since",  # noqa: S608 - constant condition
            since=since,
        )
        remaining = Decimal(str(budget["amount_usd"])) - Decimal(str(spent_rows[0]["spent"]))
        if budget["hard_stop"] and estimate > remaining:
            return Check("budget", False, f"estimate {estimate:.2f} USD exceeds the remaining {remaining:.2f} USD")
        return Check("budget", True, f"estimate {estimate:.2f} USD within the remaining {remaining:.2f} USD")

    async def archives(self) -> Mapping[str, bytes]:
        rows = await self._rows(
            "SELECT id, name, object_key, size_bytes FROM input_artifact WHERE project_id = :project "
            "AND kind = 'source_archive' AND status = 'accepted' AND deleted_at IS NULL ORDER BY name"
        )
        if not rows or self.object_store is None:
            return {}
        archives: dict[str, bytes] = {}
        for row in rows:
            if int(row["size_bytes"] or 0) > MAX_ARCHIVE_BYTES:  # type: ignore[call-overload]
                continue
            try:
                chunks = await self.object_store.read(str(row["object_key"]))
                archives[f"{row['name']} ({uuid.UUID(str(row['id'])).hex[:8]})"] = b"".join(chunks)
            except ObjectStoreError:
                continue
        return archives
