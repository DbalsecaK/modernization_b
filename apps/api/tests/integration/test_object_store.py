"""Object storage against the real MinIO of docker compose (M2): write, read, check and delete an input's object."""

import io
import uuid

import pytest

from nexti_core.object_store import ObjectStore, ObjectStoreConfig, input_key

from .conftest import SETTINGS


@pytest.fixture
def store() -> ObjectStore:
    if not SETTINGS.object_store_url:
        pytest.skip("OBJECT_STORE_URL is not configured (run init_env.py)")
    return ObjectStore(
        ObjectStoreConfig(
            SETTINGS.object_store_url,
            SETTINGS.object_store_access_key,
            SETTINGS.object_store_secret_key.get_secret_value(),
            SETTINGS.object_store_bucket,
        )
    )


async def test_an_input_object_round_trip(store: ObjectStore) -> None:
    key = input_key(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    data = b"IDENTIFICATION DIVISION.\n" * 1000
    assert await store.healthy()
    await store.put(key, io.BytesIO(data), len(data), "application/zip")
    try:
        assert await store.exists(key)
        assert b"".join(await store.read(key)) == data
    finally:
        await store.delete(key)
    assert not await store.exists(key)


def test_keys_are_built_from_ids_only() -> None:
    tenant, project, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert input_key(tenant, project, item) == f"tenants/{tenant}/projects/{project}/inputs/{item}"
