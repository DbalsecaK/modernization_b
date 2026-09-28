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
    # Sign-in with a seeded user and no password (spec 15.1, D-27). Only allowed in development and test.
    dev_auth: bool = False
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
