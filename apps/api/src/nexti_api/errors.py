"""Uniform error format: RFC 9457 Problem Details with a stable code and an English message (spec 19.5)."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    """An error the API reports to the client. `code` is stable and safe to branch on."""

    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra


def problem_response(status: int, code: str, detail: str, instance: str, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://nexti.dev/problems/{code}",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": instance,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _code_for_status(status: int) -> str:
    return HTTPStatus(status).phrase.lower().replace(" ", "_").replace("-", "_")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(exc.status, exc.code, exc.detail, request.url.path, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return problem_response(exc.status_code, _code_for_status(exc.status_code), detail, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_response(422, "validation_failed", "The request is not valid.", request.url.path, errors=errors)
