"""Model catalog (spec 12.2, 12.3, 13.3): global data from the provider, shown with the tenant's policy applied."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.ai.common import ConfigureModels, gateway_service, require_openrouter
from nexti_api.authz.require import Authorized, require_platform
from nexti_api.schemas import ApiModel
from nexti_core.db.models import (
    EffortMapping,
    ModelFamily,
    ModelOffering,
    ModelPolicy,
    ModelVersion,
    PriceVersion,
)
from nexti_model_gateway.rules import OfferingFacts, Policy, policy_denial
from nexti_model_gateway.service import Pricing

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
SuperAdmin = Annotated[Authorized, Depends(require_platform("superAdmin"))]
Effort = Literal["low", "medium", "high", "max"]


class PriceOut(ApiModel):
    id: uuid.UUID
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_read_per_mtok: Decimal | None
    cache_write_per_mtok: Decimal | None
    request_usd: Decimal | None
    valid_from: datetime
    valid_to: datetime | None
    source: Literal["provider_sync", "manual"]


class OfferingOut(ApiModel):
    id: uuid.UUID
    provider: Literal["openrouter", "openai-compatible"]
    # openai-compatible: the tenant's connection that serves it (ADR-0030); None for OpenRouter.
    connection_id: uuid.UUID | None
    upstream_provider: str
    context_window: int | None
    max_output_tokens: int | None
    capabilities: list[str]
    zdr: bool
    status: Literal["available", "unavailable"]
    price: PriceOut | None
    allowed_by_policy: bool
    policy_reason: str | None


class VersionOut(ApiModel):
    id: uuid.UUID
    family: str
    provider_slug: str
    canonical_slug: str
    name: str
    context_window: int | None
    capabilities: list[str]
    status: Literal["available", "deprecated"]
    offerings: list[OfferingOut]


class SyncOut(ApiModel):
    families: int
    versions: int


class LoadOut(ApiModel):
    offerings: int


class EffortMappingIn(ApiModel):
    parameters: dict[Effort, dict[str, Any]]


class ManualPriceIn(ApiModel):
    input_per_mtok: Decimal = Field(ge=0)
    output_per_mtok: Decimal = Field(ge=0)
    cache_read_per_mtok: Decimal | None = Field(default=None, ge=0)
    cache_write_per_mtok: Decimal | None = Field(default=None, ge=0)
    request_usd: Decimal | None = Field(default=None, ge=0)


async def tenant_policy(conn: AsyncConnection) -> Policy:
    row = (await conn.execute(select(ModelPolicy))).first()
    if row is None:
        return Policy()
    return Policy(
        openrouter_allowed=row.openrouter_allowed,
        allowed_upstream_providers=tuple(row.allowed_upstream_providers)
        if row.allowed_upstream_providers is not None
        else None,
        denied_upstream_providers=tuple(row.denied_upstream_providers),
        require_zdr=row.require_zdr,
        deny_data_collection=row.deny_data_collection,
    )


def _price(row: Any) -> PriceOut | None:
    if row.price_id is None:
        return None
    return PriceOut(
        id=row.price_id,
        input_per_mtok=row.input_per_mtok,
        output_per_mtok=row.output_per_mtok,
        cache_read_per_mtok=row.cache_read_per_mtok,
        cache_write_per_mtok=row.cache_write_per_mtok,
        request_usd=row.request_usd,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        source=row.source,
    )


@router.get("/catalog", response_model=list[VersionOut])
async def list_catalog(
    request: Request, auth: ConfigureModels, search: str | None = None, only_offered: bool = False
) -> list[VersionOut]:
    async with transaction(request, auth) as conn:
        policy = await tenant_policy(conn)
        query = (
            select(ModelVersion, ModelFamily.key.label("family"))
            .join(ModelFamily, ModelFamily.id == ModelVersion.family_id)
            .order_by(ModelVersion.provider_slug)
        )
        if search:
            query = query.where(
                ModelVersion.provider_slug.ilike(f"%{search}%") | ModelVersion.name.ilike(f"%{search}%")
            )
        versions = (await conn.execute(query)).all()
        offerings = (
            await conn.execute(
                select(
                    ModelOffering,
                    PriceVersion.id.label("price_id"),
                    PriceVersion.input_per_mtok,
                    PriceVersion.output_per_mtok,
                    PriceVersion.cache_read_per_mtok,
                    PriceVersion.cache_write_per_mtok,
                    PriceVersion.request_usd,
                    PriceVersion.valid_from,
                    PriceVersion.valid_to,
                    PriceVersion.source,
                ).outerjoin(
                    PriceVersion,
                    (PriceVersion.offering_id == ModelOffering.id) & PriceVersion.valid_to.is_(None),
                )
            )
        ).all()
    by_version: dict[uuid.UUID, list[OfferingOut]] = {}
    for o in offerings:
        offering = o
        reason = policy_denial(policy, OfferingFacts(offering.provider, offering.upstream_provider, offering.zdr))
        by_version.setdefault(offering.version_id, []).append(
            OfferingOut(
                id=offering.id,
                provider=offering.provider,
                connection_id=offering.connection_id,
                upstream_provider=offering.upstream_provider,
                context_window=offering.context_window,
                max_output_tokens=offering.max_output_tokens,
                capabilities=list(offering.capabilities),
                zdr=offering.zdr,
                status=offering.status,
                price=_price(o),
                allowed_by_policy=reason is None,
                policy_reason=reason,
            )
        )
    out = []
    for v in versions:
        version = v
        offered = sorted(by_version.get(version.id, []), key=lambda x: x.upstream_provider)
        if only_offered and not offered:
            continue
        out.append(
            VersionOut(
                id=version.id,
                family=v.family,
                provider_slug=version.provider_slug,
                canonical_slug=version.canonical_slug,
                name=version.name,
                context_window=version.context_window,
                capabilities=list(version.capabilities),
                status=version.status,
                offerings=offered,
            )
        )
    return out


@router.post("/catalog:sync", response_model=SyncOut)
async def sync(request: Request, auth: ConfigureModels) -> SyncOut:
    """Refresh families and versions from the provider's public catalog."""
    require_openrouter(request)
    async with transaction(request, auth) as conn:
        report = await gateway_service(request).sync_catalog(conn)
        await audit(conn, auth, "ai.catalog_sync", "catalog", {"versions": report.versions})
    return SyncOut(families=report.families, versions=report.versions)


