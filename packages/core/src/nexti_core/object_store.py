"""Object storage for the inputs of the projects (spec 7.1, 19.1): S3 API, MinIO in development.

Keys are always built here from the tenant, the project and the input id (never from a client-supplied name), so a
file name cannot address another tenant's objects. Per-tenant encryption keys arrive with the deployments (M9).
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError as TransportError

# Anything the client can raise when the store is unreachable or refuses the request.
FAILURES = (S3Error, TransportError, OSError)


class ObjectStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObjectStoreConfig:
    url: str  # http(s)://host:port
    access_key: str
    secret_key: str
    bucket: str = "platform"
    region: str = "us-east-1"


def input_key(tenant_id: uuid.UUID, project_id: uuid.UUID, input_id: uuid.UUID) -> str:
    return f"tenants/{tenant_id}/projects/{project_id}/inputs/{input_id}"


class ObjectStore:
    def __init__(self, config: ObjectStoreConfig) -> None:
        parts = urlsplit(config.url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("the object store URL must be http(s)://host:port")
        self.config = config
        self._client = Minio(
            parts.netloc,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=parts.scheme == "https",
            region=config.region,
        )

    async def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> None:
        stream.seek(0)
        try:
            await asyncio.to_thread(
                self._client.put_object, self.config.bucket, key, stream, size, content_type=content_type
            )
        except FAILURES as exc:
            raise ObjectStoreError(f"object store write failed: {getattr(exc, 'code', type(exc).__name__)}") from exc
        finally:
            stream.seek(0)

    async def read(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """The object's content in chunks (the response is released when the iterator ends)."""
        try:
            response = await asyncio.to_thread(self._client.get_object, self.config.bucket, key)
        except FAILURES as exc:
            raise ObjectStoreError(f"object store read failed: {getattr(exc, 'code', type(exc).__name__)}") from exc

        def chunks() -> Iterator[bytes]:
            try:
                yield from response.stream(chunk_size)
            finally:
                response.close()
                response.release_conn()

        return chunks()

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.stat_object, self.config.bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return False
            raise ObjectStoreError(f"object store check failed: {exc.code}") from exc
        except (TransportError, OSError) as exc:
            raise ObjectStoreError(f"object store check failed: {type(exc).__name__}") from exc
        return True

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.remove_object, self.config.bucket, key)
        except FAILURES as exc:
            raise ObjectStoreError(f"object store delete failed: {getattr(exc, 'code', type(exc).__name__)}") from exc

    async def healthy(self) -> bool:
        try:
            return bool(await asyncio.to_thread(self._client.bucket_exists, self.config.bucket))
        except Exception:
            return False
