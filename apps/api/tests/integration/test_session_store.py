"""Session store against the real Redis: idle timeout, absolute lifetime, hashed keys, encrypted records."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from nexti_api.auth.session import SessionStore
from nexti_api.settings import Settings

from .conftest import SETTINGS


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(SETTINGS.redis_url.get_secret_value())
    yield client
    await client.aclose()


def store(redis: Redis, idle: int = 60, maximum: int = 3600) -> SessionStore:
    settings = Settings(
        app_env="test", session_secret=SecretStr("test-secret"), session_idle_seconds=idle, session_max_seconds=maximum
    )
    return SessionStore(redis, settings)


async def test_the_record_is_encrypted_under_a_hashed_key(redis: Redis) -> None:
    s = store(redis)
    session_id, _ = await s.create(
        user_id=uuid.uuid4(),
        auth_method="keycloak",
        active_tenant_id=None,
        refresh_token="very-secret-refresh",  # noqa: S106 (test value)
    )
    keys = [k.decode() async for k in redis.scan_iter("nexti:session:*")]
    assert all(session_id not in k for k in keys)
    raw = await redis.get(SessionStore._key("session", session_id))
    assert raw is not None
    assert b"very-secret-refresh" not in raw
    await s.delete(session_id)


async def test_idle_sessions_expire(redis: Redis) -> None:
    s = store(redis, idle=1)
    session_id, _ = await s.create(user_id=uuid.uuid4(), auth_method="keycloak", active_tenant_id=None)
    assert await s.get(session_id) is not None
    await asyncio.sleep(1.5)
    assert await s.get(session_id) is None


async def test_activity_does_not_extend_past_the_absolute_lifetime(redis: Redis) -> None:
    s = store(redis)
    session_id, session = await s.create(user_id=uuid.uuid4(), auth_method="keycloak", active_tenant_id=None)
    await s.update(session_id, session, created_at=time.time() - 3601)
    assert await s.get(session_id) is None


async def test_a_record_written_with_another_secret_is_rejected(redis: Redis) -> None:
    session_id, _ = await store(redis).create(user_id=uuid.uuid4(), auth_method="keycloak", active_tenant_id=None)
    other = SessionStore(redis, Settings(app_env="test", session_secret=SecretStr("another-secret")))
    assert await other.get(session_id) is None


async def test_login_state_is_single_use(redis: Redis) -> None:
    s = store(redis)
    await s.save_login("state-1", {"binding": "b"})
    assert await s.pop_login("state-1") == {"binding": "b"}
    assert await s.pop_login("state-1") is None


async def test_the_sessions_of_a_user_end_together_or_per_tenant(redis: Redis) -> None:
    s = store(redis)
    user, tenant, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    in_tenant, _ = await s.create(user_id=user, auth_method="keycloak", active_tenant_id=tenant)
    elsewhere, _ = await s.create(user_id=user, auth_method="keycloak", active_tenant_id=other)
    someone_else, _ = await s.create(user_id=uuid.uuid4(), auth_method="keycloak", active_tenant_id=tenant)
    assert await s.revoke_user(user, tenant) == 1
    assert await s.get(in_tenant) is None
    assert await s.get(elsewhere) is not None
    assert await s.revoke_user(user) == 1
    assert await s.get(elsewhere) is None
    assert await s.get(someone_else) is not None