@router.post("/catalog/versions/{version_id}:load-offerings", response_model=LoadOut)
async def load(request: Request, version_id: uuid.UUID, auth: ConfigureModels) -> LoadOut:
    """Load the upstream providers of one model with their current prices."""
    require_openrouter(request)
    async with transaction(request, auth) as conn:
        if (await conn.execute(select(ModelVersion.id).where(ModelVersion.id == version_id))).first() is None:
            raise not_found("model_version")
        count = await gateway_service(request).load_offerings(conn, version_id)
        await audit(conn, auth, "ai.offerings_load", f"model_version:{version_id}", {"offerings": count})
    return LoadOut(offerings=count)


async def _offering(conn: AsyncConnection, offering_id: uuid.UUID) -> None:
    if (await conn.execute(select(ModelOffering.id).where(ModelOffering.id == offering_id))).first() is None:
        raise not_found("offering")


@router.get("/offerings/{offering_id}/effort-mapping", response_model=dict[Effort, dict[str, Any]])
async def get_effort_mapping(request: Request, offering_id: uuid.UUID, auth: ConfigureModels) -> dict[str, Any]:
    """Normalized effort -> the real parameter sent to the model (spec 12.3)."""
    async with transaction(request, auth) as conn:
        await _offering(conn, offering_id)
        rows = (
            await conn.execute(
                select(EffortMapping.effort, EffortMapping.parameters).where(EffortMapping.offering_id == offering_id)
            )
        ).all()
    return {r.effort: r.parameters for r in rows}


@router.put("/offerings/{offering_id}/effort-mapping", response_model=dict[Effort, dict[str, Any]])
async def set_effort_mapping(
    request: Request, offering_id: uuid.UUID, body: EffortMappingIn, auth: SuperAdmin
) -> dict[Effort, dict[str, Any]]:
    async with transaction(request, auth) as conn:
        await _offering(conn, offering_id)
        for effort, parameters in body.parameters.items():
            await conn.execute(
                pg_insert(EffortMapping)
                .values(offering_id=offering_id, effort=effort, parameters=parameters, updated_by=auth.user_id)
                .on_conflict_do_update(
                    index_elements=["offering_id", "effort"],
                    set_={"parameters": parameters, "updated_by": auth.user_id},
                )
            )
        await audit(
            conn, auth, "ai.effort_mapping_update", f"offering:{offering_id}", {"efforts": sorted(body.parameters)},
            platform=True,
        )  # fmt: skip
    return body.parameters


@router.get("/offerings/{offering_id}/prices", response_model=list[PriceOut])
async def list_prices(request: Request, offering_id: uuid.UUID, auth: ConfigureModels) -> list[PriceOut]:
    async with transaction(request, auth) as conn:
        await _offering(conn, offering_id)
        rows = (
            await conn.execute(
                select(
                    PriceVersion.id.label("price_id"),
                    PriceVersion.input_per_mtok,
                    PriceVersion.output_per_mtok,
                    PriceVersion.cache_read_per_mtok,
                    PriceVersion.cache_write_per_mtok,
                    PriceVersion.request_usd,
                    PriceVersion.valid_from,
                    PriceVersion.valid_to,
                    PriceVersion.source,
                )
                .where(PriceVersion.offering_id == offering_id)
                .order_by(PriceVersion.valid_from.desc())
            )
        ).all()
    return [p for p in (_price(r) for r in rows) if p is not None]


@router.post("/offerings/{offering_id}/prices", response_model=list[PriceOut], status_code=201)
async def add_manual_price(
    request: Request, offering_id: uuid.UUID, body: ManualPriceIn, auth: SuperAdmin
) -> list[PriceOut]:
    """A price the provider does not report (spec 12.2). Past costs keep the version they used."""
    async with transaction(request, auth) as conn:
        await _offering(conn, offering_id)
        price = Pricing(
            body.input_per_mtok, body.output_per_mtok, body.cache_read_per_mtok, body.cache_write_per_mtok,
            body.request_usd,
        )  # fmt: skip
        await gateway_service(request).record_manual_price(conn, offering_id, price, auth.user_id)
        await audit(
            conn, auth, "ai.price_manual", f"offering:{offering_id}", body.model_dump(mode="json"), platform=True
        )
    return await list_prices(request, offering_id, auth)
