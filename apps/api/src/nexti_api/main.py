"""Application factory. Run with: uvicorn --factory nexti_api.main:create_app"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexti_api import health, me, usage
from nexti_api.admin import assignments, audit_log, invitations, roles, tenants, users
from nexti_api.ai import assignments as ai_assignments
from nexti_api.ai import catalog as ai_catalog
from nexti_api.ai import connections as ai_connections
from nexti_api.ai import profiles as ai_profiles
from nexti_api.audit.keycloak_events import pull_keycloak_events
from nexti_api.auth import dev_auth
from nexti_api.auth import routes as auth_routes
from nexti_api.auth.oidc import OidcClient
from nexti_api.auth.session import SessionStore
from nexti_api.authz import fga as fga_module
from nexti_api.authz.reconcile import reconcile
from nexti_api.authz.relay import OutboxRelay
from nexti_api.errors import install_error_handlers
from nexti_api.graph import router as graph_router
from nexti_api.keycloak_admin import KeycloakAdmin
from nexti_api.observability import RequestLogMiddleware, configure_logging, log
from nexti_api.projects import catalog_api, inputs, repository
from nexti_api.projects import router as projects_router
from nexti_api.projects import services as input_services
from nexti_api.resources import Resources
from nexti_api.runs import activity as runs_activity
from nexti_api.runs import questions as runs_questions
from nexti_api.runs import router as runs_router
from nexti_api.runs import tasks as runs_tasks
from nexti_api.settings import Settings, get_settings
from nexti_api.spec import code as spec_code
from nexti_api.spec import plan as spec_plan
from nexti_api.spec import screens as spec_screens
from nexti_api.spec import stories as spec_stories
from nexti_api.spec import validation as spec_validation
from nexti_model_gateway.service import GatewayService, SecretsConfig


async def _connect_fga(resources: Resources, settings: Settings) -> fga_module.OpenFga | None:
    """OpenFGA unavailable at startup does not stop the API: protected endpoints answer 503 until restart."""
    if not settings.openfga_url:
        return None
    try:
        return await fga_module.connect(resources.http, settings)
    except Exception as exc:
        log.error("openfga_unavailable", error=type(exc).__name__, detail=str(exc)[:200])
        return None


async def _reconcile_periodically(
    resources: Resources, fga: fga_module.OpenFga, settings: Settings, stop: asyncio.Event
) -> None:
    assert resources.engine is not None  # noqa: S101 (checked by the caller)
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.reconcile_interval_seconds)
        if stop.is_set():
            return
        try:
            report = await reconcile(resources.engine, fga)
            if not report.in_sync:
                log.warning("authz_reconciled", written=len(report.missing), deleted=len(report.extra))
        except Exception as exc:
            log.warning("authz_reconcile_failed", error=type(exc).__name__, detail=str(exc)[:200])


async def _copy_keycloak_events(
    resources: Resources, admin: KeycloakAdmin, settings: Settings, stop: asyncio.Event
) -> None:
    assert resources.engine is not None  # noqa: S101 (checked by the caller)
    while not stop.is_set():
        try:
            await pull_keycloak_events(resources.engine, admin)
        except Exception as exc:
            log.warning("keycloak_events_failed", error=type(exc).__name__, detail=str(exc)[:200])
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.keycloak_events_interval_seconds)


def create_app(settings: Settings | None = None, health_checks: dict[str, health.Check] | None = None) -> FastAPI:
    """Build the API. `health_checks` replaces the real dependency checks (tests only)."""
    settings = settings or get_settings()
    # Before anything else: dev-auth outside development/test must not start (ADR-0004).
    dev_auth.ensure_allowed(settings)
    configure_logging(json=not settings.is_local, level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = Resources.open(settings)
        app.state.resources = resources
        app.state.health_checks = health_checks or health.default_checks(resources, settings)
        app.state.oidc = OidcClient(settings, resources.http)
        app.state.keycloak_admin = (
            KeycloakAdmin(settings, resources.http)
            if settings.keycloak_admin_client_secret.get_secret_value()
            else None
        )
        # Without Redis or a session secret there are no sessions: session routes answer 503.
        configured = resources.redis is not None and settings.session_secret.get_secret_value()
        app.state.sessions = SessionStore(resources.redis, settings) if configured and resources.redis else None
        app.state.gateway_service = (
            GatewayService(
                resources.engine,
                resources.http,
                SecretsConfig(settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount),
                settings.openrouter_url,
            )
            if resources.engine is not None and settings.secrets_url
            else None
        )
        app.state.settings = settings
        app.state.graph = resources.graph
        app.state.inputs = input_services.build(settings)
        app.state.fga = await _connect_fga(resources, settings)
        app.state.relay = None
        stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []
        if app.state.fga is not None and resources.relay_engine is not None:
            app.state.relay = OutboxRelay(resources.relay_engine, app.state.fga)
            tasks.append(asyncio.create_task(app.state.relay.run_forever(stop, settings.relay_poll_seconds)))
        events_enabled = settings.keycloak_events_interval_seconds > 0
        if app.state.keycloak_admin is not None and resources.engine is not None and events_enabled:
            admin = app.state.keycloak_admin
            tasks.append(asyncio.create_task(_copy_keycloak_events(resources, admin, settings, stop)))
        if app.state.fga is not None and resources.engine is not None and settings.reconcile_interval_seconds > 0:
            tasks.append(asyncio.create_task(_reconcile_periodically(resources, app.state.fga, settings, stop)))
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
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
    app.include_router(auth_routes.router)
    app.include_router(me.router)
    for admin_router in (
        tenants.router,
        users.router,
        invitations.router,
        roles.router,
        assignments.router,
        projects_router.router,
        catalog_api.router,
        inputs.router,
        repository.router,
        runs_router.router,
        runs_questions.router,
        runs_tasks.router,
        runs_activity.router,
        spec_stories.router,
        spec_stories.tools,
        spec_plan.router,
        spec_validation.router,
        spec_code.router,
        spec_screens.router,
        graph_router.router,
    ):
        app.include_router(admin_router)
    app.include_router(audit_log.router)
    for ai_router in (
        ai_connections.router,
        ai_catalog.router,
        ai_profiles.router,
        ai_assignments.router,
        usage.router,
    ):
        app.include_router(ai_router)
    if settings.dev_auth_enabled:
        app.include_router(dev_auth.router)
    return app
