"""Model profiles (spec 12.3): offering + normalized effort + limits + fallback chain."""

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.ai.common import ConfigureModels, gateway_service
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.ai_catalog import TEST_PHASE
from nexti_core.db.models import ModelOffering, ModelProfile, ModelVersion, ProviderConnection
from nexti_model_gateway.gateway import (
    BudgetExceededError,
    CallContext,
    GatewayError,
    PolicyDeniedError,
)

router = APIRouter(prefix="/api/v1/ai/profiles", tags=["ai"])
Effort = Literal["low", "medium", "high", "max"]
MAX_CHAIN = 5


class ProfileOut(ApiModel):
    id: uuid.UUID
    name: str
    connection_id: uuid.UUID
    offering_id: uuid.UUID
    model: str
    upstream_provider: str
    effort: Effort
    max_output_tokens: int
    temperature: Decimal | None
    timeout_seconds: int
    max_retries: int
    fallback_profile_id: uuid.UUID | None


class ProfileIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    connection_id: uuid.UUID
    offering_id: uuid.UUID
    effort: Effort = "medium"
    max_output_tokens: int = Field(default=4096, ge=1, le=1_000_000)
    temperature: Decimal | None = Field(default=None, ge=0, le=2)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_retries: int = Field(default=2, ge=0, le=10)
    fallback_profile_id: uuid.UUID | None = None


class ProfileTestOut(ApiModel):
    ok: bool
    content: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    provider_cost_usd: Decimal | None
    was_fallback: bool
    error_code: str | None


COLUMNS = (
    ModelProfile.id,
    ModelProfile.name,
    ModelProfile.connection_id,
    ModelProfile.offering_id,
    ModelVersion.provider_slug.label("model"),
    ModelOffering.upstream_provider,
    ModelProfile.effort,
    ModelProfile.max_output_tokens,
    ModelProfile.temperature,
    ModelProfile.timeout_seconds,
    ModelProfile.max_retries,
    ModelProfile.fallback_profile_id,
)


def _query() -> Any:
    return (
        select(*COLUMNS)
        .join(ModelOffering, ModelOffering.id == ModelProfile.offering_id)
        .join(ModelVersion, ModelVersion.id == ModelOffering.version_id)
    )


async def _load(conn: AsyncConnection, profile_id: uuid.UUID) -> ProfileOut:
    row = (await conn.execute(_query().where(ModelProfile.id == profile_id))).one_or_none()
    if row is None:
        raise not_found("profile")
    return ProfileOut.model_validate(row, from_attributes=True)


async def _validate(conn: AsyncConnection, body: ProfileIn, profile_id: uuid.UUID | None) -> None:
    if (
        await conn.execute(select(ProviderConnection.id).where(ProviderConnection.id == body.connection_id))
    ).first() is None:
        raise not_found("connection")
    offering = (
        await conn.execute(
            select(ModelOffering.status, ModelOffering.max_output_tokens, ModelVersion.provider_slug)
            .join(ModelVersion, ModelVersion.id == ModelOffering.version_id)
            .where(ModelOffering.id == body.offering_id)
        )
    ).one_or_none()
    if offering is None:
        raise not_found("offering")
    if offering.status != "available":
        raise ProblemError(422, "offering_unavailable", "The offering is not available.")
    # Fixed versions only (rule 10): aliases that move to a newer model are not assignable.
    if "latest" in offering.provider_slug:
        raise ProblemError(422, "alias_not_allowed", "Only fixed model versions can be used, not aliases.")
    if offering.max_output_tokens and body.max_output_tokens > offering.max_output_tokens:
        raise ProblemError(
            422, "max_output_too_high", f"The offering allows at most {offering.max_output_tokens} output tokens."
        )
    # The fallback chain must end: no cycles, bounded depth.
    if body.fallback_profile_id is None:
        return
    fallback = select(ModelProfile.id).where(ModelProfile.id == body.fallback_profile_id)
    if (await conn.execute(fallback)).first() is None:
        raise not_found("fallback_profile")
    seen: set[uuid.UUID] = {profile_id} if profile_id else set()
    next_id: uuid.UUID | None = body.fallback_profile_id
    for _ in range(MAX_CHAIN):
        if next_id is None:
            return
        if next_id in seen:
            raise ProblemError(422, "fallback_cycle", "The fallback chain loops back to this profile.")
        seen.add(next_id)
        next_id = (
            await conn.execute(select(ModelProfile.fallback_profile_id).where(ModelProfile.id == next_id))
        ).scalar_one_or_none()
    if next_id is not None:
        raise ProblemError(422, "fallback_chain_too_long", f"A fallback chain has at most {MAX_CHAIN} profiles.")


