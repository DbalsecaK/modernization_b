"""Application factory. Run with: uvicorn --factory nexti_api.main:create_app"""

from fastapi import FastAPI

from nexti_api.errors import install_error_handlers
from nexti_api.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="NexTI Platform API", version="0.1.0", openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    install_error_handlers(app)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
