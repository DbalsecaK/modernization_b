"""Reconciliation: make OpenFGA equal to what PostgreSQL implies, and audit every correction (ADR-0001)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.audit import AuditEvent, record
from nexti_api.authz.fga import OpenFga
from nexti_api.authz.names import Tuple
from nexti_api.authz.tuples import expected_platform_tuples, expected_tuples
from nexti_core.db.models import Tenant
from nexti_core.db.session import DbScope, scoped_connection

SAMPLE = 20


@dataclass(frozen=True)
class ReconcileReport:
    expected: int
    missing: frozenset[Tuple]
    extra: frozenset[Tuple]

    @property
    def in_sync(self) -> bool:
        return not self.missing and not self.extra


async def compute_expected(engine: AsyncEngine) -> set[Tuple]:
    async with scoped_connection(engine, DbScope(platform_scope=True)) as conn:
        expected = await expected_platform_tuples(conn)
        for tenant_id in (await conn.execute(select(Tenant.id))).scalars():
            expected |= await expected_tuples(conn, tenant_id)
    return expected


async def reconcile(engine: AsyncEngine, fga: OpenFga, *, apply: bool = True) -> ReconcileReport:
    expected = await compute_expected(engine)
    actual = await fga.read_all()
    report = ReconcileReport(len(expected), frozenset(expected - actual), frozenset(actual - expected))
    if apply and not report.in_sync:
        await fga.write(writes=report.missing, deletes=report.extra)
        async with scoped_connection(engine, DbScope(platform_scope=True)) as conn:
            await record(
                conn,
                AuditEvent(
                    action="authz.reconcile",
                    outcome="success",
                    actor_kind="system",
                    actor_label="authz-reconciler",
                    details={
                        "written": len(report.missing),
                        "deleted": len(report.extra),
                        "written_sample": [t.as_key() for t in sorted(report.missing)[:SAMPLE]],
                        "deleted_sample": [t.as_key() for t in sorted(report.extra)[:SAMPLE]],
                    },
                ),
            )
    return report
