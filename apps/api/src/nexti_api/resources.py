"""Connections shared by the whole process, opened at startup and closed at shutdown."""

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nexti_api.settings import Settings


@dataclass
class Resources:
    engine: AsyncEngine | None
    redis: Redis | None
    http: httpx.AsyncClient

    @classmethod
    def open(cls, settings: Settings) -> "Resources":
        db_url = settings.database_url.get_secret_value()
        redis_url = settings.redis_url.get_secret_value()
        return cls(
            engine=create_async_engine(db_url, pool_pre_ping=True) if db_url else None,
            redis=Redis.from_url(redis_url) if redis_url else None,
            http=httpx.AsyncClient(timeout=httpx.Timeout(5.0)),
        )

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        if self.redis is not None:
            await self.redis.aclose()
        await self.http.aclose()
