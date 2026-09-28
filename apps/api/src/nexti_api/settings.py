"""Runtime configuration, read from environment variables (never from the repository).

In development, `infra/docker-compose/init_env.py` writes `apps/api/.env` with the local service URLs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "staging", "production"]

API_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", extra="ignore")

    app_env: AppEnv = "production"
    # Sign-in with a seeded user and no password (spec 15.1, D-27). The API refuses to start with it enabled
    # outside development and test (see main.create_app).
    dev_auth_enabled: bool = False
    log_level: str = "INFO"

    # PostgreSQL as the runtime role (no BYPASSRLS): postgresql+asyncpg://platform_app:...@host:port/platform
    database_url: SecretStr = SecretStr("")
    # Schema owner, used only by Alembic, the dev seed and tests; the running API never connects with it.
    migration_database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    # Keycloak as reached by the API (back channel) and as seen by the browser (redirects and token issuer).
    keycloak_url: str = ""
    keycloak_public_url: str = ""
    keycloak_realm: str = "nexti"
    oidc_client_id: str = "nexti-bff"
    oidc_client_secret: SecretStr = SecretStr("")
    # Least-privilege service account for the Admin REST API (invitations, events): manage-users, view-events.
    keycloak_admin_client_id: str = "nexti-admin"
    keycloak_admin_client_secret: SecretStr = SecretStr("")
    invitation_days: int = 7
    # Keycloak events copied to the audit log every N seconds (0 disables the background poller).
    keycloak_events_interval_seconds: int = 30
    # Origin of the web app; the OIDC callback goes through it (Vite proxy in development).
    web_origin: str = "http://localhost:5173"

    # BFF session (spec 15.1): idle timeout, absolute lifetime, encryption of what is stored in Redis.
    session_secret: SecretStr = SecretStr("")
    session_idle_seconds: int = 1800
    session_max_seconds: int = 43200
    # __Host- cookies must be Secure; browsers accept Secure cookies on http://localhost.
    session_cookie_secure: bool = True
    openfga_url: str = ""
    openfga_api_key: SecretStr = SecretStr("")
    # Outside development/test the store and model are pinned; locally they are created/updated from the repo.
    openfga_store_name: str = "nexti"
    openfga_store_id: str = ""
    openfga_model_id: str = ""
    # OpenFGA outbox relay (role authz_relay) and periodic reconciliation (0 disables it).
    authz_relay_database_url: SecretStr = SecretStr("")
    relay_poll_seconds: float = 1.0
    reconcile_interval_seconds: int = 600

    @property
    def is_local(self) -> bool:
        return self.app_env in ("development", "test")

    @property
    def keycloak_issuer(self) -> str:
        """Back-channel base URL of the realm (discovery, token, JWKS, logout)."""
        return f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def keycloak_public_issuer(self) -> str:
        """The `iss` of the tokens and the base of the browser redirects."""
        base = self.keycloak_public_url or self.keycloak_url
        return f"{base.rstrip('/')}/realms/{self.keycloak_realm}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
