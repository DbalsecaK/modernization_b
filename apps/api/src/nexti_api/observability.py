"""Structured logs (JSON outside development) and one log line per request with a request id."""

import logging
import re
import time
import uuid
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
# Accept a caller's request id only if it is short and harmless; otherwise generate one.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = structlog.get_logger("nexti_api")


def configure_logging(*, json: bool, level: str = "INFO") -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        cache_logger_on_first_use=True,
    )


class RequestLogMiddleware:
    """Binds a request id to every log line of the request and logs method, path, status and duration.

    The query string is never logged: it can carry OAuth codes and state (/auth/callback).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (REQUEST_ID_HEADER.encode(), request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.unbind_contextvars("request_id")
