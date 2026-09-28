from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from nexti_api.db.models import Base
from nexti_api.settings import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    # Tests pass the URL of their throwaway database; otherwise it comes from the settings.
    url = config.get_main_option("sqlalchemy.url") or Settings().migration_database_url.get_secret_value()
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL is not set (run infra/docker-compose/init_env.py)")
    # Migrations run with the synchronous psycopg driver: asyncpg cannot run multi-statement SQL blocks.
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; run against a database.")

engine = create_engine(database_url())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
