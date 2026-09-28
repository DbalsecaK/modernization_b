"""Publishes the OpenFGA outbox. Runs inside the API process as a background task (plan M0 section 13).

Rows are applied strictly in order: at the first failure the batch stops, so a later diff never overtakes an
earlier one. Writes are idempotent, so retrying a row that was half-applied is harmless.
"""

import asyncio
import contextlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.names import Tuple
from nexti_api.observability import log

MAX_ATTEMPTS = 10


def _tuples(raw: list[dict[str, Any]]) -> list[Tuple]:
    return [Tuple(t["user"], t["relation"], t["object"]) for t in raw]


class OutboxRelay:
    def __init__(self, engine: AsyncEngine, fga: OpenFga, batch_size: int = 50) -> None:
        self.engine = engine
        self.fga = fga
        self.batch_size = batch_size
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Called after a commit that enqueued something, so it is published without waiting for the poll."""
        self._wake.set()

    async def run_once(self) -> int:
        """Publish pending rows in order; returns how many were published."""
        published = 0
        async with self.engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, operation, tuples, attempts FROM authz_outbox WHERE status = 'pending' "
                        "ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED"
                    ),
                    {"n": self.batch_size},
                )
            ).all()
            for row in rows:
                tuples = _tuples(row.tuples)
                try:
                    if row.operation == "write":
                        await self.fga.write(writes=tuples)
                    else:
                        await self.fga.write(deletes=tuples)
                except Exception as exc:
                    attempts = row.attempts + 1
                    await conn.execute(
                        text("UPDATE authz_outbox SET attempts = :a, last_error = :e, status = :s WHERE id = :id"),
                        {
                            "a": attempts,
                            "e": f"{type(exc).__name__}: {exc}"[:500],
                            "s": "failed" if attempts >= MAX_ATTEMPTS else "pending",
                            "id": row.id,
                        },
                    )
                    log.warning("authz_outbox_publish_failed", outbox_id=row.id, attempts=attempts)
                    break
                await conn.execute(
                    text(
                        "UPDATE authz_outbox SET status = 'done', attempts = attempts + 1, "
                        "processed_at = now(), last_error = NULL WHERE id = :id"
                    ),
                    {"id": row.id},
                )
                published += 1
        return published

    async def run_forever(self, stop: asyncio.Event, poll_seconds: float) -> None:
        while not stop.is_set():
            try:
                while await self.run_once() == self.batch_size:
                    pass  # a full batch: there may be more right away
            except Exception as exc:  # the loop must survive database or network hiccups
                log.warning("authz_relay_error", error=type(exc).__name__, detail=str(exc)[:200])
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=poll_seconds)
