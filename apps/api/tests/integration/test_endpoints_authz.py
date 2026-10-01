"""Every endpoint has an allowed and a denied authorization test against the real OpenFGA (M0 acceptance, rule of
CLAUDE.md), every route declares its authorization, and every sensitive action lands in the audit log."""

import hashlib
import io
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import (
    AppUser,
    AuditLog,
    Budget,
    EffortMapping,
    InputArtifact,
    Invitation,
    Membership,
    ModelAssignment,
    ModelFamily,
    ModelOffering,
    ModelProfile,
    ModelVersion,
    PlatformRoleAssignment,
    PriceVersion,
    Project,
    ProjectRepository,
    ProviderConnection,
    Role,
    RoleAssignment,
    UsageLedger,
)
from nexti_core.object_store import ObjectStore, ObjectStoreConfig, input_key
from nexti_model_gateway.secrets import SecretsConfig, SecretStore, connection_path

from .conftest import SETTINGS, World
from .run_support import (
    VALID_CRITERION,
    execute,
    make_config,
    make_project,
    make_run,
    seed_architecture,
    seed_graph,
    seed_proposal,
    seed_screens,
    seed_spec,
    seed_validation,
)

# Routes that are public by design (no session): health, the sign-in flow and dev-auth (development only).
PUBLIC = {
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/auth/login"),
    ("GET", "/auth/callback"),
    ("GET", "/auth/dev/users"),
    ("POST", "/auth/dev/login"),
}
# Mutations that are not sensitive actions and therefore not audited; projects:compose is a POST that saves nothing.
NOT_AUDITED = {("PATCH", "/api/v1/me"), ("POST", "/api/v1/projects:compose"), ("POST", "/api/v1/gherkin:validate")}

# OpenRouter is simulated in these tests (shapes recorded from the real API, packages/model_gateway/tests).
OPENROUTER = "https://openrouter.test/api/v1"
MODEL = "openai/gpt-4o-mini"
MODEL_INFO: dict[str, Any] = {
    "id": MODEL,
    "canonical_slug": MODEL,
    "name": "OpenAI: GPT-4o-mini",
    "context_length": 128000,
    "architecture": {"input_modalities": ["text"]},
    "supported_parameters": ["max_tokens", "temperature"],
}
ENDPOINTS: dict[str, Any] = {
    "data": {
        "id": MODEL,
        "endpoints": [
            {
                "tag": "openai",
                "provider_name": "OpenAI",
                "context_length": 128000,
                "max_completion_tokens": 16384,
                "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                "status": 0,
            }
        ],
    }
}
CHAT: dict[str, Any] = {
    "id": "gen-test",
    "model": MODEL,
    "provider": "OpenAI",
    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 13, "completion_tokens": 1, "cost": 2.55e-06},
}


def authz_marker(route: APIRoute) -> tuple[str, str] | None:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        marker = getattr(dep.call, "__authz__", None)
        if marker:
            return marker  # type: ignore[no-any-return]
        stack.extend(dep.dependencies)
    return None


