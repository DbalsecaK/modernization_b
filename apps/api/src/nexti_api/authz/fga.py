"""Small OpenFGA HTTP client: check, batch check, list objects, idempotent writes, read all, bootstrap."""

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from nexti_api.authz.names import Tuple
from nexti_api.settings import API_DIR, Settings

MODEL_FILE = API_DIR.parents[1] / "infra" / "openfga" / "model.json"
MAX_TUPLES_PER_WRITE = 100  # OpenFGA default limit per Write request
# Relay and reconciler writing the same tuple at once: OpenFGA aborts one with 409; the retry is a no-op.
WRITE_CONFLICT_RETRIES = 3


class OpenFgaError(RuntimeError):
    pass


def load_model(path: Path = MODEL_FILE) -> dict[str, Any]:
    model: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return model


def _comparable(model: dict[str, Any]) -> str:
    keys = ("schema_version", "type_definitions", "conditions")
    return json.dumps({k: model.get(k) or None for k in keys}, sort_keys=True)


class OpenFga:
    def __init__(self, http: httpx.AsyncClient, url: str, api_key: str, store_id: str, model_id: str) -> None:
        self.http = http
        self.base = f"{url.rstrip('/')}/stores/{store_id}"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.store_id = store_id
        self.model_id = model_id

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        res = await self.http.post(f"{self.base}/{path}", json=body, headers=self.headers)
        for attempt in range(WRITE_CONFLICT_RETRIES):
            if not (path == "write" and res.status_code == 409):
                break
            await asyncio.sleep(0.05 * (attempt + 1))
            res = await self.http.post(f"{self.base}/{path}", json=body, headers=self.headers)
        if res.status_code >= 400:
            raise OpenFgaError(f"OpenFGA {path} answered {res.status_code}: {res.text[:300]}")
        data: dict[str, Any] = res.json() if res.content else {}
        return data

    async def check(self, user: str, relation: str, obj: str) -> bool:
        body = {
            "tuple_key": {"user": user, "relation": relation, "object": obj},
            "authorization_model_id": self.model_id,
        }
        return bool((await self._post("check", body)).get("allowed"))

    async def batch_check(self, user: str, obj: str, relations: Iterable[str]) -> dict[str, bool]:
        rels = list(relations)
        if not rels:
            return {}
        checks = [
            {"tuple_key": {"user": user, "relation": r, "object": obj}, "correlation_id": str(i)}
            for i, r in enumerate(rels)
        ]
        result = (await self._post("batch-check", {"checks": checks, "authorization_model_id": self.model_id}))[
            "result"
        ]
        return {r: bool(result.get(str(i), {}).get("allowed")) for i, r in enumerate(rels)}

    async def list_objects(self, user: str, relation: str, type_name: str) -> list[str]:
        body = {"user": user, "relation": relation, "type": type_name, "authorization_model_id": self.model_id}
        objects: list[str] = (await self._post("list-objects", body)).get("objects", [])
        return sorted(objects)

    async def write(self, writes: Iterable[Tuple] = (), deletes: Iterable[Tuple] = ()) -> None:
        """Idempotent: existing writes and missing deletes are ignored, so a retried batch is harmless."""
        pending = [("writes", t) for t in sorted(set(writes))] + [("deletes", t) for t in sorted(set(deletes))]
        for start in range(0, len(pending), MAX_TUPLES_PER_WRITE):
            chunk = pending[start : start + MAX_TUPLES_PER_WRITE]
            body: dict[str, Any] = {"authorization_model_id": self.model_id}
            w = [t.as_key() for kind, t in chunk if kind == "writes"]
            d = [t.as_key() for kind, t in chunk if kind == "deletes"]
            if w:
                body["writes"] = {"tuple_keys": w, "on_duplicate": "ignore"}
            if d:
                body["deletes"] = {"tuple_keys": d, "on_missing": "ignore"}
            await self._post("write", body)

    async def read_all(self) -> set[Tuple]:
        tuples: set[Tuple] = set()
        token = ""
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if token:
                body["continuation_token"] = token
            data = await self._post("read", body)
            for item in data.get("tuples", []):
                key = item["key"]
                tuples.add(Tuple(key["user"], key["relation"], key["object"]))
            token = data.get("continuation_token", "")
            if not token:
                return tuples


async def ensure_store(http: httpx.AsyncClient, url: str, api_key: str, name: str, model: dict[str, Any]) -> OpenFga:
    """Find or create the store `name` and make its latest model equal to `model` (development/test only)."""
    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    store_id = ""
    token = ""
    while not store_id:
        res = await http.get(f"{base}/stores", params={"page_size": 100, "continuation_token": token}, headers=headers)
        res.raise_for_status()
        data = res.json()
        store_id = next((s["id"] for s in data.get("stores", []) if s["name"] == name), "")
        token = data.get("continuation_token", "")
        if not token:
            break
    if not store_id:
        res = await http.post(f"{base}/stores", json={"name": name}, headers=headers)
        res.raise_for_status()
        store_id = res.json()["id"]

    res = await http.get(f"{base}/stores/{store_id}/authorization-models", params={"page_size": 1}, headers=headers)
    res.raise_for_status()
    latest = res.json().get("authorization_models", [])
    if latest and _comparable(latest[0]) == _comparable(model):
        model_id = latest[0]["id"]
    else:
        res = await http.post(f"{base}/stores/{store_id}/authorization-models", json=model, headers=headers)
        res.raise_for_status()
        model_id = res.json()["authorization_model_id"]
    return OpenFga(http, url, api_key, store_id, model_id)


async def connect(http: httpx.AsyncClient, settings: Settings) -> OpenFga:
    key = settings.openfga_api_key.get_secret_value()
    if settings.openfga_store_id and settings.openfga_model_id:
        return OpenFga(http, settings.openfga_url, key, settings.openfga_store_id, settings.openfga_model_id)
    if not settings.is_local:
        raise OpenFgaError("OPENFGA_STORE_ID and OPENFGA_MODEL_ID must be pinned outside development/test")
    return await ensure_store(http, settings.openfga_url, key, settings.openfga_store_name, load_model())
