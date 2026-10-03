"""What a SCIM change does in the platform and in Keycloak (ADR-0031). Every function runs in the caller's transaction,
scoped to the tenant of the bearer, and inside `authz_change` when it touches memberships or roles.

- A user is a platform account (found or created by e-mail) with a membership in the tenant, and a Keycloak account
  (found by e-mail or created, without the invitation's actions) that joins the tenant's Organization. Its e-mail
  must be in one of the tenant's domains: the tenant's provider speaks for its own people only.
- Deactivating suspends the membership, removes the roles SCIM gave and ends the user's sessions in the tenant. The
  Keycloak account is disabled only when the person belongs to no other active tenant (the realm is shared, D-20).
- Groups give tenant roles through the group -> role mapping of the tenant's identity providers (source `scim`);
  roles assigned by hand or by the sign-in mapping are never touched.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.auth.session import SessionStore
from nexti_api.identity import service as identity_service
from nexti_api.identity.signin import domain_of
from nexti_api.keycloak_admin import KeycloakAdmin, KeycloakAdminError
from nexti_api.observability import log
from nexti_api.scim import protocol
from nexti_api.scim.protocol import ScimError, UserFields
from nexti_core.db.models import (
    Membership,
    Role,
    RoleAssignment,
    ScimGroup,
    ScimGroupMember,
    ScimUser,
    TenantIdentityProvider,
)
from nexti_core.db.session import DbScope, apply_scope


@dataclass(frozen=True)
class Scim:
    """The tenant of the bearer and the services a change needs."""

    tenant_id: uuid.UUID
    access_id: uuid.UUID
    base: str  # the public /scim/v2 URL, for the resources' locations
    admin: KeycloakAdmin | None
    sessions: SessionStore | None

    def keycloak(self) -> KeycloakAdmin:
        if self.admin is None:
            raise ScimError(503, "The identity service (Keycloak admin) is not configured.")
        return self.admin


def _sync_failed(exc: KeycloakAdminError) -> ScimError:
    return ScimError(502, f"Keycloak did not take the change: {exc}"[:300])


# -- Reading ------------------------------------------------------------------------------------------------------
async def load_user(conn: AsyncConnection, scim_id: str) -> Any:
    try:
        key = uuid.UUID(scim_id)
    except ValueError:
        raise ScimError(404, "The user does not exist.") from None
    row = (await conn.execute(select(ScimUser).where(ScimUser.id == key))).first()
    if row is None:
        raise ScimError(404, "The user does not exist.")
    return row


async def load_group(conn: AsyncConnection, scim_id: str) -> Any:
    try:
        key = uuid.UUID(scim_id)
    except ValueError:
        raise ScimError(404, "The group does not exist.") from None
    row = (await conn.execute(select(ScimGroup).where(ScimGroup.id == key))).first()
    if row is None:
        raise ScimError(404, "The group does not exist.")
    return row


def _meta(kind: str, row: Any, base: str) -> dict[str, Any]:
    return {"resourceType": kind, "created": row.created_at.isoformat(), "lastModified": row.updated_at.isoformat(),
            "location": f"{base}/{kind}s/{row.id}"}  # fmt: skip


def user_resource(row: Any, base: str, groups: list[Any] | None = None) -> dict[str, Any]:
    name = {k: v for k, v in (("givenName", row.given_name), ("familyName", row.family_name)) if v}
    body: dict[str, Any] = {
        "schemas": [protocol.USER], "id": str(row.id), "userName": row.user_name, "active": row.active,
        "emails": [{"value": row.email, "type": "work", "primary": True}], "meta": _meta("User", row, base),
    }  # fmt: skip
    for key, value in (("externalId", row.external_id), ("displayName", row.display_name), ("name", name)):
        if value:
            body[key] = value
    if groups is not None:
        body["groups"] = [{"value": str(g.id), "display": g.display_name, "$ref": f"{base}/Groups/{g.id}"}
                          for g in groups]  # fmt: skip
    return body


async def user_groups(conn: AsyncConnection, scim_id: uuid.UUID) -> list[Any]:
    return list(
        (await conn.execute(select(ScimGroup.id, ScimGroup.display_name)
                            .join(ScimGroupMember, ScimGroupMember.group_id == ScimGroup.id)
                            .where(ScimGroupMember.member_id == scim_id).order_by(ScimGroup.display_name))).all()
    )  # fmt: skip


async def group_resource(conn: AsyncConnection, row: Any, base: str) -> dict[str, Any]:
    members = (
        await conn.execute(select(ScimUser.id, ScimUser.user_name)
                           .join(ScimGroupMember, ScimGroupMember.member_id == ScimUser.id)
                           .where(ScimGroupMember.group_id == row.id).order_by(ScimUser.user_name))
    ).all()  # fmt: skip
    body: dict[str, Any] = {
        "schemas": [protocol.GROUP], "id": str(row.id), "displayName": row.display_name,
        "members": [{"value": str(m.id), "display": m.user_name, "$ref": f"{base}/Users/{m.id}"} for m in members],
        "meta": _meta("Group", row, base),
    }  # fmt: skip
    if row.external_id:
        body["externalId"] = row.external_id
    return body


# -- Roles --------------------------------------------------------------------------------------------------------
async def group_mapping(conn: AsyncConnection) -> dict[str, set[str]]:
    """Group -> tenant role keys, from every identity provider of the tenant (the same mapping as at sign-in)."""
    mapping: dict[str, set[str]] = {}
    for group_roles in (await conn.execute(select(TenantIdentityProvider.group_roles))).scalars():
        for group, role in dict(group_roles or {}).items():
            mapping.setdefault(str(group), set()).add(str(role))
    return mapping


async def sync_roles(conn: AsyncConnection, tenant_id: uuid.UUID, scim_id: uuid.UUID) -> list[str]:
    """The `scim` role assignments of the user, recalculated from their groups. Returns the role keys."""
    user = (await conn.execute(select(ScimUser.user_id, ScimUser.active).where(ScimUser.id == scim_id))).one()
    wanted: set[str] = set()
    if user.active:
        mapping = await group_mapping(conn)
        for group in await user_groups(conn, scim_id):
            wanted |= mapping.get(group.display_name, set())
    roles = {
        r.key: r.id
        for r in (await conn.execute(select(Role.key, Role.id)
                                     .where(Role.scope == "tenant", Role.key.in_(wanted or {""})))).all()
    }  # fmt: skip
    await conn.execute(delete(RoleAssignment).where(
        RoleAssignment.user_id == user.user_id, RoleAssignment.source == "scim", RoleAssignment.project_id.is_(None),
        RoleAssignment.role_id.not_in(list(roles.values()) or [uuid.uuid4()]),
    ))  # fmt: skip
    for role_id in roles.values():
        await conn.execute(pg_insert(RoleAssignment).values(
            tenant_id=tenant_id, user_id=user.user_id, role_id=role_id, scope="tenant", source="scim",
        ).on_conflict_do_nothing())  # fmt: skip
    return sorted(roles)


# -- Users --------------------------------------------------------------------------------------------------------
async def _tenant_domains(conn: AsyncConnection, tenant_id: uuid.UUID) -> set[str]:
    identity = await identity_service.identity_of(conn, tenant_id)
    provider_domains = (await conn.execute(select(TenantIdentityProvider.domains))).scalars().all()
    return {*identity.domains, *(d for ds in provider_domains for d in ds)}


async def _check_email(conn: AsyncConnection, tenant_id: uuid.UUID, email: str | None) -> str:
    domain = domain_of(email)
    if not email or domain is None:
        raise ScimError(400, "The user needs an e-mail (userName or emails).", "invalidValue")
    if domain not in await _tenant_domains(conn, tenant_id):
        raise ScimError(400, f"{domain} is not a domain of the tenant (Administration -> Authentication).",
                        "invalidValue")  # fmt: skip
    return email.lower()


async def _check_unique(conn: AsyncConnection, user_name: str, except_id: uuid.UUID | None = None) -> None:
    query = select(ScimUser.id).where(func.lower(ScimUser.user_name) == user_name.lower())
    if except_id is not None:
        query = query.where(ScimUser.id != except_id)
    if (await conn.execute(query)).first() is not None:
        raise ScimError(409, "A user with that userName already exists.", "uniqueness")


async def _organization(conn: AsyncConnection, scim: Scim) -> str:
    identity = await identity_service.identity_of(conn, scim.tenant_id)
    if identity.organization_id:
        return str(identity.organization_id)
    return await identity_service.reconcile_organization(conn, scim.keycloak(), scim.tenant_id)


async def _link_account(conn: AsyncConnection, tenant_id: uuid.UUID, user_id: uuid.UUID, sub: str,
                        email: str) -> None:  # fmt: skip
    """The platform account learns its Keycloak id, so its first sign-in finds it (as the sign-in would by e-mail)."""
    await apply_scope(conn, DbScope(tenant_id=tenant_id, auth_sub=sub, auth_email=email))
    try:
        async with conn.begin_nested():
            await conn.execute(text("UPDATE app_user SET keycloak_sub = :s WHERE id = :u AND keycloak_sub IS NULL"),
                               {"s": sub, "u": user_id})  # fmt: skip
    except IntegrityError:
        log.warning("scim_link_skipped", reason="keycloak_sub_taken")
    finally:
        await apply_scope(conn, DbScope(tenant_id=tenant_id))


async def create_user(conn: AsyncConnection, scim: Scim, fields: UserFields) -> uuid.UUID:
    assert fields.user_name is not None  # noqa: S101 (user_fields requires it)
    email = await _check_email(conn, scim.tenant_id, fields.email)
    await _check_unique(conn, fields.user_name)
    display = fields.display_name or " ".join(p for p in (fields.given_name, fields.family_name) if p) or email
    user_id: uuid.UUID = (
        await conn.execute(text("SELECT ensure_user_for_invitation(:e, :n)"), {"e": email, "n": display})
    ).scalar_one()  # fmt: skip
    if (await conn.execute(select(ScimUser.id).where(ScimUser.user_id == user_id))).first() is not None:
        raise ScimError(409, "That person is already provisioned with another userName.", "uniqueness")
    member = (await conn.execute(select(Membership.status).where(Membership.user_id == user_id))).first()
    if member is None:
        await conn.execute(insert(Membership).values(tenant_id=scim.tenant_id, user_id=user_id))
    elif member.status != "active":
        await conn.execute(update(Membership).where(Membership.user_id == user_id).values(status="active"))
    admin = scim.keycloak()
    try:
        account = await admin.find_user(email)
        if account is None:
            account = await admin.create_user(email, fields.given_name, fields.family_name, required_actions=[])
        elif not account.enabled:
            await admin.set_user_enabled(account.id, True)
        await admin.add_organization_member(await _organization(conn, scim), account.id)
    except KeycloakAdminError as exc:
        raise _sync_failed(exc) from None
    await _link_account(conn, scim.tenant_id, user_id, account.id, email)
    scim_id: uuid.UUID = (
        await conn.execute(insert(ScimUser).values(
            tenant_id=scim.tenant_id, user_id=user_id, keycloak_id=account.id, user_name=fields.user_name,
            external_id=fields.external_id, given_name=fields.given_name, family_name=fields.family_name,
            display_name=fields.display_name, email=email, active=True,
        ).returning(ScimUser.id))
    ).scalar_one()  # fmt: skip
    if fields.active is False:
        await set_active(conn, scim, scim_id, False)
    return scim_id


async def update_user(conn: AsyncConnection, scim: Scim, scim_id: uuid.UUID, changes: dict[str, Any]) -> bool | None:
    """Applies the changes; returns the new `active` when it changed, else None."""
    row = (await conn.execute(select(ScimUser).where(ScimUser.id == scim_id))).one()
    values = {k: v for k, v in changes.items() if k != "active"}
    if values.get("user_name"):
        await _check_unique(conn, values["user_name"], scim_id)
    if "email" in values:
        # The account keeps the e-mail it was provisioned with; a new one must still be the tenant's.
        values["email"] = await _check_email(conn, scim.tenant_id, values["email"])
    if values:
        await conn.execute(update(ScimUser).where(ScimUser.id == scim_id).values(**values))
    if "active" in changes and changes["active"] != row.active:
        await set_active(conn, scim, scim_id, bool(changes["active"]))
        return bool(changes["active"])
    return None


async def set_active(conn: AsyncConnection, scim: Scim, scim_id: uuid.UUID, active: bool) -> None:
    row = (await conn.execute(select(ScimUser).where(ScimUser.id == scim_id))).one()
    await conn.execute(update(ScimUser).where(ScimUser.id == scim_id).values(active=active))
    await conn.execute(update(Membership).where(Membership.user_id == row.user_id)
                       .values(status="active" if active else "suspended"))  # fmt: skip
    await sync_roles(conn, scim.tenant_id, scim_id)
    shared = bool((await conn.execute(text("SELECT scim_user_shared(:u)"), {"u": row.user_id})).scalar())
    if row.keycloak_id and (active or not shared):
        admin = scim.keycloak()
        try:
            await admin.set_user_enabled(row.keycloak_id, active)
            if not active:
                await admin.logout_user(row.keycloak_id)
        except KeycloakAdminError as exc:
            raise _sync_failed(exc) from None
    if not active and scim.sessions is not None:
        await scim.sessions.revoke_user(row.user_id, scim.tenant_id if shared else None)


# -- Groups -------------------------------------------------------------------------------------------------------
async def member_keys(conn: AsyncConnection, ids: list[str] | tuple[str, ...]) -> set[uuid.UUID]:
    """The SCIM user ids given, all of them users of the tenant."""
    try:
        keys = {uuid.UUID(i) for i in ids}
    except ValueError:
        raise ScimError(400, "A member is not a user id.", "invalidValue") from None
    if not keys:
        return set()
    found = set((await conn.execute(select(ScimUser.id).where(ScimUser.id.in_(keys)))).scalars())
    if keys - found:
        raise ScimError(400, "A member is not a user of the tenant.", "invalidValue")
    return keys


async def _check_group_name(conn: AsyncConnection, name: str, except_id: uuid.UUID | None = None) -> None:
    query = select(ScimGroup.id).where(func.lower(ScimGroup.display_name) == name.lower())
    if except_id is not None:
        query = query.where(ScimGroup.id != except_id)
    if (await conn.execute(query)).first() is not None:
        raise ScimError(409, "A group with that displayName already exists.", "uniqueness")


async def current_members(conn: AsyncConnection, group_id: uuid.UUID) -> set[uuid.UUID]:
    query = select(ScimGroupMember.member_id).where(ScimGroupMember.group_id == group_id)
    return set((await conn.execute(query)).scalars())


async def set_members(conn: AsyncConnection, tenant_id: uuid.UUID, group_id: uuid.UUID,
                      wanted: set[uuid.UUID]) -> tuple[set[uuid.UUID], set[uuid.UUID]]:  # fmt: skip
    """Makes the members exactly `wanted`; returns (added, removed)."""
    current = await current_members(conn, group_id)
    added, removed = wanted - current, current - wanted
    if removed:
        await conn.execute(delete(ScimGroupMember).where(ScimGroupMember.group_id == group_id,
                                                         ScimGroupMember.member_id.in_(removed)))  # fmt: skip
    if added:
        await conn.execute(insert(ScimGroupMember),
                           [{"tenant_id": tenant_id, "group_id": group_id, "member_id": m} for m in added])  # fmt: skip
    return added, removed


async def resync(conn: AsyncConnection, tenant_id: uuid.UUID, scim_ids: set[uuid.UUID]) -> None:
    for scim_id in sorted(scim_ids):
        await sync_roles(conn, tenant_id, scim_id)


async def create_group(conn: AsyncConnection, scim: Scim, body: dict[str, Any]) -> tuple[uuid.UUID, int]:
    name = protocol.text(body.get("displayName"), "displayName", 256, required=True)
    assert name is not None  # noqa: S101
    await _check_group_name(conn, name)
    members = await member_keys(conn, protocol.member_ids(body.get("members")))
    group_id: uuid.UUID = (
        await conn.execute(insert(ScimGroup).values(
            tenant_id=scim.tenant_id, display_name=name,
            external_id=protocol.text(body.get("externalId"), "externalId", 320),
        ).returning(ScimGroup.id))
    ).scalar_one()  # fmt: skip
    added, _ = await set_members(conn, scim.tenant_id, group_id, members)
    await resync(conn, scim.tenant_id, added)
    return group_id, len(added)


async def replace_group(conn: AsyncConnection, scim: Scim, group_id: uuid.UUID, name: str | None,
                        external_id: str | None, members: set[uuid.UUID] | None,
                        external_given: bool) -> tuple[int, int]:  # fmt: skip
    """Renames and sets the members (None = unchanged); returns (added, removed)."""
    values: dict[str, Any] = {}
    if name is not None:
        await _check_group_name(conn, name, group_id)
        values["display_name"] = name
    if external_given:
        values["external_id"] = external_id
    if values:
        await conn.execute(update(ScimGroup).where(ScimGroup.id == group_id).values(**values))
    current = await current_members(conn, group_id)
    added: set[uuid.UUID] = set()
    removed: set[uuid.UUID] = set()
    if members is not None:
        added, removed = await set_members(conn, scim.tenant_id, group_id, members)
    # A new name can map to other roles: everyone in the group is recalculated then.
    await resync(conn, scim.tenant_id, (current | added) if name is not None else (added | removed))
    return len(added), len(removed)


async def delete_group(conn: AsyncConnection, scim: Scim, group_id: uuid.UUID) -> int:
    members = await current_members(conn, group_id)
    await conn.execute(delete(ScimGroup).where(ScimGroup.id == group_id))
    await resync(conn, scim.tenant_id, members)
    return len(members)
