"""The instances of the platform (spec 18.4, ADR-0024): each API and worker process registers its name, component,
version and deployment profile, and beats every minute, so the operators see what runs where."""

import asyncio
import contextlib
import os
import socket
from importlib.metadata import PackageNotFoundError, version

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()
BEAT_SECONDS = 60


def instance_name() -> str:
    """The pod or container name (HOSTNAME), else the machine's name."""
    return (os.environ.get("HOSTNAME") or socket.gethostname())[:200]


def deployed_version(package: str) -> str:
    """The image's version (NEXTI_VERSION, set when the image is built), else the installed package's."""
    if found := os.environ.get("NEXTI_VERSION"):
        return found[:100]
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def profile() -> str:
    """The deployment profile (NEXTI_PROFILE: shared-saas, customer-cloud...), development outside a deployment."""
    return (os.environ.get("NEXTI_PROFILE") or "development")[:100]


async def beat(engine: AsyncEngine, component: str, package: str, *, started: bool = False) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT platform_heartbeat(:n, :c, :v, :p, :s)"),
                           {"n": instance_name(), "c": component, "v": deployed_version(package), "p": profile(),
                            "s": started})  # fmt: skip


async def beat_forever(engine: AsyncEngine, component: str, package: str, stop: asyncio.Event) -> None:
    """Registers the instance and beats until `stop`; a failed beat is logged and retried at the next one."""
    started = True
    while not stop.is_set():
        try:
            await beat(engine, component, package, started=started)
            started = False
        except Exception as exc:
            log.warning("instance_heartbeat_failed", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=BEAT_SECONDS)
