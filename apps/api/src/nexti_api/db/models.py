"""ORM mapping of the schema created by the Alembic migrations (the migrations are the source of truth;
tests/integration/test_schema.py fails if the two drift apart). Checks and RLS policies live only in SQL."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deployment_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="sharedSaas")
    default_language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (Index("app_user_email_key", func.lower(text("email")), unique=True),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    keycloak_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"), Index("membership_user_idx", "user_id"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class Permission(Base):
    __tablename__ = "permission"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class PermissionScope(Base):
    __tablename__ = "permission_scope"
    permission_key: Mapped[str] = mapped_column(ForeignKey("permission.key"), primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)


class Role(Base):
    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("tenant_id", "key"), UniqueConstraint("id", "tenant_id", "scope"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "permission_key"),
        ForeignKeyConstraint(
            ["role_id", "tenant_id", "role_scope"], ["role.id", "role.tenant_id", "role.scope"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["permission_key", "role_scope"], ["permission_scope.permission_key", "permission_scope.scope"]
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_scope: Mapped[str] = mapped_column(Text, nullable=False)
    permission_key: Mapped[str] = mapped_column(Text, nullable=False)


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class RoleAssignment(Base):
    __tablename__ = "role_assignment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["membership.tenant_id", "membership.user_id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["role_id", "tenant_id", "scope"], ["role.id", "role.tenant_id", "role.scope"]),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"]),
        UniqueConstraint("user_id", "role_id", "project_id", postgresql_nulls_not_distinct=True),
        Index("role_assignment_tenant_user_idx", "tenant_id", "user_id"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class Invitation(Base):
    __tablename__ = "invitation"
    __table_args__ = (
        ForeignKeyConstraint(["role_id", "tenant_id", "role_scope"], ["role.id", "role.tenant_id", "role.scope"]),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"]),
        Index("invitation_email_idx", func.lower(text("email")), postgresql_where=text("status = 'pending'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_scope: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    keycloak_user_id: Mapped[str | None] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class PlatformRoleAssignment(Base):
    __tablename__ = "platform_role_assignment"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = _now()


class AuthzOutbox(Base):
    __tablename__ = "authz_outbox"
    __table_args__ = (Index("authz_outbox_pending_idx", "id", postgresql_where=text("status = 'pending'")),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"))
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    tuples: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
