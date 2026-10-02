"""The offline license in the API (spec 14.4, ADR-0030).

The file and its signature are verified once, when the app is built, and the result is cached; expiry and the limits
(tenants, projects) are evaluated on each check against the current usage. With no license configured (SaaS,
development) nothing changes. A configured license that is missing, invalid, expired or exceeded makes the platform
read-only: everything can be seen, but no run is started and no project or tenant is created (`license_read_only`).
With a valid license, creating the project or tenant that would pass a limit is refused (`license_limit_reached`).
"""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Request
from pydantic import AwareDatetime, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.admin.common import audit, transaction
from nexti_api.audit import AuditEvent, record
from nexti_api.authz.require import Authorized
from nexti_api.errors import ProblemError
from nexti_api.observability import log
from nexti_api.schemas import ApiModel
from nexti_api.settings import Settings
from nexti_core.db.models import Project, Tenant
from nexti_core.db.session import DbScope, apply_scope, scoped_connection
from nexti_core.license import LicenseCheck, LicenseReason, LicenseState, LicenseStatus, Usage, check_license, evaluate


class LicenseOut(ApiModel):
    state: LicenseState
    read_only: bool
    reason: LicenseReason | None = None
    license_id: str | None = None
    customer: str | None = None
    deployment_profile: str | None = None
    issued_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    max_tenants: int | None = None
    max_projects: int | None = None
    features: list[str] = Field(default_factory=list)
    tenants: int | None = None
    projects: int | None = None


def load(settings: Settings) -> LicenseCheck:
    """Verify the configured license file (at startup; the result is kept in app.state.license)."""
    check = check_license(settings.license_file, settings.license_public_key, settings.license_signature_file)
    if check.configured:
        log.info("license_checked", verified=check.verified, reason=check.reason)
    return check


async def record_startup(engine: AsyncEngine | None, check: LicenseCheck) -> None:
    """The verification at startup, in the platform audit chain (only when a license is configured)."""
    if engine is None or not check.configured:
        return
    status = evaluate(check, datetime.now(UTC), None)
    details: dict[str, Any] = {"state": status.state, "reason": status.reason}
    if status.license is not None:
        details |= {"license_id": status.license.license_id, "customer": status.license.customer,
                    "expires_at": status.license.expires_at.isoformat()}  # fmt: skip
    try:
        async with scoped_connection(engine, DbScope(platform_scope=True)) as conn:
            await record(conn, AuditEvent(action="license.verify", outcome="success" if status.license else "failure",
                                          actor_kind="system", target="platform:license", details=details))  # fmt: skip
    except Exception as exc:  # the database may still be starting; the state is also logged
        log.warning("license_audit_failed", error=type(exc).__name__)


async def usage(engine: AsyncEngine) -> Usage:
    """Tenants and projects across the platform. Projects are read tenant by tenant: they are visible only with
    their tenant's scope (RLS)."""
    async with scoped_connection(engine, DbScope(platform_scope=True)) as conn:
        tenants = list((await conn.execute(select(Tenant.id))).scalars())
        projects = 0
        for tenant_id in tenants:
            await apply_scope(conn, DbScope(tenant_id=tenant_id, platform_scope=True))
            projects += (await conn.execute(select(func.count()).select_from(Project))).scalar_one()
    return Usage(tenants=len(tenants), projects=projects)


async def current(request: Request) -> LicenseStatus:
    check: LicenseCheck = request.app.state.license
    engine: AsyncEngine | None = request.app.state.resources.engine
    counted = await usage(engine) if check.verified and engine is not None else None
    return evaluate(check, datetime.now(UTC), counted)


def to_out(status: LicenseStatus) -> LicenseOut:
    out = LicenseOut(state=status.state, read_only=status.read_only, reason=status.reason)
    if status.license is not None:
        lic = status.license
        out = out.model_copy(update={
            "license_id": lic.license_id, "customer": lic.customer, "deployment_profile": lic.deployment_profile,
            "issued_at": lic.issued_at, "expires_at": lic.expires_at, "max_tenants": lic.max_tenants,
            "max_projects": lic.max_projects, "features": list(lic.features),
        })  # fmt: skip
    if status.usage is not None:
        out = out.model_copy(update={"tenants": status.usage.tenants, "projects": status.usage.projects})
    return out


async def ensure_writable(
    request: Request,
    auth: Authorized,
    action: str,
    target: str,
    *,
    creating: Literal["project", "tenant"] | None = None,
) -> None:
    """Refuse (and audit) an action that the license does not allow. Call it after authorization."""
    check: LicenseCheck = request.app.state.license
    if not check.configured:
        return
    status = await current(request)
    code, reason, blocked = "license_read_only", status.reason, status.read_only
    if not blocked and creating is not None and status.license is not None and status.usage is not None:
        used, limit = (
            (status.usage.projects, status.license.max_projects)
            if creating == "project"
            else (status.usage.tenants, status.license.max_tenants)
        )
        if used >= limit:
            blocked, code = True, "license_limit_reached"
            reason = "max_projects" if creating == "project" else "max_tenants"
    if not blocked:
        return
    async with transaction(request, auth) as conn:
        await audit(conn, auth, f"{action}.license_denied", target, {"code": code, "state": status.state,
                    "reason": reason}, outcome="denied", platform=creating == "tenant")  # fmt: skip
    detail = (
        "The license does not allow more of these."
        if code == "license_limit_reached"
        else "The platform is read-only: the license is missing, invalid, expired or exceeded."
    )
    raise ProblemError(403, code, detail, state=status.state, reason=reason)
