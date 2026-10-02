"""The openai-compatible client (ADR-0030) against a simulated vLLM/Ollama server."""

import json

import httpx
import pytest
import respx

from nexti_model_gateway.openrouter import OpenAICompatibleClient, ProviderError
from nexti_model_gateway.rules import OPENAI_COMPATIBLE, OfferingFacts, Policy, policy_denial

BASE = "http://vllm.internal:8000/v1"
CHAT = {
    "id": "chatcmpl-local",
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "choices": [{"message": {"role": "assistant", "content": "Ok."}}],
    "usage": {"prompt_tokens": 21, "completion_tokens": 3, "total_tokens": 24},
}


@respx.mock
async def test_chat_goes_to_the_base_url_without_a_key_when_there_is_none() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(json=CHAT)
    async with httpx.AsyncClient() as http:
        result = await OpenAICompatibleClient(http, BASE + "/").chat(None, {"model": "m", "messages": []}, 5)
    request = route.calls.last.request
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {"model": "m", "messages": []}
    assert result.content == "Ok."
    assert (result.usage.input_tokens, result.usage.output_tokens) == (21, 3)
    assert result.usage.provider_cost_usd is None  # a local server reports no cost


@respx.mock
async def test_chat_sends_the_key_when_the_connection_has_one() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(json=CHAT)
    async with httpx.AsyncClient() as http:
        await OpenAICompatibleClient(http, BASE).chat("local-key-123", {"model": "m", "messages": []}, 5)
    assert route.calls.last.request.headers["authorization"] == "Bearer local-key-123"


@respx.mock
async def test_served_models_are_listed_in_the_openai_format() -> None:
    respx.get(f"{BASE}/models").respond(
        json={
            "object": "list",
            "data": [
                {"id": "meta-llama/Llama-3.1-8B-Instruct", "object": "model", "max_model_len": 131072},
                {"id": "qwen2.5-coder:7b", "object": "model"},
                {"object": "model"},
            ],
        }
    )
    async with httpx.AsyncClient() as http:
        models = await OpenAICompatibleClient(http, BASE).served_models()
    assert [(m.provider_slug, m.context_window) for m in models] == [
        ("meta-llama/Llama-3.1-8B-Instruct", 131072),
        ("qwen2.5-coder:7b", None),
    ]


@respx.mock
async def test_a_server_error_is_retryable() -> None:
    respx.post(f"{BASE}/chat/completions").respond(503, text="loading model")
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError) as error:
            await OpenAICompatibleClient(http, BASE).chat(None, {"model": "m", "messages": []}, 5)
    assert error.value.retryable


def test_the_upstream_lists_do_not_apply_to_a_local_server_but_zdr_does() -> None:
    local = OfferingFacts(OPENAI_COMPATIBLE, "connection:x", zdr=False)
    assert policy_denial(Policy(allowed_upstream_providers=("azure",), openrouter_allowed=False), local) is None
    assert policy_denial(Policy(require_zdr=True), local) == "zdr_required"
    assert policy_denial(Policy(require_zdr=True), OfferingFacts(OPENAI_COMPATIBLE, "connection:x", zdr=True)) is None
