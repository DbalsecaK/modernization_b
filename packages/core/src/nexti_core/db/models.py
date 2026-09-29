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
    id: Mapped[uuid.UUID] = _uuid_pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_family.id"), nullable=False)
    provider_slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
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
    __table_args__ = (UniqueConstraint("version_id", "provider", "upstream_provider"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_version.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
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
    flow: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_key: Mapped[str | None] = mapped_column(ForeignKey("source_adapter.key"))
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))


class TargetOptionDefinition(Base):
    __tablename__ = "target_option"
    axis: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str | None] = mapped_column(Text)
    wave: Mapped[int | None] = mapped_column(Integer)


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