def _flatten(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    # Recent FastAPI wraps included routers (_IncludedRouter) instead of copying their routes into app.routes.
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            extra = getattr(route.include_context, "prefix", "") or ""
            yield from _flatten(route.original_router.routes, prefix + extra)


def api_routes(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    found = {(method, path): route for path, route in _flatten(app.routes) for method in route.methods or ()}
    # Guard against a silent pass: the app has dozens of routes.
    assert len(found) > 20, f"route discovery found only {len(found)} routes"
    return found


@dataclass
class Ctx:
    world: World
    root: uuid.UUID
    owner: AsyncEngine
    # To publish the authorization tuples of objects made directly in the database (fresh projects).
    app: AsyncEngine | None = None
    fga: OpenFga | None = None

    async def sync_authz(self) -> None:
        if self.app is not None and self.fga is not None:
            await reconcile(self.app, self.fga)

    async def member(self) -> uuid.UUID:
        """A throwaway member of tenant A (for destructive cases)."""
        async with self.owner.begin() as conn:
            user_id: uuid.UUID = (
                await conn.execute(
                    insert(AppUser)
                    .values(email=f"m0test-{uuid.uuid4().hex[:10]}@example.test", display_name="Throwaway")
                    .returning(AppUser.id)
                )
            ).scalar_one()
            await conn.execute(insert(Membership).values(tenant_id=self.world.tenant_a, user_id=user_id))
        return user_id

    async def role(self, key: str) -> uuid.UUID:
        async with self.owner.connect() as conn:
            found: uuid.UUID = (
                await conn.execute(select(Role.id).where(Role.tenant_id == self.world.tenant_a, Role.key == key))
            ).scalar_one()
        return found

    async def custom_role(self) -> uuid.UUID:
        async with self.owner.begin() as conn:
            role_id: uuid.UUID = (
                await conn.execute(
                    insert(Role)
                    .values(tenant_id=self.world.tenant_a, key=f"r{uuid.uuid4().hex[:10]}", scope="tenant", name="Tmp")
                    .returning(Role.id)
                )
            ).scalar_one()
        return role_id

    async def invitation(self) -> uuid.UUID:
        role_id = await self.role("auditor")
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(Invitation)
                    .values(
                        tenant_id=self.world.tenant_a,
                        email=f"m0test-{uuid.uuid4().hex[:10]}@example.test",
                        role_id=role_id,
                        role_scope="tenant",
                        invited_by=self.world.a_user,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    .returning(Invitation.id)
                )
            ).scalar_one()
        return found

    async def assignment(self) -> uuid.UUID:
        user_id = await self.member()
        role_id = await self.role("finance")
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(RoleAssignment)
                    .values(tenant_id=self.world.tenant_a, user_id=user_id, role_id=role_id, scope="tenant")
                    .returning(RoleAssignment.id)
                )
            ).scalar_one()
        return found

    async def model_version(self) -> uuid.UUID:
        """A catalog model (global) with one priced offering, so profiles can use it."""
        return (await self.offering())[0]

    async def offering(self) -> tuple[uuid.UUID, uuid.UUID]:
        tag = uuid.uuid4().hex[:8]
        async with self.owner.begin() as conn:
            family = (
                await conn.execute(
                    insert(ModelFamily).values(key=f"f-{tag}", name="Test family").returning(ModelFamily.id)
                )
            ).scalar_one()
            slug = f"{MODEL}-{tag}"
            version: uuid.UUID = (
                await conn.execute(
                    insert(ModelVersion)
                    .values(family_id=family, provider_slug=slug, canonical_slug=slug, name="GPT-4o-mini")
                    .returning(ModelVersion.id)
                )
            ).scalar_one()
            offering: uuid.UUID = (
                await conn.execute(
                    insert(ModelOffering)
                    .values(version_id=version, provider="openrouter", upstream_provider="openai", zdr=False)
                    .returning(ModelOffering.id)
                )
            ).scalar_one()
            await conn.execute(
                insert(PriceVersion).values(
                    offering_id=offering,
                    input_per_mtok=Decimal("0.15"),
                    output_per_mtok=Decimal("0.60"),
                    source="provider_sync",
                )
            )
            await conn.execute(
                insert(EffortMapping).values(
                    offering_id=offering, effort="medium", parameters={"reasoning": {"effort": "medium"}}
                )
            )
        return version, offering

    async def connection(self, tenant_id: uuid.UUID | None = None, api_key: str = "sk-or-v1-test") -> uuid.UUID:
        """An OpenRouter connection whose key is in OpenBao (the database holds only the path)."""
        tenant_id = tenant_id or self.world.tenant_a
        connection_id = uuid.uuid4()
        path = connection_path(tenant_id, connection_id)
        async with httpx.AsyncClient(timeout=10) as http:
            await SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http).put(
                path, api_key
            )
        async with self.owner.begin() as conn:
            await conn.execute(
                insert(ProviderConnection).values(
                    id=connection_id, tenant_id=tenant_id, provider="openrouter", name=f"OR {connection_id.hex[:8]}",
                    vault_path=path,
                )
            )  # fmt: skip
        return connection_id

    async def profile(self, tenant_id: uuid.UUID | None = None) -> uuid.UUID:
        tenant_id = tenant_id or self.world.tenant_a
        connection_id = await self.connection(tenant_id)
        _, offering = await self.offering()
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(ModelProfile)
                    .values(
                        tenant_id=tenant_id, name=f"P {uuid.uuid4().hex[:8]}", connection_id=connection_id,
                        offering_id=offering, max_output_tokens=256,
                    )
                    .returning(ModelProfile.id)
                )
            ).scalar_one()  # fmt: skip
        return found

    async def project(self, tenant_id: uuid.UUID | None = None) -> uuid.UUID:
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(Project)
                    .values(tenant_id=tenant_id or self.world.tenant_a, name=f"Budget {uuid.uuid4().hex[:6]}")
                    .returning(Project.id)
                )
            ).scalar_one()
        return found

    async def stored_input(self, kind: str = "screenshot") -> uuid.UUID:
        """An accepted input of project A with its object in MinIO (a small PNG)."""
        input_id = uuid.uuid4()
        key = input_key(self.world.tenant_a, self.world.project_a, input_id)
        await object_store().put(key, io.BytesIO(PNG), len(PNG), "image/png")
        async with self.owner.begin() as conn:
            await conn.execute(
                insert(InputArtifact).values(
                    id=input_id, tenant_id=self.world.tenant_a, project_id=self.world.project_a, kind=kind,
                    name=f"shot-{input_id.hex[:6]}.png", version=1, status="accepted", object_key=key,
                    size_bytes=len(PNG), sha256=hashlib.sha256(PNG).hexdigest(), content_type="image/png",
                )
            )  # fmt: skip
        return input_id

    async def repository(self) -> uuid.UUID:
        """Project A with a repository configured (no token)."""
        async with self.owner.begin() as conn:
            await conn.execute(
                pg_insert(ProjectRepository)
                .values(tenant_id=self.world.tenant_a, project_id=self.world.project_a, url=REPOSITORY_URL)
                .on_conflict_do_nothing()
            )
        return self.world.project_a

    async def budget(self, tenant_id: uuid.UUID | None = None) -> uuid.UUID:
        """A project budget (one per scope and period, so each gets its own project)."""
        tenant_id = tenant_id or self.world.tenant_a
        project_id = await self.project(tenant_id)
        async with self.owner.begin() as conn:
            found: uuid.UUID = (
                await conn.execute(
                    insert(Budget)
                    .values(tenant_id=tenant_id, project_id=project_id, period="monthly", amount_usd=Decimal(100))
                    .returning(Budget.id)
                )
            ).scalar_one()
        return found

    async def run_project(self) -> tuple[uuid.UUID, uuid.UUID]:
        """A project of tenant A with a configuration and a run waiting at C1 with an open question, launched by
        someone other than the admin (who then may decide its gates)."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        await self.sync_authz()
        version = await make_config(self.owner, self.world.tenant_a, project_id)
        run_id = await make_run(self.owner, self.world.tenant_a, project_id, version, started_by=self.world.shared)
        async with self.owner.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE run SET status = 'waiting', waiting_reason = 'gate', current_phase = 'ruleReview' "
                    "WHERE id = :r"
                ),
                {"r": run_id},
            )
            await conn.execute(
                text("INSERT INTO gate (tenant_id, run_id, gate, required) VALUES (:t, :r, 'C1', true)"),
                {"t": self.world.tenant_a, "r": run_id},
            )
        return project_id, run_id

    async def question(self) -> tuple[uuid.UUID, uuid.UUID]:
        project_id, run_id = await self.run_project()
        async with self.owner.begin() as conn:
            question_id: uuid.UUID = (
                await conn.execute(
                    text(
                        "INSERT INTO question (tenant_id, project_id, run_id, phase, agent_key, question_text, "
                        "reason, impact, recommended, alternatives) VALUES (:t, :p, :r, 'inventory', "
                        "'legacy-analyst', 'Which rounding?', 'contradiction', 'low', "
                        '\'{"key": "halfUp", "label": "Half up"}\', '
                        '\'[{"key": "bankers", "label": "Bankers"}]\') RETURNING id'
                    ),
                    {"t": self.world.tenant_a, "p": project_id, "r": run_id},
                )
            ).scalar_one()
        return project_id, question_id

    async def event(self) -> int:
        project_id, run_id = await self.run_project()
        async with self.owner.begin() as conn:
            event_id: int = (
                await conn.execute(
                    text(
                        "INSERT INTO activity_event (tenant_id, project_id, run_id, kind, status, message) "
                        "VALUES (:t, :p, :r, 'info', 'running', 'Preflight started') RETURNING id"
                    ),
                    {"t": self.world.tenant_a, "p": project_id, "r": run_id},
                )
            ).scalar_one()
        return event_id

    async def screens_project(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """A fresh project of tenant A with screens, the design system, a prototype, a comment on it and a chat
        proposal to change its spec."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        prototype_id = await seed_screens(self.owner, object_store(), self.world.tenant_a, project_id)
        async with self.owner.begin() as conn:
            comment_id: uuid.UUID = (
                await conn.execute(
                    text("INSERT INTO prototype_comment (tenant_id, project_id, prototype_id, body) "
                         "VALUES (:t, :p, :id, 'A comment') RETURNING id"),
                    {"t": self.world.tenant_a, "p": project_id, "id": prototype_id},
                )
            ).scalar_one()  # fmt: skip
        proposal_id = await seed_proposal(self.owner, self.world.tenant_a, project_id)
        await self.sync_authz()
        return project_id, comment_id, proposal_id

    async def graph_project(self) -> uuid.UUID:
        """A fresh project of tenant A with the fictitious CICS application in the knowledge graph."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        await seed_graph(self.owner, SETTINGS, self.world.tenant_a, project_id)
        await self.sync_authz()
        return project_id

    async def verified_project(self) -> tuple[uuid.UUID, uuid.UUID]:
        """A fresh project of tenant A with rules, generated code and a verdict with its proof pack."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        await seed_spec(self.owner, self.world.tenant_a, project_id)
        verdict_id = await seed_validation(self.owner, object_store(), self.world.tenant_a, project_id)
        await self.sync_authz()
        return project_id, verdict_id

    async def architecture_project(self) -> uuid.UUID:
        """A fresh project of tenant A with the design of the fictitious application and its OpenAPI document."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        await seed_architecture(self.owner, object_store(), self.world.tenant_a, project_id)
        await self.sync_authz()
        return project_id

    async def spec_project(self) -> uuid.UUID:
        """A fresh project of tenant A with rules, stories (US-003 discarded), dependencies and a plan."""
        project_id = await make_project(self.owner, self.world.tenant_a)
        await seed_spec(self.owner, self.world.tenant_a, project_id)
        await execute(
            self.owner,
            "INSERT INTO user_story_version (tenant_id, story_id, version, title, criteria, links, status, reason, "
            "action) SELECT tenant_id, story_id, 2, title, criteria, links, 'discarded', 'Not needed', 'discard' "
            "FROM user_story_version WHERE title = 'Story 3' AND version = 1 AND story_id IN "
            "(SELECT id FROM user_story WHERE project_id = :p)",
            p=project_id,
        )
        await self.sync_authz()
        return project_id


@dataclass(frozen=True)
class Upload:
    """A multipart body (file uploads)."""

    files: dict[str, tuple[str, bytes, str]]
    data: dict[str, str]


Request = tuple[str, dict[str, Any] | Upload | None]


def send(api: TestClient, method: str, path: str, body: dict[str, Any] | Upload | None, headers: dict[str, str]) -> Any:
    if isinstance(body, Upload):
        return api.request(method, path, files=body.files, data=body.data, headers=headers)
    return api.request(method, path, json=body, headers=headers)


@dataclass(frozen=True)
class Case:
    """How to call one route, who may and who may not. `allowed`/`denied` name users of the context."""

    method: str
    path: str
    allowed: str
    denied: str
    make: Callable[[Ctx], Awaitable[Request]]


def fixed(path: str, body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        return path.format(a=ctx.world.tenant_a, shared=ctx.world.shared, project_a=ctx.world.project_a), body

    return make


async def _new_tenant(ctx: Ctx) -> Request:
    return "/api/v1/tenants", {"slug": f"t-{uuid.uuid4().hex[:10]}", "name": "New tenant"}


async def _patch_member(ctx: Ctx) -> Request:
    return f"/api/v1/users/{await ctx.member()}", {"status": "suspended"}


async def _remove_member(ctx: Ctx) -> Request:
    return f"/api/v1/users/{await ctx.member()}/membership", None


async def _invite(ctx: Ctx) -> Request:
    email = f"m0test-{uuid.uuid4().hex[:10]}@example.test"
    return "/api/v1/invitations", {"email": email, "roleId": str(await ctx.role("auditor"))}


async def _resend(ctx: Ctx) -> Request:
    return f"/api/v1/invitations/{await ctx.invitation()}:resend", None


async def _revoke(ctx: Ctx) -> Request:
    return f"/api/v1/invitations/{await ctx.invitation()}", None


async def _new_role(ctx: Ctx) -> Request:
    return "/api/v1/roles", {"key": f"r{uuid.uuid4().hex[:10]}", "name": "Reviewer", "scope": "tenant"}


async def _rename_role(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}", {"name": "Renamed"}


async def _delete_role(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}", None


async def _role_permissions(ctx: Ctx) -> Request:
    return f"/api/v1/roles/{await ctx.custom_role()}/permissions", {"permissions": ["audit.view"]}


async def _assign(ctx: Ctx) -> Request:
    return "/api/v1/role-assignments", {"userId": str(await ctx.member()), "roleId": str(await ctx.role("auditor"))}


async def _unassign(ctx: Ctx) -> Request:
    return f"/api/v1/role-assignments/{await ctx.assignment()}", None


def _with(helper: str, template: str, body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    """A path with the id of a fresh object made by `Ctx.<helper>()`."""

    async def make(ctx: Ctx) -> Request:
        return template.format(id=await getattr(ctx, helper)()), body

    return make


async def _offering_path(ctx: Ctx, suffix: str) -> str:
    return f"/api/v1/ai/offerings/{(await ctx.offering())[1]}/{suffix}"


async def _new_connection(ctx: Ctx) -> Request:
    return "/api/v1/ai/connections", {"name": f"OR {uuid.uuid4().hex[:8]}", "apiKey": "sk-or-v1-test-new"}


async def _profile_body(ctx: Ctx) -> dict[str, Any]:
    _, offering = await ctx.offering()
    return {
        "name": f"P {uuid.uuid4().hex[:8]}",
        "connectionId": str(await ctx.connection()),
        "offeringId": str(offering),
        "maxOutputTokens": 512,
    }


async def _new_profile(ctx: Ctx) -> Request:
    return "/api/v1/ai/profiles", await _profile_body(ctx)


async def _edit_profile(ctx: Ctx) -> Request:
    return f"/api/v1/ai/profiles/{await ctx.profile()}", await _profile_body(ctx)


async def _get_effort(ctx: Ctx) -> Request:
    return await _offering_path(ctx, "effort-mapping"), None


async def _set_effort(ctx: Ctx) -> Request:
    return await _offering_path(ctx, "effort-mapping"), {"parameters": {"high": {"reasoning": {"effort": "high"}}}}


async def _get_prices(ctx: Ctx) -> Request:
    return await _offering_path(ctx, "prices"), None


async def _add_price(ctx: Ctx) -> Request:
    return await _offering_path(ctx, "prices"), {"inputPerMtok": "0.2", "outputPerMtok": "0.8"}


async def _set_assignment(ctx: Ctx) -> Request:
    return "/api/v1/ai/assignments", {"phase": "design", "agentRole": None, "profileId": str(await ctx.profile())}


async def _new_budget(ctx: Ctx) -> Request:
    return "/api/v1/budgets", {"projectId": str(await ctx.project()), "amountUsd": "50", "alertPct": 75}


REPOSITORY_URL = "https://git.bank.example/cards/card-system.git"  # .example never resolves: the test fails softly


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "PNG")
    return buffer.getvalue()


PNG = _png()


def object_store() -> ObjectStore:
    return ObjectStore(
        ObjectStoreConfig(
            SETTINGS.object_store_url, SETTINGS.object_store_access_key,
            SETTINGS.object_store_secret_key.get_secret_value(), SETTINGS.object_store_bucket,
        )
    )  # fmt: skip


async def _upload(ctx: Ctx) -> Request:
    body = Upload({"file": (f"login-{uuid.uuid4().hex[:6]}.png", PNG, "image/png")}, {"kind": "screenshot"})
    return f"/api/v1/projects/{ctx.world.project_a}/inputs", body


async def _content(ctx: Ctx) -> Request:
    return f"/api/v1/projects/{ctx.world.project_a}/inputs/{await ctx.stored_input()}/content", None


async def _delete_input(ctx: Ctx) -> Request:
    return f"/api/v1/projects/{ctx.world.project_a}/inputs/{await ctx.stored_input()}", None


TARGET = {"architecture": "microservices-hexagonal", "backend": "spring-boot", "frontend": "angular",
          "database": "postgresql", "cloud": "aws"}  # fmt: skip
COMPOSE = {"flow": "modernization", "sources": ["cobol-cics", "bms"], "target": TARGET}
CONFIG = {"sources": ["cobol-cics", "bms"], "target": TARGET, "pipelineTemplate": "bankStandard"}


async def _new_project(ctx: Ctx) -> Request:
    return "/api/v1/projects", {**CONFIG, "name": f"Project {uuid.uuid4().hex[:8]}", "flow": "modernization"}


async def _new_run(ctx: Ctx) -> Request:
    project_id = await make_project(ctx.owner, ctx.world.tenant_a)
    await ctx.sync_authz()
    await make_config(ctx.owner, ctx.world.tenant_a, project_id)
    return f"/api/v1/projects/{project_id}/runs", {"kind": "pipeline"}


def _run_path(suffix: str = "", body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        project_id, run_id = await ctx.run_project()
        return f"/api/v1/projects/{project_id}/runs/{run_id}{suffix}", body

    return make


async def _runs(ctx: Ctx) -> Request:
    project_id, _ = await ctx.run_project()
    return f"/api/v1/projects/{project_id}/runs", None


async def _questions(ctx: Ctx) -> Request:
    project_id, _ = await ctx.question()
    return f"/api/v1/projects/{project_id}/questions", None


async def _answer(ctx: Ctx) -> Request:
    project_id, question_id = await ctx.question()
    return f"/api/v1/projects/{project_id}/questions/{question_id}:answer", {"option": "bankers"}


async def _accept(ctx: Ctx) -> Request:
    project_id, _ = await ctx.question()
    return f"/api/v1/projects/{project_id}/questions:accept-recommended", {}


async def _export(ctx: Ctx) -> Request:
    return f"/api/v1/activity/events/{await ctx.event()}/export", None


def _spec(suffix: str, body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        return f"/api/v1/projects/{await ctx.spec_project()}{suffix}", body

    return make


def _screens(suffix: str, body: dict[str, Any] | None = None) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        project_id, comment_id, proposal_id = await ctx.screens_project()
        return f"/api/v1/projects/{project_id}{suffix.format(comment=comment_id, proposal=proposal_id)}", body

    return make


async def _edit_screen(ctx: Ctx) -> Request:
    project_id, _, _ = await ctx.screens_project()
    async with ctx.owner.connect() as conn:
        data: dict[str, Any] = (
            await conn.execute(
                text("SELECT data FROM spec_element WHERE project_id = :p AND key = 'SCR-PAGORES'"), {"p": project_id}
            )
        ).scalar_one()
    return f"/api/v1/projects/{project_id}/screens/SCR-PAGORES", {**data, "name": "Resultado"}


def _graph(suffix: str) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        return f"/api/v1/projects/{await ctx.graph_project()}{suffix}", None

    return make


def _verified(suffix: str) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        project_id, verdict_id = await ctx.verified_project()
        return f"/api/v1/projects/{project_id}{suffix.format(verdict=verdict_id)}", None

    return make


def _architecture(suffix: str) -> Callable[[Ctx], Awaitable[Request]]:
    async def make(ctx: Ctx) -> Request:
        return f"/api/v1/projects/{await ctx.architecture_project()}{suffix}", None

    return make


PROTO = "/api/v1/projects/{project_id}/screens/{key}/prototypes/{version}"
UI_CHAT = "/api/v1/projects/{project_id}/screens/{key}/chat"
STORY = {"title": "Pay an order", "criteria": [VALID_CRITERION], "links": ["RULE-001"]}

AI_POLICY = {"openrouterAllowed": True, "deniedUpstreamProviders": ["deepinfra"], "denyDataCollection": True}


# allowed/denied: "root" super administrator; "admin" tenant admin of A; "member" plain member of A (architect in
# project A); "outsider" a user of tenant B only; "anonymous" no session.
CASES = [
    Case("GET", "/api/v1/tenants", "root", "admin", fixed("/api/v1/tenants")),
    Case("POST", "/api/v1/tenants", "root", "admin", _new_tenant),
    Case("GET", "/api/v1/tenants/{tenant_id}", "root", "admin", fixed("/api/v1/tenants/{a}")),
    Case("PATCH", "/api/v1/tenants/{tenant_id}", "root", "admin", fixed("/api/v1/tenants/{a}", {"name": "Andes Bank"})),
    Case("GET", "/api/v1/users", "admin", "member", fixed("/api/v1/users")),
    Case("GET", "/api/v1/users/{user_id}", "admin", "member", fixed("/api/v1/users/{shared}")),
    Case("PATCH", "/api/v1/users/{user_id}", "admin", "member", _patch_member),
    Case("DELETE", "/api/v1/users/{user_id}/membership", "admin", "member", _remove_member),
    Case("GET", "/api/v1/invitations", "admin", "member", fixed("/api/v1/invitations")),
    Case("POST", "/api/v1/invitations", "admin", "member", _invite),
    Case("POST", "/api/v1/invitations/{invitation_id}:resend", "admin", "member", _resend),
    Case("DELETE", "/api/v1/invitations/{invitation_id}", "admin", "member", _revoke),
    Case("GET", "/api/v1/permissions", "member", "anonymous", fixed("/api/v1/permissions")),
    Case("GET", "/api/v1/roles", "admin", "member", fixed("/api/v1/roles")),
    Case("POST", "/api/v1/roles", "admin", "member", _new_role),
    Case("PATCH", "/api/v1/roles/{role_id}", "admin", "member", _rename_role),
    Case("DELETE", "/api/v1/roles/{role_id}", "admin", "member", _delete_role),
    Case("PUT", "/api/v1/roles/{role_id}/permissions", "admin", "member", _role_permissions),
    Case("GET", "/api/v1/role-assignments", "admin", "member", fixed("/api/v1/role-assignments")),
    Case("POST", "/api/v1/role-assignments", "admin", "member", _assign),
    Case("DELETE", "/api/v1/role-assignments/{assignment_id}", "admin", "member", _unassign),
    Case("GET", "/api/v1/projects", "member", "root", fixed("/api/v1/projects")),
    Case("GET", "/api/v1/audit", "admin", "member", fixed("/api/v1/audit")),
    Case("GET", "/api/v1/audit/export", "admin", "member", fixed("/api/v1/audit/export")),
    Case("GET", "/api/v1/audit/verify", "admin", "member", fixed("/api/v1/audit/verify")),
    Case("GET", "/api/v1/me", "member", "anonymous", fixed("/api/v1/me")),
    Case("PATCH", "/api/v1/me", "member", "anonymous", fixed("/api/v1/me", {"locale": "en"})),
    Case("PUT", "/api/v1/session/tenant", "member", "anonymous", fixed("/api/v1/session/tenant", None)),
    Case("POST", "/auth/logout", "member", "anonymous", fixed("/auth/logout")),
    # AI configuration (M1): models.configure; the global effort table and manual prices are SuperAdmin's.
    Case("GET", "/api/v1/ai/connections", "admin", "member", fixed("/api/v1/ai/connections")),
    Case("POST", "/api/v1/ai/connections", "admin", "member", _new_connection),
    Case(
        "PATCH",
        "/api/v1/ai/connections/{connection_id}",
        "admin",
        "member",
        _with("connection", "/api/v1/ai/connections/{id}", {"name": "Renamed", "apiKey": "sk-or-v1-rotated"}),
    ),
    Case(
        "DELETE",
        "/api/v1/ai/connections/{connection_id}",
        "admin",
        "member",
        _with("connection", "/api/v1/ai/connections/{id}"),
    ),
    Case(
        "POST",
        "/api/v1/ai/connections/{connection_id}:test",
        "admin",
        "member",
        _with("connection", "/api/v1/ai/connections/{id}:test"),
    ),
    Case("GET", "/api/v1/ai/catalog", "admin", "member", fixed("/api/v1/ai/catalog")),
    Case("POST", "/api/v1/ai/catalog:sync", "admin", "member", fixed("/api/v1/ai/catalog:sync")),
    Case(
        "POST",
        "/api/v1/ai/catalog/versions/{version_id}:load-offerings",
        "admin",
        "member",
        _with("model_version", "/api/v1/ai/catalog/versions/{id}:load-offerings"),
    ),
    Case("GET", "/api/v1/ai/offerings/{offering_id}/effort-mapping", "admin", "member", _get_effort),
    Case("PUT", "/api/v1/ai/offerings/{offering_id}/effort-mapping", "root", "admin", _set_effort),
    Case("GET", "/api/v1/ai/offerings/{offering_id}/prices", "admin", "member", _get_prices),
    Case("POST", "/api/v1/ai/offerings/{offering_id}/prices", "root", "admin", _add_price),
    Case("GET", "/api/v1/ai/profiles", "admin", "member", fixed("/api/v1/ai/profiles")),
    Case("POST", "/api/v1/ai/profiles", "admin", "member", _new_profile),
    Case("PUT", "/api/v1/ai/profiles/{profile_id}", "admin", "member", _edit_profile),
    Case("DELETE", "/api/v1/ai/profiles/{profile_id}", "admin", "member", _with("profile", "/api/v1/ai/profiles/{id}")),
    Case(
        "POST",
        "/api/v1/ai/profiles/{profile_id}:test",
        "admin",
        "member",
        _with("profile", "/api/v1/ai/profiles/{id}:test"),
    ),
    Case("GET", "/api/v1/ai/assignment-options", "admin", "member", fixed("/api/v1/ai/assignment-options")),
    Case("GET", "/api/v1/ai/assignments", "admin", "member", fixed("/api/v1/ai/assignments")),
    Case("PUT", "/api/v1/ai/assignments", "admin", "member", _set_assignment),
    Case("GET", "/api/v1/ai/assignments:resolve", "admin", "member", fixed("/api/v1/ai/assignments:resolve")),
    Case("GET", "/api/v1/ai/policy", "admin", "member", fixed("/api/v1/ai/policy")),
    Case("PUT", "/api/v1/ai/policy", "admin", "member", fixed("/api/v1/ai/policy", AI_POLICY)),
    # Usage and costs (M1): tokens with usage.view, money with cost.view, budgets set with models.configure.
    Case("GET", "/api/v1/usage/summary", "admin", "member", fixed("/api/v1/usage/summary?groupBy=phase")),
    Case("GET", "/api/v1/budgets", "admin", "member", fixed("/api/v1/budgets")),
    Case("POST", "/api/v1/budgets", "admin", "member", _new_budget),
    Case(
        "PUT",
        "/api/v1/budgets/{budget_id}",
        "admin",
        "member",
        _with("budget", "/api/v1/budgets/{id}", {"amountUsd": "80", "alertPct": 90, "hardStop": False}),
    ),
    Case("DELETE", "/api/v1/budgets/{budget_id}", "admin", "member", _with("budget", "/api/v1/budgets/{id}")),
    # Projects and catalog (M2).
    Case("GET", "/api/v1/catalog", "member", "anonymous", fixed("/api/v1/catalog")),
    Case(
        "GET", "/api/v1/catalog/skills/{skill_key}", "member", "anonymous", fixed("/api/v1/catalog/skills/bms-parsing")
    ),
    Case("POST", "/api/v1/projects:compose", "member", "anonymous", fixed("/api/v1/projects:compose", COMPOSE)),
    Case("POST", "/api/v1/projects", "admin", "member", _new_project),
    Case("GET", "/api/v1/projects/{project_id}", "member", "outsider", fixed("/api/v1/projects/{project_a}")),
    Case(
        "PATCH", "/api/v1/projects/{project_id}", "admin", "member",
        fixed("/api/v1/projects/{project_a}", {"description": "Cards, CICS to Spring Boot."}),
    ),
    Case(
        "PUT", "/api/v1/projects/{project_id}/config", "admin", "member",
        fixed("/api/v1/projects/{project_a}/config", CONFIG),
    ),
    Case(
        "GET", "/api/v1/projects/{project_id}/config/versions", "member", "outsider",
        fixed("/api/v1/projects/{project_a}/config/versions"),
    ),
    Case(
        "GET", "/api/v1/projects/{project_id}/inputs", "member", "outsider",
        fixed("/api/v1/projects/{project_a}/inputs"),
    ),
    Case("POST", "/api/v1/projects/{project_id}/inputs", "admin", "member", _upload),
    Case(
        "POST", "/api/v1/projects/{project_id}/inputs:link", "admin", "member",
        fixed("/api/v1/projects/{project_a}/inputs:link",
              {"kind": "figma_link", "url": "https://www.figma.com/design/AbCdEf1234567890/Cards"}),
    ),
    Case("GET", "/api/v1/projects/{project_id}/inputs/{input_id}/content", "member", "outsider", _content),
    Case("DELETE", "/api/v1/projects/{project_id}/inputs/{input_id}", "admin", "member", _delete_input),
    Case(
        "GET", "/api/v1/projects/{project_id}/repository", "member", "outsider",
        fixed("/api/v1/projects/{project_a}/repository"),
    ),
    Case(
        "PUT", "/api/v1/projects/{project_id}/repository", "admin", "member",
        fixed("/api/v1/projects/{project_a}/repository", {"url": REPOSITORY_URL, "branch": "main"}),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/repository:test", "admin", "member",
        _with("repository", "/api/v1/projects/{id}/repository:test"),
    ),
    Case(
        "DELETE", "/api/v1/projects/{project_id}/repository", "admin", "member",
        _with("repository", "/api/v1/projects/{id}/repository"),
    ),
    # Runs, gates, questions, tasks and activity (M3). Fresh projects: only the tenant admin sees them.
    Case("GET", "/api/v1/projects/{project_id}/runs", "admin", "outsider", _runs),
    Case("POST", "/api/v1/projects/{project_id}/runs", "admin", "member", _new_run),
    Case("GET", "/api/v1/projects/{project_id}/runs/{run_id}", "admin", "outsider", _run_path()),
    Case("POST", "/api/v1/projects/{project_id}/runs/{run_id}:cancel", "admin", "member", _run_path(":cancel")),
    Case(
        "POST", "/api/v1/projects/{project_id}/runs/{run_id}/gates/{gate}:approve", "admin", "member",
        _run_path("/gates/C1:approve", {}),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/runs/{run_id}/gates/{gate}:reject", "admin", "member",
        _run_path("/gates/C1:reject", {"comment": "Rules incomplete"}),
    ),
    Case(
        "GET", "/api/v1/projects/{project_id}/runs/{run_id}/events", "admin", "outsider",
        _run_path("/events?follow=false"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/questions", "admin", "outsider", _questions),
    Case("POST", "/api/v1/projects/{project_id}/questions/{question_id}:answer", "admin", "member", _answer),
    Case("POST", "/api/v1/projects/{project_id}/questions:accept-recommended", "admin", "member", _accept),
    Case("GET", "/api/v1/tasks", "member", "anonymous", fixed("/api/v1/tasks")),
    Case("GET", "/api/v1/activity/events", "member", "anonymous", fixed("/api/v1/activity/events?follow=false")),
    Case("GET", "/api/v1/activity/events/{event_id}/export", "admin", "member", _export),
    # Spec, user stories and the plan (M4).
    Case("GET", "/api/v1/projects/{project_id}/spec/rules", "admin", "outsider", _spec("/spec/rules")),
    Case(
        "GET", "/api/v1/projects/{project_id}/spec/rules/{key}/versions", "admin", "outsider",
        _spec("/spec/rules/RULE-001/versions"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/stories", "admin", "outsider", _spec("/stories")),
    Case(
        "GET", "/api/v1/projects/{project_id}/stories/{key}/versions", "admin", "outsider",
        _spec("/stories/US-001/versions"),
    ),
    Case("POST", "/api/v1/projects/{project_id}/stories", "admin", "member", _spec("/stories", STORY)),
    Case("PUT", "/api/v1/projects/{project_id}/stories/{key}", "admin", "member", _spec("/stories/US-001", STORY)),
    Case(
        "POST", "/api/v1/projects/{project_id}/stories/{key}:split", "admin", "member",
        _spec("/stories/US-001:split", {"title": "Other part", "criteria": [], "links": ["RULE-001"]}),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/stories/{key}:merge", "admin", "member",
        _spec("/stories/US-002:merge", {"into": "US-001"}),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/stories/{key}:discard", "admin", "member",
        _spec("/stories/US-001:discard", {"reason": "Not needed"}),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/stories/{key}:restore", "admin", "member",
        _spec("/stories/US-003:restore"),
    ),
    Case(
        "POST", "/api/v1/projects/{project_id}/stories/{key}/dependencies", "admin", "member",
        _spec("/stories/US-001/dependencies", {"on": "US-002", "strength": "soft"}),
    ),
    Case(
        "DELETE", "/api/v1/projects/{project_id}/stories/{key}/dependencies/{on}", "admin", "member",
        _spec("/stories/US-002/dependencies/US-001"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/coverage", "admin", "outsider", _spec("/coverage")),
    Case("GET", "/api/v1/projects/{project_id}/c1-check", "admin", "outsider", _spec("/c1-check")),
    Case(
        "POST", "/api/v1/gherkin:validate", "member", "anonymous",
        fixed("/api/v1/gherkin:validate", {"criteria": [VALID_CRITERION]}),
    ),
    Case("GET", "/api/v1/projects/{project_id}/plan", "admin", "outsider", _spec("/plan")),
    Case(
        "PUT", "/api/v1/projects/{project_id}/plan", "admin", "member",
        _spec("/plan", {"waves": [["US-001", "US-002"]]}),
    ),
    Case("POST", "/api/v1/projects/{project_id}/plan:reset", "admin", "member", _spec("/plan:reset")),
    Case("GET", "/api/v1/projects/{project_id}/screens", "admin", "outsider", _screens("/screens")),
    Case(
        "GET", "/api/v1/projects/{project_id}/screens/{key}/versions", "admin", "outsider",
        _screens("/screens/SCR-PAGOORD/versions"),
    ),
    Case("PUT", "/api/v1/projects/{project_id}/screens/{key}", "admin", "member", _edit_screen),
    Case("GET", "/api/v1/projects/{project_id}/design-system", "admin", "outsider", _screens("/design-system")),
    Case(
        "GET", "/api/v1/projects/{project_id}/screens/{key}/prototypes", "admin", "outsider",
        _screens("/screens/SCR-PAGOORD/prototypes"),
    ),
    Case("GET", PROTO + "/page", "admin", "outsider", _screens("/screens/SCR-PAGOORD/prototypes/1/page")),
    Case("GET", PROTO + "/source", "admin", "outsider", _screens("/screens/SCR-PAGOORD/prototypes/1/source")),
    Case("GET", PROTO + "/comments", "admin", "outsider", _screens("/screens/SCR-PAGOORD/prototypes/1/comments")),
    Case(
        "POST", PROTO + "/comments", "admin", "member",
        _screens("/screens/SCR-PAGOORD/prototypes/1/comments", {"body": "Looks good"}),
    ),
    Case(
        "POST", PROTO + "/comments/{comment_id}:resolve", "admin", "member",
        _screens("/screens/SCR-PAGOORD/prototypes/1/comments/{comment}:resolve", {"resolved": True}),
    ),
    Case("GET", UI_CHAT, "admin", "outsider", _screens("/screens/SCR-PAGOORD/chat")),
    Case("POST", UI_CHAT, "admin", "member", _screens("/screens/SCR-PAGOORD/chat", {"body": "Agregar un titulo"})),
    Case(
        "POST", UI_CHAT + "/{message_id}:accept", "admin", "member",
        _screens("/screens/SCR-PAGOORD/chat/{proposal}:accept"),
    ),
    Case(
        "POST", UI_CHAT + "/{message_id}:reject", "admin", "member",
        _screens("/screens/SCR-PAGOORD/chat/{proposal}:reject"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/graph", "admin", "outsider", _graph("/graph")),
    Case(
        "GET", "/api/v1/projects/{project_id}/graph/impact", "admin", "outsider",
        _graph("/graph/impact?node=copybook:ORDREG"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/verdicts", "admin", "outsider", _verified("/verdicts")),
    Case(
        "GET", "/api/v1/projects/{project_id}/verdicts/{verdict_id}/proof-pack", "admin", "outsider",
        _verified("/verdicts/{verdict}/proof-pack"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/traceability", "admin", "outsider", _verified("/traceability")),
    Case(
        "GET", "/api/v1/projects/{project_id}/traceability/{rule_key}", "admin", "outsider",
        _verified("/traceability/RULE-001"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/code", "admin", "outsider", _verified("/code")),
    Case(
        "GET", "/api/v1/projects/{project_id}/code/file", "admin", "outsider",
        _verified("/code/file?path=src/main/java/demo/PayOrderService.java"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/code:download", "admin", "outsider", _verified("/code:download")),
    Case("GET", "/api/v1/projects/{project_id}/design", "admin", "outsider", _architecture("/design")),
    Case("GET", "/api/v1/dashboard", "member", "root", fixed("/api/v1/dashboard")),
    Case("GET", "/api/v1/search", "member", "root", fixed("/api/v1/search?q=payments")),
    Case("GET", "/api/v1/notifications", "member", "root", fixed("/api/v1/notifications")),
    Case(
        "GET", "/api/v1/projects/{project_id}/usage", "admin", "outsider",
        fixed("/api/v1/projects/{project_a}/usage"),
    ),
    Case("GET", "/api/v1/projects/{project_id}/contracts", "admin", "outsider", _architecture("/contracts")),
]  # fmt: skip


@pytest.fixture(scope="module")
async def root(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        user_id: uuid.UUID = (
            await conn.execute(
                insert(AppUser)
                .values(email=f"m0test-root-{uuid.uuid4().hex[:6]}@example.test", display_name="Root")
                .returning(AppUser.id)
            )
        ).scalar_one()
        await conn.execute(insert(PlatformRoleAssignment).values(user_id=user_id, role="superAdmin"))
    return user_id


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    settings = api_settings.model_copy(update={"dev_auth_enabled": True, "openrouter_url": OPENROUTER})
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


@pytest.fixture(autouse=True)
def openrouter() -> Iterator[respx.MockRouter]:
    """OpenRouter simulated (recorded response shapes); every other host (OpenBao, OpenFGA...) is real."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{OPENROUTER}/models").respond(json={"data": [MODEL_INFO]})
        router.get(url__regex=rf"^{OPENROUTER}/models/.+/endpoints$").respond(json=ENDPOINTS)
        router.get(f"{OPENROUTER}/endpoints/zdr").respond(json={"data": []})
        router.get(f"{OPENROUTER}/key").respond(
            json={"data": {"label": "sk-or-v1-...", "limit": None, "is_free_tier": False}}
        )
        router.post(f"{OPENROUTER}/chat/completions").respond(json=CHAT)
        router.route().pass_through()
        yield router