@router.get("", response_model=list[ProfileOut])
async def list_profiles(request: Request, auth: ConfigureModels) -> list[ProfileOut]:
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(_query().order_by(ModelProfile.name))).all()
    return [ProfileOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=ProfileOut, status_code=201)
async def create_profile(request: Request, body: ProfileIn, auth: ConfigureModels) -> ProfileOut:
    try:
        async with transaction(request, auth) as conn:
            await _validate(conn, body, None)
            profile_id = (
                await conn.execute(
                    insert(ModelProfile)
                    .values(tenant_id=auth.tenant_id, **body.model_dump(by_alias=False))
                    .returning(ModelProfile.id)
                )
            ).scalar_one()
            await audit(conn, auth, "ai.profile_create", f"profile:{profile_id}", {"name": body.name})
            return await _load(conn, profile_id)
    except IntegrityError as exc:
        raise ProblemError(409, "profile_name_taken", "A profile with that name already exists.") from exc


@router.put("/{profile_id}", response_model=ProfileOut)
async def update_profile(request: Request, profile_id: uuid.UUID, body: ProfileIn, auth: ConfigureModels) -> ProfileOut:
    try:
        async with transaction(request, auth) as conn:
            await _load(conn, profile_id)
            await _validate(conn, body, profile_id)
            await conn.execute(
                update(ModelProfile).where(ModelProfile.id == profile_id).values(**body.model_dump(by_alias=False))
            )
            await audit(conn, auth, "ai.profile_update", f"profile:{profile_id}", {"name": body.name})
            return await _load(conn, profile_id)
    except IntegrityError as exc:
        raise ProblemError(409, "profile_name_taken", "A profile with that name already exists.") from exc


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(request: Request, profile_id: uuid.UUID, auth: ConfigureModels) -> None:
    """Assignments that use the profile go with it; profiles that fall back to it lose their fallback."""
    async with transaction(request, auth) as conn:
        await _load(conn, profile_id)
        await conn.execute(delete(ModelProfile).where(ModelProfile.id == profile_id))
        await audit(conn, auth, "ai.profile_delete", f"profile:{profile_id}")


@router.post("/{profile_id}:test", response_model=ProfileTestOut)
async def test_profile(request: Request, profile_id: uuid.UUID, auth: ConfigureModels) -> ProfileTestOut:
    """A minimal real call through the gateway; it is recorded in the usage ledger like any other call."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        await _load(conn, profile_id)
    context = CallContext(tenant_id=auth.tenant_id, phase=TEST_PHASE)
    messages = [{"role": "user", "content": "Reply with the single word: ok"}]
    try:
        result = await gateway_service(request).complete(context, messages, profile_id=profile_id, max_tokens=16)
        out = ProfileTestOut(
            ok=True,
            content=result.content,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.cost_usd,
            provider_cost_usd=result.provider_cost_usd,
            was_fallback=result.was_fallback,
            error_code=None,
        )
    except (BudgetExceededError, PolicyDeniedError) as exc:
        out = ProfileTestOut(
            ok=False, content=None, input_tokens=0, output_tokens=0, cost_usd=Decimal(0), provider_cost_usd=None,
            was_fallback=False, error_code=exc.code,
        )  # fmt: skip
    except GatewayError as exc:
        out = ProfileTestOut(
            ok=False, content=None, input_tokens=0, output_tokens=0, cost_usd=Decimal(0), provider_cost_usd=None,
            was_fallback=False, error_code=f"{exc.code}: {exc}"[:200],
        )  # fmt: skip
    # A test spends money on the tenant's account: it is a sensitive action like any other configuration change.
    async with transaction(request, auth) as conn:
        await audit(
            conn, auth, "ai.profile_test", f"profile:{profile_id}", {"ok": out.ok, "cost_usd": str(out.cost_usd)},
            outcome="success" if out.ok else "failure",
        )  # fmt: skip
    return out
