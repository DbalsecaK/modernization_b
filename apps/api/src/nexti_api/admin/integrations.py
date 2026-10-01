"""Integrations of the tenant (spec 7.1, 7.6; ADR-0018): the external tools a customer connects once for all its
projects. The token is written to the secrets store and never returned; the row keeps its path and who the token
belongs to. Figma (M7), Jira and Azure DevOps (M7b, ADR-0019) are available; Git arrives with the delivery
milestone. A Jira or Azure DevOps integration also says where the tool is (`config`: the site and account e-mail, or
the organization URL), checked to be a public https host (no SSRF)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_core.db.models import TenantIntegration
from nexti_core.secrets import SecretsConfig, SecretStore, integration_path
from nexti_ingest import Rejection
from nexti_ingest.figma import FigmaClient, FigmaError
from nexti_ingest.git import ensure_public_host
from nexti_integrations.azure_devops import AzureDevOpsTracker
from nexti_integrations.jira import JiraTracker, TrackerError

router = APIRouter(prefix="/api/v1/integrations", tags=["admin"])
ManageIntegrations = Annotated[Authorized, Depends(require_tenant("integrations.manage"))]
Kind = Literal["figma", "jira", "azure_devops", "github", "gitlab"]
AVAILABLE: tuple[Kind, ...] = ("figma", "jira", "azure_devops")
# What each kind needs in `config` (where the tool is; never a credential).
CONFIG_KEYS: dict[str, tuple[str, ...]] = {"figma": (), "jira": ("site", "email"), "azure_devops": ("organization",)}


class IntegrationOut(ApiModel):
    id: uuid.UUID
    kind: Kind
    name: str
    account: str | None
    status: Literal["untested", "ok", "failed"]
    has_token: bool
    last_tested_at: datetime | None
    last_test_detail: str | None
    config: dict[str, str] = Field(default_factory=dict)


class IntegrationCreate(ApiModel):
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    token: str = Field(min_length=8, max_length=500)
    config: dict[str, str] = Field(default_factory=dict, max_length=5)


class IntegrationUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Rotating the token: the new one replaces the old in the secrets store.
    token: str | None = Field(default=None, min_length=8, max_length=500)


def _secrets(request: Request) -> SecretStore:
    settings = request.app.state.settings
    if not settings.secrets_url:
        raise ProblemError(503, "secrets_unavailable", "The secrets store is not configured.")
    config = SecretsConfig(settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount)
    return SecretStore(config, request.app.state.resources.http)


def _out(row: Any) -> IntegrationOut:
    return IntegrationOut(
        id=row.id, kind=row.kind, name=row.name, account=row.account, status=row.status,
        has_token=row.vault_path is not None, last_tested_at=row.last_tested_at, last_test_detail=row.last_test_detail,
        config=dict(row.config or {}),
    )  # fmt: skip


async def checked_config(request: Request, kind: str, config: dict[str, str]) -> dict[str, str]:
    """The config a kind needs, its URLs on a public https host. Raises a 422 problem otherwise."""
    wanted = CONFIG_KEYS.get(kind, ())
    missing = [key for key in wanted if not str(config.get(key, "")).strip()]
    if missing:
        raise ProblemError(422, "integration_config_missing", f"The {kind} integration needs: {', '.join(missing)}.")
    clean = {key: str(config[key]).strip().rstrip("/")[:300] for key in wanted}
    settings = request.app.state.settings
    private = settings.git_allow_private_hosts and settings.is_local
    for key in ("site", "organization"):
        if key in clean:
            try:
                resolver = services.services(request).git_resolver
                await ensure_public_host(clean[key], resolver, allow_private_hosts=private)
            except Rejection as rejection:
                raise ProblemError(422, rejection.code, rejection.detail) from None
    if "email" in clean and "@" not in clean["email"]:
        raise ProblemError(422, "integration_config_invalid", "The Jira account e-mail is not valid.")
    return clean


async def _load(conn: AsyncConnection, integration_id: uuid.UUID) -> Any:
    row = (await conn.execute(select(TenantIntegration).where(TenantIntegration.id == integration_id))).first()
    if row is None:
        raise not_found("integration")
    return row


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(request: Request, auth: ManageIntegrations) -> list[IntegrationOut]:
    async with transaction(request, auth) as conn:
        rows = await conn.execute(select(TenantIntegration).order_by(TenantIntegration.kind, TenantIntegration.name))
        return [_out(r) for r in rows.all()]


@router.post("", response_model=IntegrationOut, status_code=201)
async def create_integration(request: Request, body: IntegrationCreate, auth: ManageIntegrations) -> IntegrationOut:
    assert auth.tenant_id is not None  # noqa: S101
    if body.kind not in AVAILABLE:
        raise ProblemError(422, "integration_not_available", f"The {body.kind} integration is not available yet.")
    config = await checked_config(request, body.kind, body.config)
    integration_id = uuid.uuid4()
    path = integration_path(auth.tenant_id, integration_id)
    secrets = _secrets(request)
    await secrets.put(path, body.token)
    try:
        async with transaction(request, auth) as conn:
            await conn.execute(insert(TenantIntegration).values(
                id=integration_id, tenant_id=auth.tenant_id, kind=body.kind, name=body.name, vault_path=path,
                config=config, created_by=auth.user_id,
            ))  # fmt: skip
            await audit(conn, auth, "integration.create", f"integration:{integration_id}",
                        {"kind": body.kind, "name": body.name})  # fmt: skip
            return _out(await _load(conn, integration_id))
    except IntegrityError as exc:
        await secrets.delete(path)
        raise ProblemError(409, "integration_name_taken", "An integration with that name already exists.") from exc


@router.patch("/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    request: Request, integration_id: uuid.UUID, body: IntegrationUpdate, auth: ManageIntegrations
) -> IntegrationOut:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        await _load(conn, integration_id)
        changes: dict[str, object] = {}
        if body.name is not None:
            changes["name"] = body.name
        if body.token is not None:
            path = integration_path(auth.tenant_id, integration_id)
            await _secrets(request).put(path, body.token)
            changes |= {"vault_path": path, "status": "untested", "account": None}
        if changes:
            changes["updated_at"] = datetime.now(UTC)
            where = TenantIntegration.id == integration_id
            await conn.execute(update(TenantIntegration).where(where).values(**changes))
            await audit(conn, auth, "integration.update", f"integration:{integration_id}",
                        {"renamed": body.name is not None, "access_rotated": body.token is not None})  # fmt: skip
        return _out(await _load(conn, integration_id))


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(request: Request, integration_id: uuid.UUID, auth: ManageIntegrations) -> None:
    async with transaction(request, auth) as conn:
        row = await _load(conn, integration_id)
        await conn.execute(delete(TenantIntegration).where(TenantIntegration.id == integration_id))
        await audit(conn, auth, "integration.delete", f"integration:{integration_id}", {"kind": row.kind})
    if row.vault_path:
        await _secrets(request).delete(row.vault_path)


@router.post("/{integration_id}:test", response_model=IntegrationOut)
async def test_integration(request: Request, integration_id: uuid.UUID, auth: ManageIntegrations) -> IntegrationOut:
    """Ask the tool who the token belongs to: nothing is read from the customer's files."""
    async with transaction(request, auth) as conn:
        row = await _load(conn, integration_id)
    token = await _secrets(request).get(row.vault_path) if row.vault_path else None
    account: str | None = None
    if not token:
        ok, detail = False, "There is no token: set one and test again."
    else:
        try:
            account = await who(request, row.kind, dict(row.config or {}), token)
            ok, detail = True, f"Connected as {account}" if account else "Connected"
        except (FigmaError, TrackerError) as exc:
            ok, detail = False, str(exc)
        except Rejection as rejection:
            ok, detail = False, rejection.detail
    async with transaction(request, auth) as conn:
        await conn.execute(update(TenantIntegration).where(TenantIntegration.id == integration_id).values(
            status="ok" if ok else "failed", account=account, last_tested_at=datetime.now(UTC),
            last_test_detail=detail[:500],
        ))  # fmt: skip
        await audit(conn, auth, "integration.test", f"integration:{integration_id}", {"ok": ok},
                    outcome="success" if ok else "failure")  # fmt: skip
        return _out(await _load(conn, integration_id))


async def who(request: Request, kind: str, config: dict[str, str], token: str) -> str:
    """Who the token belongs to, as the tool reports it."""
    http = request.app.state.resources.http
    if kind == "figma":
        return await FigmaClient(http, token, request.app.state.settings.figma_url).me()
    settings = request.app.state.settings
    url = config.get("site") or config.get("organization") or ""
    await ensure_public_host(url, services.services(request).git_resolver,
                             allow_private_hosts=settings.git_allow_private_hosts and settings.is_local)  # fmt: skip
    if kind == "jira":
        return await JiraTracker(http, url, config.get("email", ""), token, "").whoami()
    return await AzureDevOpsTracker(http, url, token, "").whoami()
