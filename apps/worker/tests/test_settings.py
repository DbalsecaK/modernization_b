"""The worker's settings: the queue and the checkpointer reach the same database as SQLAlchemy, through psycopg."""

from pydantic import SecretStr

from nexti_worker.settings import WorkerSettings


def test_the_psycopg_dsn_is_derived_from_the_database_url() -> None:
    settings = WorkerSettings(database_url=SecretStr("postgresql+asyncpg://platform_app:pw@127.0.0.1:5432/platform"))
    assert settings.psycopg_dsn == "postgresql://platform_app:pw@127.0.0.1:5432/platform"


def test_only_development_and_test_are_local() -> None:
    assert WorkerSettings(app_env="test").is_local
    assert not WorkerSettings(app_env="production").is_local
