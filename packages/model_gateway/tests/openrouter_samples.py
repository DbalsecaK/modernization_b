"""Responses recorded from the real OpenRouter API (2026-09-28), trimmed to the fields the gateway reads."""

from typing import Any

MODEL = "openai/gpt-4o-mini"

MODELS: dict[str, Any] = {
    "data": [
        {
            "id": MODEL,
            "canonical_slug": MODEL,
            "name": "OpenAI: GPT-4o-mini",
            "context_length": 128000,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006", "input_cache_read": "0.000000075"},
            "architecture": {"input_modalities": ["text", "image", "file"], "output_modalities": ["text"]},
            "supported_parameters": ["max_tokens", "response_format", "structured_outputs", "temperature", "tools"],
        },
        {
            "id": "anthropic/claude-sonnet-5.5",
            "canonical_slug": "anthropic/claude-sonnet-5.5-20260928",
            "name": "Anthropic: Claude Sonnet 5.5",
            "context_length": 1000000,
            "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            "architecture": {"input_modalities": ["text", "image"]},
            "supported_parameters": ["max_tokens", "reasoning", "include_reasoning", "tools"],
        },
    ]
}

ENDPOINTS: dict[str, Any] = {
    "data": {
        "id": MODEL,
        "architecture": {"input_modalities": ["text", "image", "file"]},
        "endpoints": [
            {
                "tag": "openai",
                "provider_name": "OpenAI",
                "context_length": 128000,
                "max_completion_tokens": 16384,
                "pricing": {"prompt": "0.00000015", "completion": "0.0000006", "input_cache_read": "0.000000075"},
                "status": 0,
                "supported_parameters": ["max_tokens", "response_format", "structured_outputs", "temperature"],
            },
            {
                "tag": "azure/swedencentral",
                "provider_name": "Azure",
                "context_length": 128000,
                "max_completion_tokens": 16384,
                "pricing": {"prompt": "0.000000165", "completion": "0.00000066", "input_cache_read": "0.0000000825"},
                "status": 0,
                "supported_parameters": ["max_completion_tokens", "temperature"],
            },
        ],
    }
}

ZDR: dict[str, Any] = {"data": [{"model_id": MODEL, "tag": "azure/swedencentral"}]}

KEY: dict[str, Any] = {"data": {"label": "sk-or-v1-...", "limit": None, "usage": 0, "is_free_tier": False}}

CHAT: dict[str, Any] = {
    "id": "gen-1790628304-pjcAsL5Yt2cAUg3zR8Vq",
    "model": MODEL,
    "provider": "OpenAI",
    "choices": [{"message": {"role": "assistant", "content": "Ok."}}],
    "usage": {
        "prompt_tokens": 13,
        "completion_tokens": 2,
        "total_tokens": 15,
        "cost": 3.15e-06,
        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}
