"""Recorded model responses (ADR-0012): record once against the provider, then replay without the network; replay
without a recording fails and makes no call."""

from pathlib import Path

import httpx
import pytest
import respx

from nexti_model_gateway.cassettes import MissingRecordingError, RecordingClient, request_key
from nexti_model_gateway.openrouter import OpenRouterClient

URL = "https://openrouter.test/api/v1"
BODY = {
    "model": "anthropic/claude-sonnet-4.5",
    "messages": [{"role": "user", "content": "Extract the rules"}],
    "max_tokens": 512,
    "usage": {"include": True},
    "provider": {"order": ["anthropic"]},
}
REPLY = {
    "id": "gen-1",
    "model": "anthropic/claude-sonnet-4.5",
    "provider": "Anthropic",
    "choices": [{"message": {"role": "assistant", "content": '{"rules": []}'}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "cost": 0.0001},
}


def _only_recording(folder: Path) -> str:
    (saved,) = folder.glob("*.json")
    return saved.read_text(encoding="utf-8")


def test_routing_preferences_do_not_change_the_key() -> None:
    assert request_key(BODY) == request_key({**BODY, "provider": {"order": ["other"]}, "usage": {}})
    assert request_key(BODY) != request_key({**BODY, "max_tokens": 1024})


async def test_record_then_replay_without_network(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as router:
            route = router.post(f"{URL}/chat/completions").respond(json=REPLY)
            recorder = RecordingClient(OpenRouterClient(http, URL), tmp_path, "record")
            first = await recorder.chat("other-key", BODY, 30)
            assert route.call_count == 1
        assert recorder.recorded == 1
        assert first.content == '{"rules": []}'
        saved = _only_recording(tmp_path)
        assert "Extract the rules" in saved
        assert "other-key" not in saved  # the API key is never written

        with respx.mock(assert_all_called=False) as router:
            route = router.post(f"{URL}/chat/completions").respond(status_code=500)
            player = RecordingClient(OpenRouterClient(http, URL), tmp_path, "replay")
            again = await player.chat("another-key", BODY, 30)
            assert route.call_count == 0
        assert (again.content, again.usage.input_tokens, str(again.usage.provider_cost_usd)) == (
            '{"rules": []}', 12, "0.0001",
        )  # fmt: skip


async def test_replay_without_a_recording_fails_and_calls_nothing(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as router:
            route = router.post(f"{URL}/chat/completions").respond(json=REPLY)
            player = RecordingClient(OpenRouterClient(http, URL), tmp_path, "replay")
            with pytest.raises(MissingRecordingError):
                await player.chat("key", BODY, 30)
            assert route.call_count == 0
