"""ORM mapping of the schema created by the Alembic migrations (the migrations are the source of truth;
tests/integration/test_schema.py fails if the two drift apart). Checks and RLS policies live only in SQL."""

import uuid
from datetime import datetime
from decimal import Decimal
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
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("tenant_id", "name", name="project_tenant_name_key"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    flow: Mapped[str] = mapped_column(Text, nullable=False, server_default="modernization")
    artifact_language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


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
    # `idp`: given by the groups of an identity provider and recalculated at each sign-in (migration 0013);
    # `scim`: given by the SCIM groups of the identity provider (migration 0019).
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
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


class AuditLog(Base):
    """Append-only; seq, prev_hash and hash are computed by the database trigger (migration 0002)."""

    __tablename__ = "audit_log"
    __table_args__ = (UniqueConstraint("tenant_id", "seq", postgresql_nulls_not_distinct=True),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"))
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = _now()
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_label: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    request_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


Index("audit_log_tenant_time_idx", AuditLog.tenant_id, AuditLog.occurred_at.desc())


class KeycloakEventCursor(Base):
    """Position of the Keycloak event poller (migration 0003)."""

    __tablename__ = "keycloak_event_cursor"
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    last_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    updated_at: Mapped[datetime] = _now()


# AI configuration and usage (migration 0004, spec 12 and 13). Catalog tables are global; the rest are tenant data.


class ModelFamily(Base):
    __tablename__ = "model_family"
    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_version"
    __table_args__ = (
        # Global (provider catalog) slugs are unique; a tenant's own models (openai-compatible, migration 0018) are
        # unique within the tenant and visible only to it.
        Index(
            "model_version_global_slug_key", "provider_slug", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
        Index(
            "model_version_tenant_slug_key",
            "tenant_id",
            "provider_slug",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_family.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"))
    provider_slug: Mapped[str] = mapped_column(Text, nullable=False)
    # Aliases and variants (":thinking", ":free") share the canonical slug of the version they point to.
    canonical_slug: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="available")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ModelOffering(Base):
    __tablename__ = "model_offering"
    __table_args__ = (
        UniqueConstraint("version_id", "provider", "upstream_provider"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"], ["provider_connection.id", "provider_connection.tenant_id"]
        ),
        Index("ix_model_offering_connection", "connection_id", postgresql_where=text("connection_id IS NOT NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_version.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # openai-compatible offerings belong to one tenant and one of its connections (migration 0018, ADR-0030).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    upstream_provider: Mapped[str] = mapped_column(Text, nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    zdr: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="available")
    updated_at: Mapped[datetime] = _now()


class PriceVersion(Base):
    __tablename__ = "price_version"
    __table_args__ = (
        Index("price_version_current_key", "offering_id", unique=True, postgresql_where=text("valid_to IS NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_offering.id"), nullable=False)
    input_per_mtok: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    output_per_mtok: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    cache_read_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    cache_write_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    request_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    valid_from: Mapped[datetime] = _now()
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


class EffortMapping(Base):
    __tablename__ = "effort_mapping"
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_offering.id"), primary_key=True)
    effort: Mapped[str] = mapped_column(Text, primary_key=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = _now()


class ProviderConnection(Base):
    __tablename__ = "provider_connection"
    __table_args__ = (UniqueConstraint("tenant_id", "name"), UniqueConstraint("id", "tenant_id"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # openai-compatible: the server's base URL (ADR-0030); the API key, if any, is in the secrets store.
    base_url: Mapped[str | None] = mapped_column(Text)
    vault_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ModelProfile(Base):
    __tablename__ = "model_profile"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"], ["provider_connection.id", "provider_connection.tenant_id"]
        ),
        ForeignKeyConstraint(
            ["fallback_profile_id", "tenant_id"],
            ["model_profile.id", "model_profile.tenant_id"],
            ondelete="SET NULL (fallback_profile_id)",
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_offering.id"), nullable=False)
    effort: Mapped[str] = mapped_column(Text, nullable=False, server_default="medium")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("4096"))
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("120"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    fallback_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ModelAssignment(Base):
    __tablename__ = "model_assignment"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["profile_id", "tenant_id"], ["model_profile.id", "model_profile.tenant_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "project_id", "phase", "agent_role", postgresql_nulls_not_distinct=True),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phase: Mapped[str | None] = mapped_column(Text)
    agent_role: Mapped[str | None] = mapped_column(Text)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = _now()


class ModelPolicy(Base):
    __tablename__ = "model_policy"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), primary_key=True)
    openrouter_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    allowed_upstream_providers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    denied_upstream_providers: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    require_zdr: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    deny_data_collection: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = _now()


class UsageLedger(Base):
    """Append-only (trigger in migration 0004). Costs in USD; `price_version_id` is the tariff applied."""

    __tablename__ = "usage_ledger"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    occurred_at: Mapped[datetime] = _now()
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(Text)
    agent_role: Mapped[str | None] = mapped_column(Text)
    iteration: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    offering_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_offering.id"))
    price_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_version.id"))
    model: Mapped[str | None] = mapped_column(Text)
    upstream_provider: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    was_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    provider_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))


Index("usage_ledger_tenant_time_idx", UsageLedger.tenant_id, UsageLedger.occurred_at)
Index("usage_ledger_project_time_idx", UsageLedger.project_id, UsageLedger.occurred_at)


class Budget(Base):
    __tablename__ = "budget"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("tenant_id", "project_id", "period", postgresql_nulls_not_distinct=True),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    period: Mapped[str] = mapped_column(Text, nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    alert_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("80"))
    hard_stop: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class BudgetReservation(Base):
    """The cost a call in flight may reach (spec 13.5): counted with the spend when budgets are decided."""

    __tablename__ = "budget_reservation"
    __table_args__ = (Index("budget_reservation_tenant", "tenant_id", "created_at"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    created_at: Mapped[datetime] = _now()


class BudgetAlert(Base):
    __tablename__ = "budget_alert"
    __table_args__ = (
        UniqueConstraint("budget_id", "level", "period_key"),
        ForeignKeyConstraint(["budget_id", "tenant_id"], ["budget.id", "budget.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    budget_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(Text, nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    triggered_at: Mapped[datetime] = _now()


# Agent and skill catalog, source options, target options, compatibility rules and pipeline templates (migration
# 0006). Global data written by catalog-sync; `current` marks the version the repository files define now.
class AgentDefinition(Base):
    __tablename__ = "agent_definition"
    __table_args__ = (Index("agent_definition_current_key", "key", unique=True, postgresql_where=text("current")),)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_es: Mapped[str] = mapped_column(Text, nullable=False)
    agent_group: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    description_es: Mapped[str] = mapped_column(Text, nullable=False)
    phases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    tools: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    level: Mapped[str] = mapped_column(Text, nullable=False)
    default_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    relative_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    recommend: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    synced_at: Mapped[datetime] = _now()


class SkillDefinition(Base):
    __tablename__ = "skill_definition"
    __table_args__ = (Index("skill_definition_current_key", "key", unique=True, postgresql_where=text("current")),)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skill_type: Mapped[str] = mapped_column(Text, nullable=False)
    agents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    technologies: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    conflicts: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    requires: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    eval_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = _now()


class SourceAdapterDefinition(Base):
    __tablename__ = "source_adapter"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    validation: Mapped[str] = mapped_column(Text, nullable=False)


class SourceOptionDefinition(Base):
    __tablename__ = "source_option"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    flows: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    adapter_key: Mapped[str | None] = mapped_column(ForeignKey("source_adapter.key"))
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class TargetOptionDefinition(Base):
    __tablename__ = "target_option"
    axis: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str | None] = mapped_column(Text)
    wave: Mapped[int | None] = mapped_column(Integer)
    versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class CompatibilityRuleDefinition(Base):
    __tablename__ = "compatibility_rule"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class PipelineTemplateDefinition(Base):
    __tablename__ = "pipeline_template"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_gates: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    default_autonomy: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectConfig(Base):
    """One version of a project's configuration; never updated (a change is a new version)."""

    __tablename__ = "project_config"
    __table_args__ = (
        UniqueConstraint("project_id", "version", "tenant_id"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    sources: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    target: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    pipeline_template: Mapped[str] = mapped_column(ForeignKey("pipeline_template.key"), nullable=False)
    autonomy: Mapped[str] = mapped_column(Text, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    sampling_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class ProjectAgent(Base):
    __tablename__ = "project_agent"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "config_version", "tenant_id"],
            ["project_config.project_id", "project_config.version", "project_config.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["agent_key", "agent_version"], ["agent_definition.key", "agent_definition.version"]),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_key: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_version: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class ProjectSkill(Base):
    __tablename__ = "project_skill"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "config_version", "tenant_id"],
            ["project_config.project_id", "project_config.version", "project_config.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["skill_key", "skill_version"], ["skill_definition.key", "skill_definition.version"]),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_key: Mapped[str] = mapped_column(Text, primary_key=True)
    skill_version: Mapped[str] = mapped_column(Text, nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False)


class InputArtifact(Base):
    __tablename__ = "input_artifact"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "name", "version"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        Index("input_artifact_project_idx", "project_id", "kind", "name"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    findings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    rejection_code: Mapped[str | None] = mapped_column(Text)
    rejection_detail: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectRepository(Base):
    __tablename__ = "project_repository"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    # Where the token lives in the secrets store (ADR-0007); never the token itself.
    vault_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="untested")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


# Integrations of the tenant (migration 0011, ADR-0018): Figma now, Jira / Azure DevOps / Git in M7b.
class TenantIntegration(Base):
    __tablename__ = "tenant_integration"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("id", "tenant_id", name="tenant_integration_id_tenant"),
        Index("tenant_integration_kind", "tenant_id", "kind"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Where the token lives in the secrets store (ADR-0007); never the token itself.
    vault_path: Mapped[str | None] = mapped_column(Text)
    account: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_detail: Mapped[str | None] = mapped_column(Text)
    # Where the tool is (Jira site and e-mail, Azure DevOps organization URL; migration 0012). Never a credential.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


# A source adapter the tenant declared (migration 0023, ADR-0039): patterns the platform runs, never code.
class TenantAdapter(Base):
    __tablename__ = "tenant_adapter"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default="experimental")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


# A pack profile of the tenant (migration 0024, ADR-0040): a package root and conventions, never a pack.
class TenantPackProfile(Base):
    __tablename__ = "tenant_pack_profile"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[str | None] = mapped_column(Text)
    package_root: Mapped[str | None] = mapped_column(Text)
    conventions: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


# The backlog of a project in Jira or Azure DevOps (migration 0012, ADR-0019).
class ProjectBacklog(Base):
    __tablename__ = "project_backlog"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["integration_id", "tenant_id"], ["tenant_integration.id", "tenant_integration.tenant_id"],
                             ondelete="RESTRICT"),
    )  # fmt: skip
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    integration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_project: Mapped[str] = mapped_column(Text, nullable=False)
    types: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    states: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class WorkItemLink(Base):
    __tablename__ = "work_item_link"
    __table_args__ = (
        UniqueConstraint("project_id", "integration_id", "element"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["integration_id", "tenant_id"], ["tenant_integration.id", "tenant_integration.tenant_id"],
                             ondelete="CASCADE"),
    )  # fmt: skip
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    integration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    element: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_key: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class BugFix(Base):
    __tablename__ = "bug_fix"
    __table_args__ = (
        UniqueConstraint("project_id", "element", "iteration"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    element: Mapped[str] = mapped_column(Text, nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    files_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


# Runs of the project pipeline (migration 0007). The queue (procrastinate_*) and the LangGraph checkpointer
# (checkpoint*) are infrastructure outside this mapping (ADR-0009).
class Run(Base):
    __tablename__ = "run"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["project_id", "config_version", "tenant_id"],
            ["project_config.project_id", "project_config.version", "project_config.tenant_id"],
        ),
        Index("run_project_idx", "project_id", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    waiting_reason: Mapped[str | None] = mapped_column(Text)
    current_phase: Mapped[str | None] = mapped_column(Text)
    autonomy: Mapped[str] = mapped_column(Text, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    retry_from: Mapped[str | None] = mapped_column(Text)  # the phase a retry starts from (ADR-0035)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class PhaseRun(Base):
    __tablename__ = "phase_run"
    __table_args__ = (ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    phase: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentInvocation(Base):
    __tablename__ = "agent_invocation"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),
        Index("agent_invocation_run_idx", "run_id", "started_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    agent_key: Mapped[str] = mapped_column(Text, nullable=False)
    shard: Mapped[str | None] = mapped_column(Text)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Gate(Base):
    __tablename__ = "gate"
    __table_args__ = (ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gate: Mapped[str] = mapped_column(Text, primary_key=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    requested_at: Mapped[datetime] = _now()
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        Index("question_open_idx", "project_id", postgresql_where=text("status = 'open'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    agent_key: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str] = mapped_column(Text, nullable=False)
    recommended: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    alternatives: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    affects: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    answer: Mapped[str | None] = mapped_column(Text)
    was_recommended: Mapped[bool | None] = mapped_column(Boolean)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class ActivityEvent(Base):
    __tablename__ = "activity_event"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),
        Index("activity_event_project_idx", "project_id", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_key: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = _now()


# The spec, user stories and the plan (migration 0008). Append-only: every change is a new version row.
class SpecElement(Base):
    __tablename__ = "spec_element"
    __table_args__ = (
        UniqueConstraint("project_id", "element_type", "key", "version"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        Index("spec_element_current_idx", "project_id", "element_type", "key", text("version DESC")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    element_type: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="extracted")
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class UserStory(Base):
    __tablename__ = "user_story"
    __table_args__ = (
        UniqueConstraint("project_id", "key"),
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()


class UserStoryVersion(Base):
    __tablename__ = "user_story_version"
    __table_args__ = (
        ForeignKeyConstraint(["story_id", "tenant_id"], ["user_story.id", "user_story.tenant_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    links: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="P1")
    estimate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="extracted")
    out_of_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    merged_into: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default="create")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class StoryDependency(Base):
    __tablename__ = "story_dependency"
    __table_args__ = (
        ForeignKeyConstraint(["story_id", "tenant_id"], ["user_story.id", "user_story.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["depends_on", "tenant_id"], ["user_story.id", "user_story.tenant_id"], ondelete="CASCADE"
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    depends_on: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    strength: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="graph")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class MigrationPlan(Base):
    __tablename__ = "migration_plan"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    waves: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    suggested: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class IvvMappingVersion(Base):
    """The mapping of an independent validation as a person corrected it before C2 (ADR-0025)."""

    __tablename__ = "ivv_mapping_version"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    problems: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifact"
    __table_args__ = (
        UniqueConstraint("run_id", "path"),
        ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    layer: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rules: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = _now()


class Verdict(Base):
    __tablename__ = "verdict"
    __table_args__ = (
        UniqueConstraint("run_id", "module"),
        ForeignKeyConstraint(["run_id", "tenant_id"], ["run.id", "run.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    checks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    not_proven: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    proof_pack_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Evaluation(Base):
    __tablename__ = "evaluation"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    reference_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()


class DesignSystem(Base):
    __tablename__ = "design_system"
    __table_args__ = (
        UniqueConstraint("project_id", "version"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class Prototype(Base):
    __tablename__ = "prototype"
    __table_args__ = (
        UniqueConstraint("project_id", "screen_key", "version"),
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    screen_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_key: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class PrototypeComment(Base):
    __tablename__ = "prototype_comment"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    prototype_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prototype.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    anchor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class UiChatMessage(Base):
    __tablename__ = "ui_chat_message"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        Index("ui_chat_message_screen", "project_id", "screen_key", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    screen_key: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="done")
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    prototype_version: Mapped[int | None] = mapped_column(Integer)
    question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


# How a tenant signs in (migration 0013, ADR-0022).
class TenantIdentity(Base):
    __tablename__ = "tenant_identity"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    local_accounts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sso: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    second_factor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    organization_id: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = _now()


# An identity provider of a tenant, a Keycloak identity provider linked to its Organization. No secret is stored.
class TenantIdentityProvider(Base):
    __tablename__ = "tenant_identity_provider"
    __table_args__ = (
        UniqueConstraint("tenant_id", "display_name"),
        Index("tenant_identity_provider_domains", "domains", postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    sso_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    jit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    group_roles: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    default_role: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


# SCIM 2.0 of a tenant (migration 0019, ADR-0031). The bearer of the identity provider is kept as a SHA-256 digest only.
class ScimAccess(Base):
    __tablename__ = "scim_access"
    __table_args__ = (
        Index("scim_access_active", "tenant_id", unique=True, postgresql_where=text("revoked_at IS NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    access_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    hint: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


class ScimUser(Base):
    __tablename__ = "scim_user"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["membership.tenant_id", "membership.user_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("tenant_id", "user_id"),
        Index("scim_user_name_key", "tenant_id", func.lower(text("user_name")), unique=True),
        Index("scim_user_external_id", "tenant_id", "external_id"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    keycloak_id: Mapped[str | None] = mapped_column(Text)
    user_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    given_name: Mapped[str | None] = mapped_column(Text)
    family_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ScimGroup(Base):
    __tablename__ = "scim_group"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        Index("scim_group_name_key", "tenant_id", func.lower(text("display_name")), unique=True),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ScimGroupMember(Base):
    __tablename__ = "scim_group_member"
    __table_args__ = (
        ForeignKeyConstraint(["group_id", "tenant_id"], ["scim_group.id", "scim_group.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["member_id", "tenant_id"], ["scim_user.id", "scim_user.tenant_id"], ondelete="CASCADE"),
        Index("scim_group_member_member", "member_id"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


# A delivery of a project (migration 0014, ADR-0023): pushed to a branch of the customer's repository, or a ZIP.
class Release(Base):
    __tablename__ = "release"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["project.id", "project.tenant_id"], ondelete="CASCADE"),
        Index("release_project", "project_id", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    repository_url: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(Text)
    base_sha: Mapped[str | None] = mapped_column(Text)
    files: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    findings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


# An API or worker process of the platform (migration 0015, ADR-0024); written through platform_heartbeat().
class PlatformInstance(Base):
    __tablename__ = "platform_instance"
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    component: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
