"""Demo data for a local run (plan P1): complete projects reproduced from the acceptance recordings (ADR-0012), in
the development database, for the fictitious tenant Andes Bank: Luis Andrade launches each run and María Torres,
in charge of the projects, approves its gates (segregation of duties).

The pipeline runs for real (the worker in this process, the Docker sandboxes, gates approved through the API as in
the acceptances), but the models' answers come from the recordings: the provider credential is a placeholder, a
request without a recording fails instead of reaching the network, and nothing is spent. The usage ledger keeps the
cost the recording had, so the Costs tab shows what the run cost when it was recorded.

Development only (APP_ENV=development), and with the worker stopped: the runs go on in this process, and a worker
would resume them without the recordings. Idempotent: a demo project that exists is left alone; --reset deletes the
demo projects first.

    uv run --no-sync python tools/demo/seed_demo.py [--reset] [--only m4|m6|m6b]
"""

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api/tests"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from integration import test_acceptance_m4 as m4  # noqa: E402
from integration import test_acceptance_m6 as m6  # noqa: E402
from integration import test_acceptance_m6b as m6b  # noqa: E402
from integration import test_acceptance_m6c as m6c  # noqa: E402
from integration.run_support import NO_FRONTEND, TARGET, FakeSandbox, make_config, make_run, seed_screens  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

from nexti_api.authz import fga as fga_module  # noqa: E402
from nexti_api.authz.reconcile import reconcile  # noqa: E402
from nexti_api.main import create_app  # noqa: E402
from nexti_api.settings import Settings  # noqa: E402
from nexti_core.object_store import ObjectStore, ObjectStoreConfig  # noqa: E402
from nexti_core.secrets import SecretsConfig, SecretStore  # noqa: E402
from nexti_graph import GraphStore  # noqa: E402
from nexti_model_gateway.service import GatewayService  # noqa: E402
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets  # noqa: E402
from nexti_sandbox import DockerSandbox  # noqa: E402
from nexti_worker.runner import Runtime, execute_run  # noqa: E402

TENANT_SLUG = "andes-bank"
OWNER_EMAIL = "mtorres@andesbank.example"
LAUNCHER_EMAIL = "landrade@andesbank.example"
DEMOS = {
    "m4": ("Demo · Pagos Sybase → Spring Boot", ["sybase-sp"]),
    "m6": ("Demo · Pagos COBOL/CICS → Spring Boot", ["cobol-cics", "bms"]),
    "m6b": ("Demo · Pagos frontend React y Angular", ["bms"]),
    "m6c": ("Demo · Pagos Sybase → .NET 10", ["sybase-sp"]),
}
DESCRIPTION = "Demo project replayed from the {key} acceptance recordings: a full run with no model cost."
MAX_STEPS = 30
WORKER_ALIVE_SECONDS = 30


