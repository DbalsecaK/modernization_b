"""Model catalog synchronization with OpenRouter (spec 12.2, 13.3): families, exact versions, offerings per
upstream provider, versioned prices and the default effort table."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_core.db.models import EffortMapping, ModelFamily, ModelOffering, ModelVersion, PriceVersion
from nexti_model_gateway.openrouter import OpenRouterClient, Pricing

EFFORTS = ("low", "medium", "high", "max")


def default_effort_parameters(capabilities: tuple[str, ...] | list[str]) -> dict[str, dict[str, Any]]:
    """OpenRouter's unified reasoning parameter. Models without reasoning get no parameter. "max" starts equal to
    "high"; the administrator can raise it (e.g. a reasoning token budget) per offering (spec 12.3)."""
    if "reasoning" not in capabilities:
        return {effort: {} for effort in EFFORTS}
    level = {"low": "low", "medium": "medium", "high": "high", "max": "high"}
    return {effort: {"reasoning": {"effort": level[effort]}} for effort in EFFORTS}


@dataclass(frozen=True)
class SyncReport:
    families: int
    versions: int


async def sync_catalog(conn: AsyncConnection, client: OpenRouterClient) -> SyncReport:
    """Upsert families and versions from the public model list. Offerings are loaded per model on demand."""
    models = await client.list_models()
    families: dict[str, uuid.UUID] = {}
    for model in models:
        key = model.provider_slug.split("/", 1)[0]
        if key not in families:
            families[key] = (
                await conn.execute(
                    pg_insert(ModelFamily)
                    .values(key=key, name=key.replace("-", " ").title())
                    .on_conflict_do_update(index_elements=["key"], set_={"key": key})
                    .returning(ModelFamily.id)
                )
            ).scalar_one()
        await conn.execute(
            pg_insert(ModelVersion)
            .values(
                family_id=families[key],
                provider_slug=model.provider_slug,
                canonical_slug=model.canonical_slug,
                name=model.name,
                context_window=model.context_window,
                capabilities=list(model.capabilities),
            )
            .on_conflict_do_update(
                index_elements=["provider_slug"],
                set_={
                    "name": model.name,
                    "context_window": model.context_window,
                    "capabilities": list(model.capabilities),
                    "status": "available",
                },
            )
        )
    return SyncReport(families=len(families), versions=len(models))


def _same_price(row: Any, price: Pricing) -> bool:
    return bool(
        row.input_per_mtok == price.input_per_mtok
        and row.output_per_mtok == price.output_per_mtok
        and row.cache_read_per_mtok == price.cache_read_per_mtok
        and row.cache_write_per_mtok == price.cache_write_per_mtok
        and row.request_usd == price.request_usd
    )


async def record_price(
    conn: AsyncConnection, offering_id: uuid.UUID, price: Pricing, source: str, by: uuid.UUID | None = None
) -> uuid.UUID:
    """Keep the current price if unchanged; otherwise close it and open a new version. Past costs keep the
    version they were computed with (spec 13.3)."""
    current = (
        await conn.execute(
            select(PriceVersion).where(PriceVersion.offering_id == offering_id, PriceVersion.valid_to.is_(None))
        )
    ).first()
    if current is not None and _same_price(current, price):
        price_id: uuid.UUID = current.id
        return price_id
    now = datetime.now(UTC)
    if current is not None:
        await conn.execute(update(PriceVersion).where(PriceVersion.id == current.id).values(valid_to=now))
    new_id: uuid.UUID = (
        await conn.execute(
            pg_insert(PriceVersion)
            .values(
                offering_id=offering_id,
                input_per_mtok=price.input_per_mtok,
                output_per_mtok=price.output_per_mtok,
                cache_read_per_mtok=price.cache_read_per_mtok,
                cache_write_per_mtok=price.cache_write_per_mtok,
                request_usd=price.request_usd,
                valid_from=now,
                source=source,
                created_by=by,
            )
            .returning(PriceVersion.id)
        )
    ).scalar_one()
    return new_id


async def load_offerings(conn: AsyncConnection, client: OpenRouterClient, version_id: uuid.UUID) -> int:
    """Create or refresh the offerings of one version (one per upstream provider) with their price and ZDR flag."""
    version = (await conn.execute(select(ModelVersion).where(ModelVersion.id == version_id))).one()
    endpoints = await client.list_endpoints(version.provider_slug)
    zdr = await client.zdr_endpoints()
    for e in endpoints:
        offering_id: uuid.UUID = (
            await conn.execute(
                pg_insert(ModelOffering)
                .values(
                    version_id=version_id,
                    provider="openrouter",
                    upstream_provider=e.upstream_provider,
                    context_window=e.context_window,
                    max_output_tokens=e.max_output_tokens,
                    capabilities=list(e.capabilities),
                    zdr=(version.provider_slug, e.upstream_provider) in zdr,
                    status="available" if e.available else "unavailable",
                )
                .on_conflict_do_update(
                    index_elements=["version_id", "provider", "upstream_provider"],
                    set_={
                        "context_window": e.context_window,
                        "max_output_tokens": e.max_output_tokens,
                        "capabilities": list(e.capabilities),
                        "zdr": (version.provider_slug, e.upstream_provider) in zdr,
                        "status": "available" if e.available else "unavailable",
                        "updated_at": datetime.now(UTC),
                    },
                )
                .returning(ModelOffering.id)
            )
        ).scalar_one()
        await record_price(conn, offering_id, e.pricing, "provider_sync")
        for effort, parameters in default_effort_parameters(e.capabilities).items():
            await conn.execute(
                pg_insert(EffortMapping)
                .values(offering_id=offering_id, effort=effort, parameters=parameters)
                .on_conflict_do_nothing()
            )
    return len(endpoints)
