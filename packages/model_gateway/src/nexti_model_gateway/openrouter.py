"""OpenRouter HTTP client (OpenAI-compatible API). Only the gateway uses it.

Requests pin the upstream provider (`provider.order` + `allow_fallbacks: false`) so the offering, and therefore
the price, is exactly the one configured, and ask for the usage with its cost (`usage.include`).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

BASE_URL = "https://openrouter.ai/api/v1"
MTOK = Decimal(1_000_000)
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ProviderError(Exception):
    """The provider refused or failed the request. `retryable` tells the gateway whether to try again."""

    def __init__(self, status: int, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens (OpenRouter publishes USD per token)."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_read_per_mtok: Decimal | None = None
    cache_write_per_mtok: Decimal | None = None
    request_usd: Decimal | None = None


@dataclass(frozen=True)
class ModelInfo:
    provider_slug: str
    canonical_slug: str
    name: str
    context_window: int | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class EndpointInfo:
    upstream_provider: str
    provider_name: str
    context_window: int | None
    max_output_tokens: int | None
    pricing: Pricing
    capabilities: tuple[str, ...]
    available: bool


@dataclass(frozen=True)
class ChatUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    provider_cost_usd: Decimal | None = None


@dataclass(frozen=True)
class ChatResult:
    request_id: str | None
    model: str
    provider_name: str | None
    content: str
    usage: ChatUsage
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _per_mtok(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return (Decimal(str(value)) * MTOK).quantize(Decimal("0.000001"))


def parse_pricing(pricing: dict[str, Any]) -> Pricing:
    return Pricing(
        input_per_mtok=_per_mtok(pricing.get("prompt")) or Decimal(0),
        output_per_mtok=_per_mtok(pricing.get("completion")) or Decimal(0),
        cache_read_per_mtok=_per_mtok(pricing.get("input_cache_read")),
        cache_write_per_mtok=_per_mtok(pricing.get("input_cache_write")),
        request_usd=Decimal(str(pricing["request"])) if pricing.get("request") not in (None, "", "0") else None,
    )


def capabilities_from(supported_parameters: list[str], input_modalities: list[str] | None = None) -> tuple[str, ...]:
    """The capabilities the UI checks before assigning a model (spec 12.2)."""
    params = set(supported_parameters or [])
    caps = set()
    if "tools" in params:
        caps.add("tools")
    if "structured_outputs" in params or "response_format" in params:
        caps.add("structured_output")
    if "reasoning" in params or "include_reasoning" in params:
        caps.add("reasoning")
    if input_modalities and "image" in input_modalities:
        caps.add("vision")
    return tuple(sorted(caps))


class OpenRouterClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str = BASE_URL) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def _get(self, path: str, api_key: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        res = await self.http.get(f"{self.base_url}{path}", headers=headers)
        if res.status_code != 200:
            raise ProviderError(
                res.status_code, "http_error", res.text[:200], retryable=res.status_code in RETRYABLE_STATUS
            )
        return res.json()

    async def list_models(self) -> list[ModelInfo]:
        """The public catalog (no API key needed)."""
        out = []
        for m in (await self._get("/models"))["data"]:
            arch = m.get("architecture") or {}
            out.append(
                ModelInfo(
                    provider_slug=m["id"],
                    canonical_slug=m.get("canonical_slug") or m["id"],
                    name=m.get("name") or m["id"],
                    context_window=m.get("context_length"),
                    capabilities=capabilities_from(m.get("supported_parameters", []), arch.get("input_modalities")),
                )
            )
        return out

    async def list_endpoints(self, provider_slug: str) -> list[EndpointInfo]:
        """The upstream providers serving one model, each with its own price."""
        data = (await self._get(f"/models/{provider_slug}/endpoints"))["data"]
        modalities = (data.get("architecture") or {}).get("input_modalities")
        return [
            EndpointInfo(
                upstream_provider=e["tag"],
                provider_name=e.get("provider_name") or e["tag"],
                context_window=e.get("context_length"),
                max_output_tokens=e.get("max_completion_tokens"),
                pricing=parse_pricing(e.get("pricing") or {}),
                capabilities=capabilities_from(e.get("supported_parameters", []), modalities),
                available=e.get("status", 0) >= 0,
            )
            for e in data.get("endpoints", [])
        ]

    async def zdr_endpoints(self) -> set[tuple[str, str]]:
        """(model id, upstream provider tag) of every endpoint with zero data retention."""
        data = await self._get("/endpoints/zdr")
        items = data.get("data", data) if isinstance(data, dict) else data
        return {(e["model_id"], e["tag"]) for e in items if e.get("model_id") and e.get("tag")}

    async def key_info(self, api_key: str) -> dict[str, Any]:
        """Validates the API key without calling a model (free): limit, usage, free tier."""
        info: dict[str, Any] = (await self._get("/key", api_key))["data"]
        return info

    async def chat(self, api_key: str, body: dict[str, Any], timeout_seconds: float) -> ChatResult:
        try:
            res = await self.http.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(408, "timeout", str(exc) or "timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError(503, "network_error", str(exc), retryable=True) from exc
        data = res.json() if res.content else {}
        error = data.get("error") if isinstance(data, dict) else None
        if res.status_code != 200 or error:
            code = str((error or {}).get("code", ""))
            status = int(code) if code.isdigit() else res.status_code
            message = (error or {}).get("message") or res.text[:200]
            raise ProviderError(status, "provider_error", str(message)[:300], retryable=status in RETRYABLE_STATUS)
        usage = data.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        cost = usage.get("cost")
        choice = (data.get("choices") or [{}])[0]
        return ChatResult(
            request_id=data.get("id"),
            model=data.get("model") or body.get("model", ""),
            provider_name=data.get("provider"),
            content=(choice.get("message") or {}).get("content") or "",
            usage=ChatUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
                cache_read_tokens=int(prompt_details.get("cached_tokens") or 0),
                cache_write_tokens=int(prompt_details.get("cache_write_tokens") or 0),
                provider_cost_usd=Decimal(str(cost)) if cost is not None else None,
            ),
            raw=data,
        )