class Demo:
    """What one demo needs: the engines, the stores, the tenant, its owner and an API signed in as the owner."""

    def __init__(self, settings: Settings, owner: AsyncEngine, app: AsyncEngine, api: TestClient) -> None:
        self.settings = settings
        self.owner = owner
        self.app = app
        self.api = api
        self.store = ObjectStore(ObjectStoreConfig(settings.object_store_url, settings.object_store_access_key,
                                                   settings.object_store_secret_key.get_secret_value(),
                                                   settings.object_store_bucket))  # fmt: skip
        self.tenant: uuid.UUID = uuid.UUID(int=0)
        self.user: uuid.UUID = uuid.UUID(int=0)
        self.launcher: uuid.UUID = uuid.UUID(int=0)
        self.headers: dict[str, str] = {}

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.owner.begin() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]

    async def locate(self) -> None:
        (found,) = await self.rows(
            "SELECT t.id AS tenant, o.id AS owner, l.id AS launcher FROM tenant t, app_user o, app_user l "
            "WHERE t.slug = :s AND o.email = :o AND l.email = :l",
            s=TENANT_SLUG, o=OWNER_EMAIL, l=LAUNCHER_EMAIL,
        )  # fmt: skip
        self.tenant, self.user, self.launcher = found["tenant"], found["owner"], found["launcher"]

    async def project(self, name: str) -> uuid.UUID:
        (row,) = await self.rows(
            "INSERT INTO project (tenant_id, name, created_by) VALUES (:t, :n, :u) RETURNING id",
            t=self.tenant, n=name, u=self.user,
        )  # fmt: skip
        # The owner signs off at C4 (signoff.sign comes with the project owner role); the launcher is an analyst
        # (runs the pipeline and sees code, but neither downloads it nor sees usage).
        for user, role in ((self.user, "projectOwner"), (self.launcher, "analyst")):
            await self.rows(
                "INSERT INTO role_assignment (tenant_id, user_id, role_id, scope, project_id) SELECT :t, :u, id, "
                "'project', :p FROM role WHERE tenant_id = :t AND key = :r RETURNING id",
                t=self.tenant, u=user, p=row["id"], r=role,
            )  # fmt: skip
        return uuid.UUID(str(row["id"]))

    async def sync_authz(self) -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            await reconcile(self.app, await fga_module.connect(http, self.settings))
        self.headers = sign_in(self.api, self.user)

    def gateway(self, http: httpx.AsyncClient, recordings: Path, shared: tuple[Path, ...] = ()) -> GatewayService:
        secrets = GatewaySecrets(self.settings.secrets_url, self.settings.secrets_token.get_secret_value())
        return GatewayService(self.app, http, secrets, cassettes=(recordings, "replay"), shared_cassettes=shared)

    async def unqueue(self, run_id: uuid.UUID) -> None:
        """Drops the jobs the API queued to resume the run: this process runs it, no worker must pick it up."""
        await self.rows(
            "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args->>'run_id' = :r RETURNING id", r=str(run_id)
        )

    async def drive(self, project_id: uuid.UUID, run_id: uuid.UUID, runtime: Runtime) -> list[str]:
        """Runs the pipeline to its end, approving each gate and taking each recommendation through the API."""
        base = f"/api/v1/projects/{project_id}"
        decided: list[str] = []
        for _ in range(MAX_STEPS):
            await self.unqueue(run_id)
            await execute_run(runtime, run_id, self.tenant)
            (run,) = await self.rows("SELECT status, waiting_reason FROM run WHERE id = :r", r=run_id)
            if run["status"] != "waiting":
                break
            if run["waiting_reason"] == "gate":
                (gate,) = await self.rows(
                    "SELECT gate FROM gate WHERE run_id = :r AND status = 'pending' ORDER BY gate LIMIT 1", r=run_id
                )
                answer = self.api.post(f"{base}/runs/{run_id}/gates/{gate['gate']}:approve", json={},
                                       headers=self.headers)  # fmt: skip
                answer.raise_for_status()
                decided.append(gate["gate"])
            elif run["waiting_reason"] == "question":
                for question in await self.rows(
                    "SELECT id, recommended->>'key' AS option FROM question WHERE run_id = :r AND status = 'open'",
                    r=run_id,
                ):
                    answer = self.api.post(f"{base}/questions/{question['id']}:answer",
                                           json={"option": question["option"]}, headers=self.headers)  # fmt: skip
                    answer.raise_for_status()
                decided.append("questions")
            else:
                break  # a phase this version does not have yet (hardening, delivery)
        await self.unqueue(run_id)
        return decided


def sign_in(api: TestClient, user: uuid.UUID) -> dict[str, str]:
    api.cookies.clear()
    api.post("/auth/dev/login", json={"userId": str(user)}).raise_for_status()
    return {"X-CSRF-Token": api.get("/api/v1/me").json()["csrfToken"]}


