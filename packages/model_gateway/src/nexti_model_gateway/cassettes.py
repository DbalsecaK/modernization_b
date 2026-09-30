"""Recorded model responses for tests (ADR-0012). The provider client is wrapped: in `replay` a request is answered
with the response recorded for the same request and fails (without touching the network) if there is none; in
`record` the real provider is called and the response is saved. The whole gateway path (profile, policy, budget,
usage ledger) still runs: only the HTTP call to the provider is replaced.

The key of a request is a hash of what decides the answer: model, messages, output limit, temperature and the other
body parameters, not the routing preferences. Recordings of customer reference applications stay in their kit
(ADR-0011); the repository only holds recordings of the fictitious application.

Only development and test may enable it (the settings refuse it elsewhere)."""

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from nexti_model_gateway.openrouter import ChatResult, ChatUsage, OpenRouterClient

Mode = Literal["replay", "record"]
VOLATILE = ("provider", "usage")  # routing and "include usage": they do not change the answer


class MissingRecordingError(LookupError):
    """Replay without a recording: the test must be recorded (with a budget) before it can run."""

    def __init__(self, key: str, model: str) -> None:
        super().__init__(f"no recorded response {key} for model {model}; record it with MODEL_CASSETTES_MODE=record")
        self.key = key


def request_key(body: dict[str, Any]) -> str:
    stable = {k: v for k, v in body.items() if k not in VOLATILE}
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _dump(result: ChatResult) -> dict[str, Any]:
    usage = asdict(result.usage)
    usage["provider_cost_usd"] = (
        str(result.usage.provider_cost_usd) if result.usage.provider_cost_usd is not None else None
    )
    return {
        "request_id": result.request_id, "model": result.model, "provider_name": result.provider_name,
        "content": result.content, "usage": usage,
    }  # fmt: skip


def _load(data: dict[str, Any]) -> ChatResult:
    usage = dict(data["usage"])
    cost = usage.pop("provider_cost_usd", None)
    return ChatResult(
        request_id=data.get("request_id"),
        model=data["model"],
        provider_name=data.get("provider_name"),
        content=data["content"],
        usage=ChatUsage(**usage, provider_cost_usd=Decimal(cost) if cost is not None else None),
    )


class RecordingClient(OpenRouterClient):
    """The provider client with recorded responses. Everything but `chat` is the real client's."""

    def __init__(self, inner: OpenRouterClient, directory: Path, mode: Mode) -> None:
        super().__init__(inner.http, inner.base_url)
        self.directory = directory
        self.mode = mode
        self.hits = 0
        self.recorded = 0

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    async def chat(self, api_key: str, body: dict[str, Any], timeout_seconds: float) -> ChatResult:
        key = request_key(body)
        path = self._path(key)
        if path.exists():
            self.hits += 1
            return _load(json.loads(path.read_text(encoding="utf-8"))["response"])
        if self.mode == "replay":
            raise MissingRecordingError(key, str(body.get("model", "")))
        result = await super().chat(api_key, body, timeout_seconds)
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {
            "request_digest": key,  # the file name; not a credential
            "model": body.get("model"),
            "messages": body.get("messages"),
            "response": _dump(result),
        }
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.recorded += 1
        return result