def act_as(api: TestClient, who: str, ctx: Ctx) -> dict[str, str]:
    """Sign in (dev-auth) and return the headers a browser would send on a mutation."""
    api.cookies.clear()
    if who == "anonymous":
        return {}
    user = {"root": ctx.root, "admin": ctx.world.a_user, "member": ctx.world.shared, "outsider": ctx.world.b_user}[who]
    assert api.post("/auth/dev/login", json={"userId": str(user)}).status_code == 204
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


async def audit_count(owner: AsyncEngine) -> int:
    async with owner.connect() as conn:
        count: int = (await conn.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    return count


def test_every_route_declares_its_authorization(api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    unmarked = sorted(
        key for key, route in api_routes(app).items() if key not in PUBLIC and authz_marker(route) is None
    )
    assert unmarked == [], f"routes without an authorization dependency: {unmarked}"


def test_every_protected_route_has_an_authorization_case(api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    protected = {key for key in api_routes(app) if key not in PUBLIC}
    covered = {(c.method, c.path) for c in CASES}
    assert protected - covered == set(), "protected routes without an allowed/denied test"
    assert covered - protected == set(), "cases for routes that no longer exist"


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.method} {c.path}")
async def test_allowed_and_denied(
    case: Case,
    api: TestClient,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    fga: OpenFga,
    world: World,
    root: uuid.UUID,
) -> None:
    await reconcile(app_engine, fga)
    ctx = Ctx(world, root, owner_engine, app_engine, fga)

    headers = act_as(api, case.denied, ctx)
    path, body = await case.make(ctx)
    if case.path == "/api/v1/session/tenant":
        body = {"tenantId": str(world.tenant_a)}
    denied = send(api, case.method, path, body, headers)
    assert denied.status_code == (401 if case.denied == "anonymous" else 403), denied.text

    headers = act_as(api, case.allowed, ctx)
    path, body = await case.make(ctx)
    if case.path == "/api/v1/session/tenant":
        body = {"tenantId": str(world.tenant_a)}
    before = await audit_count(owner_engine)
    allowed = send(api, case.method, path, body, headers)
    assert allowed.status_code in (200, 201, 202, 204), allowed.text
    if case.method != "GET" and (case.method, case.path) not in NOT_AUDITED:
        assert await audit_count(owner_engine) > before, "a sensitive action left no audit entry"


async def test_an_admin_of_one_tenant_reaches_nothing_of_another(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    await reconcile(app_engine, fga)
    headers = act_as(api, "admin", Ctx(world, root, owner_engine))
    async with owner_engine.connect() as conn:
        b_role = (
            await conn.execute(select(Role.id).where(Role.tenant_id == world.tenant_b, Role.key == "projectOwner"))
        ).scalar_one()
        b_assignment = (
            (await conn.execute(select(RoleAssignment.id).where(RoleAssignment.tenant_id == world.tenant_b)))
            .scalars()
            .first()
        )
        await conn.execute(text("SELECT 1"))

    assert api.get(f"/api/v1/users/{world.b_user}").status_code == 404
    assert api.patch(f"/api/v1/users/{world.b_user}", json={"status": "suspended"}, headers=headers).status_code == 404
    assert api.delete(f"/api/v1/users/{world.b_user}/membership", headers=headers).status_code == 404
    assert str(world.b_user) not in {u["id"] for u in api.get("/api/v1/users").json()}

    assert str(b_role) not in {r["id"] for r in api.get("/api/v1/roles").json()}
    assert api.patch(f"/api/v1/roles/{b_role}", json={"name": "x"}, headers=headers).status_code == 404
    assert api.put(f"/api/v1/roles/{b_role}/permissions", json={"permissions": []}, headers=headers).status_code == 404
    assert api.delete(f"/api/v1/roles/{b_role}", headers=headers).status_code == 404

    assert api.delete(f"/api/v1/role-assignments/{b_assignment}", headers=headers).status_code == 404
    foreign_role = api.post(
        "/api/v1/role-assignments", json={"userId": str(world.shared), "roleId": str(b_role)}, headers=headers
    )
    assert foreign_role.status_code == 404
    developer = await Ctx(world, root, owner_engine).role("developer")
    foreign_project = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(world.shared), "roleId": str(developer), "projectId": str(world.project_b)},
        headers=headers,
    )
    assert foreign_project.status_code in (403, 404)

    assert str(world.project_b) not in {p["id"] for p in api.get("/api/v1/projects").json()}
    assert api.get(f"/api/v1/tenants/{world.tenant_b}").status_code == 403
    assert all(
        e["target"] is None or str(world.tenant_b) not in e["target"] for e in api.get("/api/v1/audit").json()["items"]
    )


async def test_a_project_owner_manages_the_team_of_their_project_only(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    ctx = Ctx(world, root, owner_engine)
    owner_role = await ctx.role("projectOwner")
    async with owner_engine.begin() as conn:
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=world.shared, role_id=owner_role, scope="project",
                project_id=world.project_a,
            )
        )  # fmt: skip
    await reconcile(app_engine, fga)
    headers = act_as(api, "member", ctx)
    newcomer = await ctx.member()
    developer = await ctx.role("developer")
    in_project = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(newcomer), "roleId": str(developer), "projectId": str(world.project_a)},
        headers=headers,
    )
    assert in_project.status_code == 201, in_project.text
    tenant_role = api.post(
        "/api/v1/role-assignments",
        json={"userId": str(newcomer), "roleId": str(await ctx.role("auditor"))},
        headers=headers,
    )
    assert tenant_role.status_code == 403


