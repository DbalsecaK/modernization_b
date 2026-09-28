"""Helpers shared by the AI configuration routers."""

from typing import Annotated

from fastapi import Depends, Request

from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.errors import ProblemError
from nexti_model_gateway.service import GatewayService

ConfigureModels = Annotated[Authorized, Depends(require_tenant("models.configure"))]


def gateway_service(request: Request) -> GatewayService:
    service: GatewayService | None = getattr(request.app.state, "gateway_service", None)
    if service is None:
        raise ProblemError(503, "gateway_unavailable", "The model gateway is not configured.")
    return service