async def pipeline(demo: Demo, name: str, recordings: Path, team: dict[str, str], files: dict[str, bytes],
                   legacy: Callable[[], Any] | None, target: dict[str, str] | None = None,
                   shared: tuple[Path, ...] = ()) -> uuid.UUID:  # fmt: skip
    """A whole modernization run (M4, M6, M6c) of the fictitious application, replayed."""
    project_id = await demo.project(name)
    version = await make_config(demo.owner, demo.tenant, project_id, team=team, target=target or NO_FRONTEND)
    await m4.upload_source(demo.owner, demo.store, demo.tenant, project_id, files)
    await demo.sync_authz()
    run_id = await make_run(demo.owner, demo.tenant, project_id, version, kind="pipeline",
                            started_by=demo.launcher)  # fmt: skip
    async with httpx.AsyncClient(timeout=60) as http:
        gateway = demo.gateway(http, recordings / "models", shared)
        path = await m4.model_for(demo.owner, gateway, demo.tenant, project_id, live=False)
        secrets = SecretsConfig(demo.settings.secrets_url, demo.settings.secrets_token.get_secret_value())
        # The knowledge graph of the Inventory tab, as the worker writes it.
        graph = (
            GraphStore.connect(
                demo.settings.graph_uri, demo.settings.graph_user, demo.settings.graph_password.get_secret_value()
            )
            if demo.settings.graph_uri
            else None
        )
        runtime = Runtime(
            engine=demo.app,
            dsn=demo.settings.database_url.get_secret_value().replace("postgresql+asyncpg://", "postgresql://", 1),
            sandbox=FakeSandbox(), http=http, objects=demo.store, secrets=SecretStore(secrets, http),
            gateway=gateway, sandboxes=lambda image: DockerSandbox(image=image), legacy=legacy,
            graph=graph,
        )  # fmt: skip
        try:
            decided = await demo.drive(project_id, run_id, runtime)
        finally:
            await gateway.delete_credential(path)
            if graph is not None:
                await graph.close()
    print(f"  {name}: decisions {decided}")
    return project_id


async def demo_m4(demo: Demo) -> uuid.UUID:
    recorded = m4.RecordedRunner(m4.RECORDINGS / "golden", "replay", None)
    sources = {"sp/sp_pago_orden.sp": (m4.FIXTURES / "sp_pago_orden.sp").read_bytes()}
    return await pipeline(demo, DEMOS["m4"][0], m4.RECORDINGS, m4.FULL_TEAM, sources, lambda: recorded)


async def demo_m6c(demo: Demo) -> uuid.UUID:
    """The M4 run with the backend on .NET 10 + SQL Server: M4's answers up to the design, M6c's from generation."""
    recorded = m4.RecordedRunner(m4.RECORDINGS / "golden", "replay", None)
    sources = {"sp/sp_pago_orden.sp": (m4.FIXTURES / "sp_pago_orden.sp").read_bytes()}
    return await pipeline(demo, DEMOS["m6c"][0], m6c.RECORDINGS, m4.FULL_TEAM, sources, lambda: recorded,
                          target=m6c.TARGET_DOTNET, shared=(m4.RECORDINGS / "models",))  # fmt: skip


async def demo_m6(demo: Demo) -> uuid.UUID:
    return await pipeline(demo, DEMOS["m6"][0], m6.RECORDINGS, m6.TEAM, m6.sources(), None)


async def demo_m6b(demo: Demo) -> uuid.UUID:
    """The React and Angular frontends of the approved design and the M5 prototypes (M6b), replayed."""
    from nexti_orchestration import PhaseSpec
    from nexti_orchestration.context import PhaseContext
    from nexti_orchestration.frontend import frontend_checks, generate
    from nexti_orchestration.memory import MemoryStore
    from nexti_orchestration.verification import frontend_proof_pack
    from nexti_ui import PrototypeBuild
    from nexti_verification import verdict as checks
    from nexti_worker.loading import load_run
    from nexti_worker.project import WorkerProjectPort

    project_id = await demo.project(DEMOS["m6b"][0])
    await seed_screens(demo.owner, demo.store, demo.tenant, project_id)
    await demo.sync_authz()
    async with httpx.AsyncClient(timeout=60) as http:
        gateway = demo.gateway(http, m6b.RECORDINGS / "models")
        path = await m4.model_for(demo.owner, gateway, demo.tenant, project_id, live=False)
        try:
            for flavour in m6b.FLAVOURS:
                version = await make_config(demo.owner, demo.tenant, project_id, team=m6b.TEAM,
                                            target={**TARGET, "frontend": flavour})  # fmt: skip
                run_id = await make_run(demo.owner, demo.tenant, project_id, version, kind="pipeline",
                                        started_by=demo.launcher)  # fmt: skip
                run = (await load_run(demo.app, run_id, demo.tenant)).context
                port = WorkerProjectPort(demo.app, run, gateway, demo.store, None,
                                         lambda image: DockerSandbox(image=image))  # fmt: skip
                if flavour == m6b.FLAVOURS[0]:
                    for screen, source in sorted(m6b.prototypes_of_m5().items()):
                        await port.save_prototype(screen, source, PrototypeBuild(True), "generated", "M5 recording")
                ctx = PhaseContext(run, MemoryStore(), PhaseSpec("generation", None, True), None)
                files, final, summary = await generate(ctx, port, m6b.DESIGN, flavour)
                if final is None:
                    raise RuntimeError(f"the {flavour} frontend did not build: {summary}")
                await port.save_artifacts(files, {}, {})
                verdict = checks.compute(f"frontend-{flavour}", frontend_checks(final), [],
                                         required=checks.FRONTEND_CHECKS)  # fmt: skip
                await port.save_verdict(verdict, frontend_proof_pack(verdict, final))
                await demo.rows("UPDATE run SET status = 'succeeded', finished_at = now() WHERE id = :r RETURNING id",
                                r=run_id)  # fmt: skip
                print(f"  {DEMOS['m6b'][0]}: {flavour} {verdict.verdict}")
        finally:
            await gateway.delete_credential(path)
    return project_id