async def test_ai_configuration_and_usage_of_another_tenant_are_unreachable(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    await reconcile(app_engine, fga)
    ctx = Ctx(world, root, owner_engine)
    b_connection = await ctx.connection(world.tenant_b)
    b_profile = await ctx.profile(world.tenant_b)
    b_budget = await ctx.budget(world.tenant_b)
    b_model = f"b-only/{uuid.uuid4().hex[:8]}"
    async with owner_engine.begin() as conn:
        await conn.execute(insert(ModelAssignment).values(tenant_id=world.tenant_b, phase="ui", profile_id=b_profile))
        await conn.execute(
            insert(UsageLedger).values(
                tenant_id=world.tenant_b, phase="design", model=b_model, outcome="success", input_tokens=10,
                cost_usd=Decimal("0.5"),
            )
        )  # fmt: skip
    headers = act_as(api, "admin", ctx)

    assert str(b_connection) not in {c["id"] for c in api.get("/api/v1/ai/connections").json()}
    assert api.patch(f"/api/v1/ai/connections/{b_connection}", json={"name": "x"}, headers=headers).status_code == 404
    assert api.post(f"/api/v1/ai/connections/{b_connection}:test", headers=headers).status_code == 404
    assert api.delete(f"/api/v1/ai/connections/{b_connection}", headers=headers).status_code == 404

    assert str(b_profile) not in {p["id"] for p in api.get("/api/v1/ai/profiles").json()}
    body = await _profile_body(ctx)
    assert api.put(f"/api/v1/ai/profiles/{b_profile}", json=body, headers=headers).status_code == 404
    assert api.post(f"/api/v1/ai/profiles/{b_profile}:test", headers=headers).status_code == 404
    assert api.delete(f"/api/v1/ai/profiles/{b_profile}", headers=headers).status_code == 404
    foreign_connection = api.post(
        "/api/v1/ai/profiles", json={**body, "connectionId": str(b_connection)}, headers=headers
    )
    assert foreign_connection.status_code == 404
    foreign_fallback = api.post(
        "/api/v1/ai/profiles", json={**body, "fallbackProfileId": str(b_profile)}, headers=headers
    )
    assert foreign_fallback.status_code == 404

    assert all(a["profileId"] != str(b_profile) for a in api.get("/api/v1/ai/assignments").json())
    foreign_assignment = api.put(
        "/api/v1/ai/assignments", json={"phase": "ui", "profileId": str(b_profile)}, headers=headers
    )
    assert foreign_assignment.status_code == 404
    assert api.get("/api/v1/ai/assignments:resolve", params={"phase": "ui"}).json()["profileId"] != str(b_profile)

    assert str(b_budget) not in {b["id"] for b in api.get("/api/v1/budgets").json()}
    budget = {"amountUsd": "1", "alertPct": 50}
    assert api.put(f"/api/v1/budgets/{b_budget}", json=budget, headers=headers).status_code == 404
    assert api.delete(f"/api/v1/budgets/{b_budget}", headers=headers).status_code == 404
    foreign_project = api.post("/api/v1/budgets", json={**budget, "projectId": str(world.project_b)}, headers=headers)
    assert foreign_project.status_code == 404

    usage = api.get("/api/v1/usage/summary", params={"groupBy": "model"}).json()
    assert b_model not in {r["key"] for r in usage["rows"]}


async def test_the_api_key_goes_to_the_secrets_store_only(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    await reconcile(app_engine, fga)
    headers = act_as(api, "admin", Ctx(world, root, owner_engine))
    canary = f"sk-or-v1-canary-{uuid.uuid4().hex}"
    rotated = f"sk-or-v1-rotated-{uuid.uuid4().hex}"

    created = api.post("/api/v1/ai/connections", json={"name": f"OR {canary[-8:]}", "apiKey": canary}, headers=headers)
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    assert created.json()["hasCredential"] is True
    patched = api.patch(f"/api/v1/ai/connections/{connection_id}", json={"apiKey": rotated}, headers=headers)
    tested = api.post(f"/api/v1/ai/connections/{connection_id}:test", headers=headers)
    listed = api.get("/api/v1/ai/connections")
    assert tested.json()["status"] == "ok"
    for res in (created, patched, tested, listed):
        assert canary not in res.text
        assert rotated not in res.text

    # The database keeps the path only; the key is in OpenBao, where the rotation replaced it.
    async with owner_engine.connect() as conn:
        row: str = (
            await conn.execute(text("SELECT row_to_json(c)::text FROM provider_connection c WHERE id = :id"),
                               {"id": connection_id})
        ).scalar_one()  # fmt: skip
        audit_rows: str = (
            await conn.execute(text("SELECT coalesce(string_agg(details::text, ''), '') FROM audit_log"))
        ).scalar_one()
    for value in (canary, rotated):
        assert value not in row
        assert value not in audit_rows
    path = connection_path(world.tenant_a, uuid.UUID(connection_id))
    assert path in row
    async with httpx.AsyncClient(timeout=10) as http:
        store = SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http)
        assert await store.get(path) == rotated
        assert api.delete(f"/api/v1/ai/connections/{connection_id}", headers=headers).status_code == 204
        assert await store.get(path) is None


async def test_tokens_without_cost_view_come_without_money(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    ctx = Ctx(world, root, owner_engine)
    auditor = await ctx.member()
    async with owner_engine.begin() as conn:
        await conn.execute(
            insert(RoleAssignment).values(
                tenant_id=world.tenant_a, user_id=auditor, role_id=await ctx.role("auditor"), scope="tenant"
            )
        )
        await conn.execute(
            insert(UsageLedger).values(
                tenant_id=world.tenant_a, phase="verification", model=MODEL, outcome="success", input_tokens=100,
                output_tokens=20, cost_usd=Decimal("0.00004"),
            )
        )  # fmt: skip
    await reconcile(app_engine, fga)

    act_as(api, "admin", ctx)
    with_cost = api.get("/api/v1/usage/summary", params={"groupBy": "phase"}).json()
    assert with_cost["costVisible"] is True
    assert Decimal(with_cost["total"]["costUsd"]) >= Decimal("0.00004")

    api.cookies.clear()
    assert api.post("/auth/dev/login", json={"userId": str(auditor)}).status_code == 204
    tokens_only = api.get("/api/v1/usage/summary", params={"groupBy": "phase"})
    assert tokens_only.status_code == 200
    body = tokens_only.json()
    assert body["costVisible"] is False
    verification = next(r for r in body["rows"] if r["key"] == "verification")
    assert verification["inputTokens"] >= 100
    assert all(r["costUsd"] is None and r["providerCostUsd"] is None for r in [body["total"], *body["rows"]])
    assert api.get("/api/v1/budgets").status_code == 403
    project = api.get(f"/api/v1/projects/{world.project_a}/usage")
    assert project.status_code == 200
    assert project.json()["costVisible"] is False
    assert project.json()["budgetUsd"] is None
    assert project.json()["total"]["costUsd"] is None
    board = api.get("/api/v1/dashboard").json()
    assert (board["costVisible"], board["admin"], board["monthlySpend"]) == (False, None, [])
    assert all(p["spentUsd"] is None and p["budgetUsd"] is None for p in board["projects"])
    assert all(n["kind"] != "budget" for n in api.get("/api/v1/notifications").json())


async def test_the_catalog_shows_prices_and_the_tenant_policy(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World, root: uuid.UUID
) -> None:
    await reconcile(app_engine, fga)
    ctx = Ctx(world, root, owner_engine)
    version, offering = await ctx.offering()
    headers = act_as(api, "admin", ctx)
    policy = {"openrouterAllowed": True, "deniedUpstreamProviders": ["openai"], "denyDataCollection": True}
    assert api.put("/api/v1/ai/policy", json=policy, headers=headers).status_code == 200
    try:
        found = next(v for v in api.get("/api/v1/ai/catalog").json() if v["id"] == str(version))
        (offered,) = found["offerings"]
        assert offered["id"] == str(offering)
        assert Decimal(offered["price"]["inputPerMtok"]) == Decimal("0.15")
        assert offered["allowedByPolicy"] is False
        assert offered["policyReason"]
    finally:
        assert api.put("/api/v1/ai/policy", json={}, headers=headers).status_code == 200
    found = next(v for v in api.get("/api/v1/ai/catalog").json() if v["id"] == str(version))
    assert found["offerings"][0]["allowedByPolicy"] is True
