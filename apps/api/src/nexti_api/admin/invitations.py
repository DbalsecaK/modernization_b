"""Invitations (spec 15.1, plan M0 section 5): the admin invites an e-mail with a role; Keycloak creates the account
and e-mails the password set-up; the first sign-in with that verified e-mail activates the membership and role.
The platform stores no invitation token: the link is Keycloak's."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.admin.assignments import authorize_role_change
from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.audit import AuditEvent, record
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.authz.sync import authz_change
from nexti_api.errors import ProblemError
from nexti_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError
from nexti_api.observability import log
from nexti_api.schemas import ApiModel
from nexti_core.db.models import AppUser, Invitation, Membership, Project, Role, RoleAssignment
from nexti_core.db.session import DbScope, scoped_connection

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])
ManageUsers = Annotated[Authorized, Depends(require_tenant("users.manage"))]
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
EMAIL = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$"


class InvitationOut(ApiModel):
    id: uuid.UUID
    email: str
    role_id: uuid.UUID
    role_key: str
    project_id: uuid.UUID | None
    status: Literal["pending", "accepted", "revoked", "expired"]
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InvitationCreate(ApiModel):
    email: str = Field(pattern=EMAIL, max_length=320)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role_id: uuid.UUID
    project_id: uuid.UUID | None = None


class InvitationCreated(InvitationOut):
    # False when the person already had a Keycloak account (no password e-mail) or the e-mail failed.
    email_sent: bool


COLUMNS = (
    Invitation.id,
    Invitation.email,
    Invitation.role_id,
    Role.key.label("role_key"),
    Invitation.project_id,
    Invitation.status,
    Invitation.expires_at,
    Invitation.accepted_at,
    Invitation.created_at,
)


def _admin(request: Request) -> KeycloakAdmin:
    admin: KeycloakAdmin | None = getattr(request.app.state, "keycloak_admin", None)
    if admin is None:
        raise ProblemError(503, "identity_admin_unavailable", "Account administration is not available.")
    return admin


async def _load(request: Request, auth: Authorized, invitation_id: uuid.UUID) -> InvitationOut:
    async with transaction(request, auth) as conn:
        row = (
            await conn.execute(
                select(*COLUMNS).join(Role, Role.id == Invitation.role_id).where(Invitation.id == invitation_id)
            )
        ).one_or_none()
    if row is None:
        raise not_found("invitation")
    return InvitationOut.model_validate(row, from_attributes=True)


async def _send(request: Request, keycloak_user_id: str | None) -> bool:
    if not keycloak_user_id:
        return False
    try:
        lifespan = request.app.state.settings.invitation_days * 86400
        await _admin(request).send_invitation_email(keycloak_user_id, lifespan)
    except KeycloakAdminError as exc:
        log.warning("invitation_email_failed", error=str(exc))
        return False
    return True


@router.get("", response_model=list[InvitationOut])
async def list_invitations(request: Request, auth: ManageUsers) -> list[InvitationOut]:
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                select(*COLUMNS).join(Role, Role.id == Invitation.role_id).order_by(Invitation.created_at.desc())
            )
        ).all()
    return [InvitationOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=InvitationCreated, status_code=201)
async def invite(request: Request, body: InvitationCreate, auth: TenantMember) -> InvitationCreated:
    assert auth.tenant_id is not None  # noqa: S101
    await authorize_role_change(request, auth, body.project_id)
    email = body.email.lower()
    async with transaction(request, auth) as conn:
        role = (await conn.execute(select(Role.id, Role.scope).where(Role.id == body.role_id))).one_or_none()
        if role is None:
            raise not_found("role")
        if (role.scope == "project") != (body.project_id is not None):
            raise ProblemError(422, "scope_mismatch", "Project roles need a project; tenant roles must not have one.")
        if (
            body.project_id
            and (await conn.execute(select(Project.id).where(Project.id == body.project_id))).first() is None
        ):
            raise not_found("project")
        member = (
            await conn.execute(
                select(Membership.status)
                .join(AppUser, AppUser.id == Membership.user_id)
                .where(func.lower(AppUser.email) == email)
            )
        ).scalar_one_or_none()
        if member == "active":
            raise ProblemError(409, "already_member", "That person is already a member; assign the role instead.")
        pending = (
            await conn.execute(
                select(Invitation.id).where(
                    func.lower(Invitation.email) == email,
                    Invitation.role_id == body.role_id,
                    Invitation.project_id.is_(None)
                    if body.project_id is None
                    else Invitation.project_id == body.project_id,
                    Invitation.status == "pending",
                )
            )
        ).first()
        if pending:
            raise ProblemError(409, "invitation_pending", "That invitation is already pending.")

    # The Keycloak account first: if it fails, nothing was written here.
    admin = _admin(request)
    try:
        account = await admin.find_user(email)
        created = account is None
        if account is None:
            account = await admin.create_user(email, body.display_name)
    except KeycloakAdminError as exc:
        raise ProblemError(502, "identity_provider_error", "The identity provider did not accept the account.") from exc

    async with transaction(request, auth) as conn:
        name = body.display_name or email.split("@", 1)[0]
        user_id: uuid.UUID = (
            await conn.execute(text("SELECT ensure_user_for_invitation(:e, :n)"), {"e": email, "n": name})
        ).scalar_one()
        await conn.execute(
            pg_insert(Membership)
            .values(tenant_id=auth.tenant_id, user_id=user_id, status="invited", created_by=auth.user_id)
            .on_conflict_do_nothing(index_elements=["tenant_id", "user_id"])
        )
        invitation_id = (
            await conn.execute(
                insert(Invitation)
                .values(
                    tenant_id=auth.tenant_id,
                    email=email,
                    role_id=role.id,
                    role_scope=role.scope,
                    project_id=body.project_id,
                    keycloak_user_id=account.id,
                    invited_by=auth.user_id,
                    expires_at=datetime.now(UTC) + timedelta(days=request.app.state.settings.invitation_days),
                )
                .returning(Invitation.id)
            )
        ).scalar_one()
        await audit(
            conn,
            auth,
            "invitation.create",
            f"invitation:{invitation_id}",
            {"email": email, "role_id": str(role.id), "new_account": created},
        )
    sent = await _send(request, account.id) if created else False
    loaded = await _load(request, auth, invitation_id)
    return InvitationCreated(**loaded.model_dump(), email_sent=sent)


@router.post("/{invitation_id}:resend", response_model=InvitationCreated)
async def resend(request: Request, invitation_id: uuid.UUID, auth: ManageUsers) -> InvitationCreated:
    invitation = await _load(request, auth, invitation_id)
    if invitation.status != "pending":
        raise ProblemError(409, "invitation_not_pending", "Only pending invitations can be sent again.")
    async with transaction(request, auth) as conn:
        keycloak_user_id = (
            await conn.execute(select(Invitation.keycloak_user_id).where(Invitation.id == invitation_id))
        ).scalar_one()
        await audit(conn, auth, "invitation.resend", f"invitation:{invitation_id}")
    account = await _admin(request).find_user(invitation.email)
    # Only accounts that still have to set their password get the e-mail again.
    sent = await _send(request, keycloak_user_id) if account and account.required_actions else False
    return InvitationCreated(**invitation.model_dump(), email_sent=sent)


@router.delete("/{invitation_id}", status_code=204)
async def revoke(request: Request, invitation_id: uuid.UUID, auth: ManageUsers) -> None:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        row = (
            await conn.execute(
                update(Invitation)
                .where(Invitation.id == invitation_id, Invitation.status == "pending")
                .values(status="revoked")
                .returning(Invitation.email)
            )
        ).one_or_none()
        if row is None:
            raise not_found("invitation")
        # The placeholder membership goes too, unless another invitation still waits for the same person.
        user_id: uuid.UUID | None = (
            await conn.execute(select(AppUser.id).where(func.lower(AppUser.email) == row.email))
        ).scalar_one_or_none()
        others = (
            await conn.execute(
                select(Invitation.id).where(func.lower(Invitation.email) == row.email, Invitation.status == "pending")
            )
        ).first()
        if user_id is not None and others is None:
            await conn.execute(delete(Membership).where(Membership.user_id == user_id, Membership.status == "invited"))
        await audit(conn, auth, "invitation.revoke", f"invitation:{invitation_id}", {"email": row.email})


async def accept_pending_invitations(engine: AsyncEngine, user_id: uuid.UUID, verified_email: str) -> int:
    """At sign-in with a verified e-mail: activate every pending, unexpired invitation of that e-mail.
    Returns how many were accepted."""
    async with scoped_connection(engine, DbScope(user_id=user_id, auth_email=verified_email)) as conn:
        pending = (
            await conn.execute(
                select(
                    Invitation.id,
                    Invitation.tenant_id,
                    Invitation.role_id,
                    Invitation.role_scope,
                    Invitation.project_id,
                    Invitation.expires_at,
                )
            )
        ).all()
    accepted = 0
    for inv in pending:
        async with scoped_connection(engine, DbScope(tenant_id=inv.tenant_id, user_id=user_id)) as conn:
            if inv.expires_at <= datetime.now(UTC):
                await conn.execute(update(Invitation).where(Invitation.id == inv.id).values(status="expired"))
                continue
            async with authz_change(conn, inv.tenant_id):
                await conn.execute(
                    pg_insert(Membership)
                    .values(tenant_id=inv.tenant_id, user_id=user_id, status="active")
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "user_id"],
                        set_={"status": "active"},
                        where=Membership.status == "invited",
                    )
                )
                await conn.execute(
                    pg_insert(RoleAssignment)
                    .values(
                        tenant_id=inv.tenant_id,
                        user_id=user_id,
                        role_id=inv.role_id,
                        scope=inv.role_scope,
                        project_id=inv.project_id,
                    )
                    .on_conflict_do_nothing()
                )
            await conn.execute(
                update(Invitation).where(Invitation.id == inv.id).values(status="accepted", accepted_at=func.now())
            )
            await record(
                conn,
                AuditEvent(
                    action="invitation.accept",
                    outcome="success",
                    actor_kind="user",
                    actor_id=user_id,
                    tenant_id=inv.tenant_id,
                    target=f"invitation:{inv.id}",
                ),
            )
            accepted += 1
    return accepted
