# backend/tests/test_elevenlabs_rate_limit.py
#
# The ElevenLabs client waits briefly and retries when the plan's concurrency
# limit answers 429, so one video's parallel narration clips do not fail it.

import httpx
import pytest

from backend.shared.providers.elevenlabs import client as eleven

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_transport(monkeypatch, statuses: list[int], headers: dict[str, str] | None = None) -> list[int]:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[len(seen)]
        seen.append(status)
        if status == 200:
            return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})
        return httpx.Response(status, headers=headers or {}, json={"detail": {"status": "too_many_concurrent_requests"}})

    real = _REAL_ASYNC_CLIENT
    monkeypatch.setattr(eleven.httpx, "AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    return seen


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
@pytest.mark.asyncio
async def test_a_429_is_retried_after_a_short_wait(monkeypatch) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(eleven.asyncio, "sleep", fake_sleep)
    seen = _patch_transport(monkeypatch, [429, 429, 200], headers={"retry-after": "3"})

    audio, mime = await eleven.ElevenLabsClient(api_key="placeholder")._post_audio(
        path="/text-to-speech/voice", payload={"text": "Bees visit flowers."}, output_format="mp3_44100_128")

    assert audio == b"ID3audio" and mime == "audio/mpeg"
    assert seen == [429, 429, 200] and waits == [3.0, 3.0]


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
@pytest.mark.asyncio
async def test_a_lasting_429_or_another_error_still_fails(monkeypatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(eleven.asyncio, "sleep", fake_sleep)
    seen = _patch_transport(monkeypatch, [429] * 4)
    with pytest.raises(RuntimeError, match="ElevenLabs audio generation failed"):
        await eleven.ElevenLabsClient(api_key="placeholder")._post_audio(
            path="/text-to-speech/voice", payload={"text": "x"}, output_format="mp3_44100_128")
    assert len(seen) == eleven.RATE_LIMIT_RETRIES + 1

    seen = _patch_transport(monkeypatch, [400])
    with pytest.raises(RuntimeError):
        await eleven.ElevenLabsClient(api_key="placeholder")._post_audio(
            path="/text-to-speech/voice", payload={"text": "x"}, output_format="mp3_44100_128")
    assert seen == [400]


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_retry_delay_uses_a_short_retry_after_else_backs_off() -> None:
    assert eleven._retry_delay_seconds("2", 0) == 2.0
    assert eleven._retry_delay_seconds("120", 1) == 2.0
    assert eleven._retry_delay_seconds(None, 2) == 4.0
    assert eleven._retry_delay_seconds("soon", 0) == 1.0
