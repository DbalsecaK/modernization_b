"""Worker configuration, read from environment variables (never from the repository).

In development, `infra/docker-compose/init_env.py` writes `apps/worker/.env` with the local service URLs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_DIR = Path(__file__).resolve().parents[2]


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=WORKER_DIR / ".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "production"
    log_level: str = "INFO"
    # The runtime role (no BYPASSRLS): postgresql+asyncpg://platform_app:...@host:port/platform. The queue and the
    # checkpointer use the same database through psycopg.
    database_url: SecretStr = SecretStr("")
    concurrency: int = 4
    # Heartbeats and stalled jobs: a job whose worker stopped sending heartbeats is retried by another worker.
    heartbeat_seconds: float = 5
    stalled_after_seconds: float = 20
    object_store_url: str = ""
    object_store_access_key: str = ""
    object_store_secret_key: SecretStr = SecretStr("")
    object_store_bucket: str = "platform"
    secrets_url: str = ""
    secrets_token: SecretStr = SecretStr("")
    secrets_mount: str = "secret"
    # Only for local tests against a Git server on the developer's machine; never outside development/test.
    git_allow_private_hosts: bool = False
    sandbox_image: str = ""
    sandbox_docker: str = "docker"

    @property
    def is_local(self) -> bool:
        return self.app_env in ("development", "test")

    @property
    def psycopg_dsn(self) -> str:
        return self.database_url.get_secret_value().replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
