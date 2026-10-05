"""The engine's RunStore on PostgreSQL: every write is a short transaction with the run's tenant set (RLS), so the
API and the activity panel see progress as it happens. Texts and payloads are redacted before they are written
(spec 18.8); writes a replayed node can repeat are idempotent (stable ids, ON CONFLICT)."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.redaction import redact, redact_text
from nexti_orchestration import QuestionSpec, RunContext, Usage
from nexti_orchestration.store import EventKind, EventStatus


def _json(value: Any) -> str:
    return json.dumps(redact(value), default=str)


def _text(value: str | None, limit: int = 2000) -> str | None:
    return None if value is None else redact_text(value)[:limit]


class DbRunStore:
    def __init__(self, engine: AsyncEngine, run: RunContext) -> None:
        self.engine = engine
        self.run = run
        self.scope = DbScope(tenant_id=run.tenant_id)
        self.ids = {"run": run.run_id, "tenant": run.tenant_id}

    async def _execute(self, sql: str, params: dict[str, Any]) -> Any:
        async with scoped_connection(self.engine, self.scope) as conn:
            return await conn.execute(text(sql), {**self.ids, **params})

    async def prepare(self) -> int:
        """The pipeline's phases as pending rows (the UI shows them from the start), and the invocations a stopped
        worker left running marked failed. Returns how many were left running."""
        for position, phase in enumerate(self.run.phases):
            await self._execute(
                "INSERT INTO phase_run (tenant_id, run_id, phase, position) VALUES (:tenant, :run, :phase, :position) "
                "ON CONFLICT DO NOTHING",
                {"phase": phase.key, "position": position},
            )
        result = await self._execute(
            "UPDATE agent_invocation SET status = 'failed', finished_at = now(), "
            'error = \'{"type": "WorkerStopped", "message": "The worker stopped during the invocation"}\' '
            "WHERE run_id = :run AND status = 'running'",
            {},
        )
        return int(result.rowcount or 0)

    async def status(self) -> str | None:
        result = await self._execute("SELECT status FROM run WHERE id = :run", {})
        status: str | None = result.scalar_one_or_none()
        return status

    async def is_cancelled(self) -> bool:
        return await self.status() == "cancelled"

    async def run_running(self, phase: str | None) -> None:
        await self._execute(
            "UPDATE run SET status = 'running', waiting_reason = NULL, "
            "current_phase = COALESCE(:phase, current_phase), started_at = COALESCE(started_at, now()) "
            "WHERE id = :run AND status NOT IN ('succeeded', 'failed', 'cancelled')",
            {"phase": phase},
        )

    async def run_waiting(self, reason: str, phase: str) -> None:
        await self._execute(
            "UPDATE run SET status = 'waiting', waiting_reason = :reason, current_phase = :phase "
            "WHERE id = :run AND status NOT IN ('succeeded', 'failed', 'cancelled')",
            {"reason": reason, "phase": phase},
        )

    async def run_finished(self, status: str, error: str | None = None) -> None:
        await self._execute(
            "UPDATE run SET status = :status, error = :error, waiting_reason = NULL, finished_at = now() "
            "WHERE id = :run AND status NOT IN ('succeeded', 'failed', 'cancelled')",
            {"status": status, "error": _text(error)},
        )

    async def phase_started(self, phase: str) -> bool:
        result = await self._execute(
            "WITH old AS (SELECT status FROM phase_run WHERE run_id = :run AND phase = :phase FOR UPDATE) "
            "UPDATE phase_run p SET status = 'running', started_at = COALESCE(p.started_at, now()), finished_at = NULL "
            "FROM old WHERE p.run_id = :run AND p.phase = :phase RETURNING old.status",
            {"phase": phase},
        )
        previous = result.scalar_one_or_none()
        return previous not in ("running", "waiting", "unavailable")

    async def phase_finished(self, phase: str, status: str, detail: str | None, iterations: int) -> None:
        await self._execute(
            "UPDATE phase_run SET status = :status, detail = :detail, iterations = :iterations, "
            "finished_at = CASE WHEN :status IN ('succeeded', 'failed') THEN now() END "
            "WHERE run_id = :run AND phase = :phase",
            {"phase": phase, "status": status, "detail": _text(detail), "iterations": iterations},
        )

    async def invocation_started(
        self, invocation_id: uuid.UUID, phase: str, agent: str, iteration: int, shard: str | None = None
    ) -> None:
        await self._execute(
            "INSERT INTO agent_invocation (id, tenant_id, run_id, phase, agent_key, shard, iteration) "
            "VALUES (:id, :tenant, :run, :phase, :agent, :shard, :iteration) "
            "ON CONFLICT (id) DO UPDATE SET status = 'running', started_at = now(), finished_at = NULL, error = NULL",
            {"id": invocation_id, "phase": phase, "agent": agent, "shard": shard, "iteration": iteration},
        )

    async def invocation_finished(
        self,
        invocation_id: uuid.UUID,
        status: str,
        summary: str | None = None,
        error: dict[str, Any] | None = None,
        usage: Usage | None = None,
    ) -> None:
        usage = usage or Usage()
        await self._execute(
            "UPDATE agent_invocation SET status = :status, summary = :summary, error = CAST(:error AS jsonb), "
            "model = :model, input_tokens = :input_tokens, output_tokens = :output_tokens, cost_usd = :cost, "
            "finished_at = now() WHERE id = :id",
            {
                "id": invocation_id,
                "status": status,
                "summary": _text(summary),
                "error": _json(error) if error is not None else None,
                "model": usage.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost": usage.cost_usd,
            },
        )

    async def gate_requested(self, gate: str, required: bool) -> bool:
        result = await self._execute(
            "INSERT INTO gate (tenant_id, run_id, gate, required) VALUES (:tenant, :run, :gate, :required) "
            "ON CONFLICT DO NOTHING RETURNING gate",
            {"gate": gate, "required": required},
        )
        return result.scalar_one_or_none() is not None

    async def reset_for_retry(self, phases: Sequence[str], gates: Sequence[str]) -> None:
        await self._execute(
            "UPDATE phase_run SET status = 'pending', detail = NULL, iterations = 0, started_at = NULL, "
            "finished_at = NULL WHERE run_id = :run AND phase = ANY(:phases)",
            {"phases": list(phases)},
        )
        # The app role may not delete: the gate goes back to pending (the decision stays in the audit log).
        await self._execute(
            "UPDATE gate SET status = 'pending', decided_by = NULL, decided_at = NULL, comment = NULL "
            "WHERE run_id = :run AND gate = ANY(:gates)",
            {"gates": list(gates)},
        )

    async def question_asked(self, question_id: uuid.UUID, phase: str, question: QuestionSpec) -> bool:
        result = await self._execute(
            "INSERT INTO question (id, tenant_id, project_id, run_id, phase, agent_key, question_text, context, "
            "evidence, reason, impact, recommended, alternatives, affects) VALUES (:id, :tenant, :project, :run, "
            ":phase, :agent, :text, :context, CAST(:evidence AS jsonb), :reason, :impact, "
            "CAST(:recommended AS jsonb), CAST(:alternatives AS jsonb), CAST(:affects AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            {
                "id": question_id,
                "project": self.run.project_id,
                "phase": phase,
                "agent": question.agent,
                "text": _text(question.text),
                "context": _text(question.context) or "",
                "evidence": _json([asdict(e) for e in question.evidence]),
                "reason": question.reason,
                "impact": question.impact,
                "recommended": _json({**asdict(question.recommended), "confidence": question.confidence}),
                "alternatives": _json([asdict(a) for a in question.alternatives]),
                "affects": _json(list(question.affects)),
            },
        )
        return result.scalar_one_or_none() is not None

    async def event(
        self,
        kind: EventKind,
        status: EventStatus,
        message: str,
        *,
        phase: str | None = None,
        agent: str | None = None,
        invocation_id: uuid.UUID | None = None,
        usage: Usage | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        usage = usage or Usage()
        await self._execute(
            "INSERT INTO activity_event (tenant_id, project_id, run_id, invocation_id, agent_key, phase, kind, status, "
            "message, model, tokens, cost_usd, payload) VALUES (:tenant, :project, :run, :invocation, :agent, :phase, "
            ":kind, :status, :message, :model, :tokens, :cost, CAST(:payload AS jsonb))",
            {
                "project": self.run.project_id,
                "invocation": invocation_id,
                "agent": agent,
                "phase": phase,
                "kind": kind,
                "status": status,
                "message": _text(message) or "",
                "model": usage.model,
                "tokens": usage.input_tokens + usage.output_tokens,
                "cost": usage.cost_usd,
                "payload": _json(payload or {}),
            },
        )
