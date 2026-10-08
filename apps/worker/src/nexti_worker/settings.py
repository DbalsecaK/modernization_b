"""Worker configuration, read from environment variables (never from the repository).

In development, `infra/docker-compose/init_env.py` writes `apps/worker/.env` with the local service URLs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
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
    # Dependencies of the generated code in OSV (ADR-0023); empty turns the check off (offline deployments).
    osv_url: str = "https://api.osv.dev"
    sandbox_image: str = ""
    sandbox_docker: str = "docker"
    # The bridge that runs RPG programs on a customer's IBM i (ADR-0053).
    ibmi_bridge_image: str = "nexti-ibmi-bridge:1"
    # Models (M4): through the gateway with the tenant's connection; OpenRouter base URL for tests.
    openrouter_url: str | None = None
    # False in the air-gapped profile (ADR-0030): OpenRouter is never called, only openai-compatible servers.
    openrouter_enabled: bool = True
    model_servers_allow_private_hosts: bool = False  # air-gapped: local model servers on private hosts
    # Figma REST API base (ADR-0018); empty: Figma is not read (air-gapped profile, ADR-0030).
    figma_url: str = "https://api.figma.com/v1"
    # Recorded responses (ADR-0012), development and test only: a folder and replay|record.
    model_cassettes_dir: str = ""
    model_cassettes_mode: Literal["", "replay", "record"] = ""
    # Knowledge graph (M4), through packages/graph only.
    graph_uri: str = ""
    graph_user: str = "neo4j"
    graph_password: SecretStr = SecretStr("")
    # Golden master (M4): run the legacy live in its engine, or (development and test) replay/record a folder.
    golden_master_mode: Literal["live", "replay", "record"] = "live"
    golden_master_dir: str = ""

    @model_validator(mode="after")
    def cassettes_only_locally(self) -> "WorkerSettings":
        if (self.model_cassettes_dir or self.model_cassettes_mode) and not self.is_local:
            raise ValueError("recorded model responses are only allowed in development and test")
        if bool(self.model_cassettes_dir) != bool(self.model_cassettes_mode):
            raise ValueError("MODEL_CASSETTES_DIR and MODEL_CASSETTES_MODE go together")
        if self.golden_master_mode != "live" and not (self.is_local and self.golden_master_dir):
            raise ValueError("a recorded golden master needs GOLDEN_MASTER_DIR and is only for development and test")
        return self

    @property
    def is_local(self) -> bool:
        return self.app_env in ("development", "test")

    @property
    def psycopg_dsn(self) -> str:
        return self.database_url.get_secret_value().replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
