"""Application factory. Run with: uvicorn --factory nexti_api.main:create_app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexti_api import health
from nexti_api.errors import install_error_handlers
from nexti_api.observability import RequestLogMiddleware, configure_logging
from nexti_api.resources import Resources
from nexti_api.settings import Settings, get_settings


def create_app(settings: Settings | None = None, health_checks: dict[str, health.Check] | None = None) -> FastAPI:
    """Build the API. `health_checks` replaces the real dependency checks (tests only)."""
    settings = settings or get_settings()
    configure_logging(json=not settings.is_local, level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = Resources.open(settings)
        app.state.resources = resources
        app.state.health_checks = health_checks or health.default_checks(resources, settings)
        try:
            yield
        finally:
            await resources.close()

    # Interactive docs only where there is no real data; the OpenAPI document is always available.
    app = FastAPI(
        title="NexTI Platform API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs" if settings.is_local else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestLogMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    return app
