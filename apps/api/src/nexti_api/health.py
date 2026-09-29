"""Liveness and readiness. Readiness checks every dependency the API needs to serve requests."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from nexti_api.observability import log
from nexti_api.resources import Resources
from nexti_api.settings import Settings

# A check returns normally when the dependency is usable and raises otherwise.
Check = Callable[[], Awaitable[None]]
CHECK_TIMEOUT_SECONDS = 3.0

router = APIRouter(prefix="/api/v1/health", tags=["ops"])


class NotConfiguredError(RuntimeError):
    pass


class CheckResult(BaseModel):
    status: Literal["ok", "fail"]
    latency_ms: float


class Readiness(BaseModel):
    status: Literal["ok", "fail"]
    checks: dict[str, CheckResult]


def default_checks(resources: Resources, settings: Settings) -> dict[str, Check]:
    async def postgres() -> None:
        if resources.engine is None:
            raise NotConfiguredError("DATABASE_URL is not set")
        async with resources.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis() -> None:
        if resources.redis is None:
            raise NotConfiguredError("REDIS_URL is not set")
        await resources.redis.ping()

    async def keycloak() -> None:
        if not settings.keycloak_url:
            raise NotConfiguredError("KEYCLOAK_URL is not set")
        res = await resources.http.get(f"{settings.keycloak_issuer}/.well-known/openid-configuration")
        res.raise_for_status()

    async def openfga() -> None:
        if not settings.openfga_url:
            raise NotConfiguredError("OPENFGA_URL is not set")
        res = await resources.http.get(f"{settings.openfga_url.rstrip('/')}/healthz")
        res.raise_for_status()

    async def secrets() -> None:
        if not settings.secrets_url:
            raise NotConfiguredError("SECRETS_URL is not set")
        res = await resources.http.get(f"{settings.secrets_url.rstrip('/')}/v1/sys/health")
        res.raise_for_status()

    async def storage() -> None:
        if not settings.object_store_url:
            raise NotConfiguredError("OBJECT_STORE_URL is not set")
        from nexti_api.projects.services import build

        found = build(settings).store
        if found is None or not await found.healthy():
            raise ConnectionError("the object store bucket is not reachable")

    async def malware_scanner() -> None:
        if not settings.malware_scanner_host:
            raise NotConfiguredError("MALWARE_SCANNER_HOST is not set")
        from nexti_ingest import ClamdScanner

        if not await ClamdScanner(settings.malware_scanner_host, settings.malware_scanner_port, 10).ping():
            raise ConnectionError("clamd did not answer PONG")

    return {
        "postgres": postgres, "redis": redis, "keycloak": keycloak, "openfga": openfga, "secrets": secrets,
        "storage": storage, "malware_scanner": malware_scanner,
    }  # fmt: skip


async def _run(name: str, check: Check) -> CheckResult:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check(), CHECK_TIMEOUT_SECONDS)
        status: Literal["ok", "fail"] = "ok"
    except Exception as exc:  # any failure makes the dependency not ready
        # Details go to the log only; the public response does not reveal internals.
        log.warning("readiness_check_failed", check=name, error=type(exc).__name__, detail=str(exc)[:200])
        status = "fail"
    return CheckResult(status=status, latency_ms=round((time.perf_counter() - started) * 1000, 1))


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is up. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/ready", response_model=Readiness, responses={503: {"model": Readiness}})
async def ready(request: Request, response: Response) -> Readiness:
    """Every dependency answers. 503 if any of them fails."""
    checks: dict[str, Check] = request.app.state.health_checks
    results = await asyncio.gather(*(_run(name, check) for name, check in checks.items()))
    by_name = dict(zip(checks, results, strict=True))
    overall: Literal["ok", "fail"] = "ok" if all(r.status == "ok" for r in results) else "fail"
    if overall == "fail":
        response.status_code = 503
    return Readiness(status=overall, checks=by_name)
