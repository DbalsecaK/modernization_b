"""`python -m nexti_worker`: run a worker until it receives SIGINT/SIGTERM."""

import asyncio
import logging
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from nexti_core.jobs import RUNS_QUEUE
from nexti_core.object_store import ObjectStore, ObjectStoreConfig
from nexti_core.redaction import redact
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_graph import GraphStore
from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_sandbox import DEFAULT_IMAGE, DockerSandbox
from nexti_worker.queue import MAINTENANCE_QUEUE, create_app
from nexti_worker.runner import Runtime
from nexti_worker.settings import WorkerSettings, get_settings


def _redact_event(logger: Any, method: str, event: MutableMapping[str, Any]) -> Mapping[str, Any]:
    clean: dict[str, Any] = redact(event)
    return clean


def configure_logging(settings: WorkerSettings) -> None:
    renderer = structlog.dev.ConsoleRenderer() if settings.is_local else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _redact_event,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[settings.log_level.upper()]),
    )


async def run_worker(settings: WorkerSettings, *, name: str | None = None, wait: bool = True) -> None:
    if not settings.database_url.get_secret_value():
        raise SystemExit("DATABASE_URL is not set")
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    async with httpx.AsyncClient() as http:
        runtime = Runtime(
            engine=engine,
            dsn=settings.psycopg_dsn,
            sandbox=DockerSandbox(image=settings.sandbox_image or DEFAULT_IMAGE, docker=settings.sandbox_docker),
            http=http,
            objects=ObjectStore(
                ObjectStoreConfig(
                    settings.object_store_url, settings.object_store_access_key,
                    settings.object_store_secret_key.get_secret_value(), settings.object_store_bucket,
                )
            ) if settings.object_store_url else None,
            secrets=SecretStore(
                SecretsConfig(
                    settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount
                ), http,
            ) if settings.secrets_url else None,
            allow_private_hosts=settings.git_allow_private_hosts and settings.is_local,
            gateway=GatewayService(
                engine, http,
                GatewaySecrets(settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount),
                settings.openrouter_url,
                cassettes=(Path(settings.model_cassettes_dir), settings.model_cassettes_mode)
                if settings.model_cassettes_mode else None,
            ) if settings.secrets_url else None,
            sandboxes=lambda image: DockerSandbox(image=image, docker=settings.sandbox_docker),
            graph=GraphStore.connect(
                settings.graph_uri, settings.graph_user, settings.graph_password.get_secret_value()
            ) if settings.graph_uri else None,
        )  # fmt: skip
        app = create_app(settings.psycopg_dsn)
        try:
            async with app.open_async():
                await app.run_worker_async(
                    queues=[RUNS_QUEUE, MAINTENANCE_QUEUE],
                    concurrency=settings.concurrency,
                    name=name or "worker",
                    wait=wait,
                    update_heartbeat_interval=settings.heartbeat_seconds,
                    stalled_worker_timeout=settings.stalled_after_seconds,
                    additional_context={"runtime": runtime, "stalled_after_seconds": settings.stalled_after_seconds},
                )
        finally:
            await engine.dispose()


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    name = sys.argv[1] if len(sys.argv) > 1 else None
    # psycopg's async mode needs the selector loop (the default on Windows is the proactor loop).
    asyncio.run(run_worker(settings, name=name), loop_factory=asyncio.SelectorEventLoop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
