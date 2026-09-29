"""Evaluates the rules a run extracted against a reference kit (spec 21.4, ADR-0011), on demand, on the machine that
has the kit:

    uv run --no-sync python -m nexti_worker.evaluate --tenant <uuid> --run <uuid> --kit <folder>

The kit folder defaults to $NEXTI_REFERENCE_DIR/<name> with --name. Only the metrics, the name and the hash of the
reference are stored; the output prints counts and rule ids, never the content of the kit."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from nexti_model_gateway.service import GatewayService
from nexti_model_gateway.service import SecretsConfig as GatewaySecrets
from nexti_verification.evaluation import Evaluation, evaluate
from nexti_verification.kit import kits_root, load_kit
from nexti_worker.loading import load_run
from nexti_worker.project import WorkerProjectPort
from nexti_worker.settings import get_settings


async def run_evaluation(tenant: uuid.UUID, run_id: uuid.UUID, folder: Path) -> Evaluation:
    settings = get_settings()
    kit = load_kit(folder)
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        loaded = await load_run(engine, run_id, tenant)
        async with httpx.AsyncClient() as http:
            gateway = GatewayService(engine, http, GatewaySecrets(settings.secrets_url, "", settings.secrets_mount))
            port = WorkerProjectPort(engine, loaded.context, gateway, None, None)
            result = evaluate(kit.reference, await port.load_rules())
            await port.save_evaluation(result)
    finally:
        await engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", required=True, type=uuid.UUID)
    parser.add_argument("--run", required=True, type=uuid.UUID)
    parser.add_argument("--kit", type=Path, help="the kit folder")
    parser.add_argument("--name", help="the kit's folder under $NEXTI_REFERENCE_DIR")
    args = parser.parse_args()
    root = kits_root()
    folder = args.kit or (root / args.name if root and args.name else None)
    if folder is None:
        raise SystemExit("give --kit, or --name with NEXTI_REFERENCE_DIR set")
    result = asyncio.run(run_evaluation(args.tenant, args.run, folder))
    summary = {key: value for key, value in result.metrics().items() if key != "matched"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