BUILDERS: dict[str, Callable[[Demo], Awaitable[uuid.UUID]]] = {
    "m4": demo_m4, "m6": demo_m6, "m6b": demo_m6b, "m6c": demo_m6c,
}  # fmt: skip


async def main(reset: bool, only: list[str]) -> int:
    settings = Settings()
    if not settings.is_local:
        print(f"Demo data only goes into development (APP_ENV={settings.app_env}).", file=sys.stderr)
        return 2
    owner = create_async_engine(settings.migration_database_url.get_secret_value())
    app = create_async_engine(settings.database_url.get_secret_value())
    try:
        with TestClient(create_app(settings.model_copy(update={"dev_auth_enabled": True})),
                        base_url="https://testserver") as api:  # fmt: skip
            demo = Demo(settings, owner, app, api)
            alive = await demo.rows(
                "SELECT id FROM procrastinate_workers WHERE last_heartbeat > now() - make_interval(secs => :s)",
                s=WORKER_ALIVE_SECONDS,
            )
            if alive:
                print(
                    "A worker is running: stop it first (scripts/stop-local.ps1). The demo runs the pipeline in "
                    "this process, and a worker would resume the same runs without the recordings.",
                    file=sys.stderr,
                )
                return 2
            await demo.locate()
            for key in only:
                name, sources = DEMOS[key]
                existing = await demo.rows("SELECT id FROM project WHERE tenant_id = :t AND name = :n",
                                           t=demo.tenant, n=name)  # fmt: skip
                if existing and not reset:
                    print(f"  {name}: already there (use --reset to rebuild it)")
                    continue
                for row in existing:
                    await demo.rows("DELETE FROM role_assignment WHERE project_id = :p RETURNING id", p=row["id"])
                    await demo.rows("DELETE FROM project WHERE id = :p RETURNING id", p=row["id"])
                print(f"Reproducing {name} from the {key.upper()} recordings…")
                project_id = await BUILDERS[key](demo)
                # Cosmetic, after the run: the source technologies the wizard would have recorded.
                await demo.rows("UPDATE project_config SET sources = CAST(:s AS text[]) WHERE project_id = :p "
                                "RETURNING version", s=sources, p=project_id)  # fmt: skip
                await demo.rows("UPDATE project SET description = :d WHERE id = :p RETURNING id",
                                d=DESCRIPTION.format(key=key.upper()), p=project_id)  # fmt: skip
                verdicts = await demo.rows("SELECT module, verdict FROM verdict WHERE project_id = :p ORDER BY module",
                                           p=project_id)  # fmt: skip
                if not verdicts:
                    print(f"  {name}: the run ended without a verdict", file=sys.stderr)
                    return 1
                print(f"  {name}: " + ", ".join(f"{v['module']} {v['verdict']}" for v in verdicts))
            await demo.sync_authz()
    finally:
        await owner.dispose()
        await app.dispose()
    print("Demo data ready. Sign in as María Torres at http://localhost:5173.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reset", action="store_true", help="delete the demo projects and reproduce them again")
    parser.add_argument("--only", choices=sorted(BUILDERS), action="append", help="one demo (repeatable)")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main(args.reset, args.only or list(BUILDERS))))
