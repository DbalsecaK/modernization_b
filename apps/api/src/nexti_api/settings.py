"""Runtime configuration, read from environment variables (never from the repository)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: AppEnv = "production"
    # Sign-in with a seeded user and no password (spec 15.1, D-27). Only allowed in development and test.
    dev_auth: bool = False

    @property
    def is_local(self) -> bool:
        return self.app_env in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
