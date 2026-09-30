"""Connections shared by the whole process, opened at startup and closed at shutdown."""

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nexti_api.settings import Settings
from nexti_graph import GraphStore


@dataclass
class Resources:
    engine: AsyncEngine | None
    redis: Redis | None
    http: httpx.AsyncClient
    # Role authz_relay: only reads and updates the OpenFGA outbox.
    relay_engine: AsyncEngine | None = None
    # The knowledge graph (Neo4j through packages/graph only, 5.3); read-only for the API.
    graph: GraphStore | None = None

    @classmethod
    def open(cls, settings: Settings) -> "Resources":
        db_url = settings.database_url.get_secret_value()
        redis_url = settings.redis_url.get_secret_value()
        relay_url = settings.authz_relay_database_url.get_secret_value()
        return cls(
            engine=create_async_engine(db_url, pool_pre_ping=True) if db_url else None,
            redis=Redis.from_url(redis_url) if redis_url else None,
            http=httpx.AsyncClient(timeout=httpx.Timeout(5.0)),
            relay_engine=create_async_engine(relay_url, pool_pre_ping=True, pool_size=2) if relay_url else None,
            graph=GraphStore.connect(
                settings.graph_uri, settings.graph_user, settings.graph_password.get_secret_value()
            )
            if settings.graph_uri
            else None,
        )

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        if self.relay_engine is not None:
            await self.relay_engine.dispose()
        if self.redis is not None:
            await self.redis.aclose()
        if self.graph is not None:
            await self.graph.close()
        await self.http.aclose()
