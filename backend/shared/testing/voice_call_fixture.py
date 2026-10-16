"""Isolated CI-only Gemini-shaped voice events for transport and ciphertext E2E.

This module is unreachable without all four isolated CI environment guards.
It does not contact a provider or retain media/transcript content.
"""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

from backend.shared.providers.live_voice import LiveVoiceCapabilities


def isolated_voice_fixture_enabled() -> bool:
    return (
        os.getenv("CI") == "true"
        and os.getenv("OPENMATES_CI_ISOLATED") == "1"
        and os.getenv("OPENMATES_CI_AI_FIXTURES") == "1"
        and os.getenv("MOCK_EXTERNAL_APIS") == "true"
    )


# Isolated CI uses a per-account override so existing voice flows remain focused
# on transport, while the first-use test exercises the real Directus profile.
VOICE_ACK_DEFAULT_TIMESTAMP = 1_700_000_000
VOICE_ACK_FIXTURE_TTL_SECONDS = 3600


def _voice_ack_fixture_key(user_id: str, kind: str) -> str:
    return f"isolated-voice-ack:{kind}:{user_id}"


async def voice_ack_fixture_requires_profile(cache: Any, user_id: str) -> bool:
    if not isolated_voice_fixture_enabled():
        return True
    getter = getattr(cache, "get", None)
    return bool(await getter(_voice_ack_fixture_key(user_id, "profile"))) if getter else False


async def set_voice_ack_fixture_profile_mode(cache: Any, user_id: str) -> None:
    if not isolated_voice_fixture_enabled():
        raise RuntimeError("Isolated voice fixture is unavailable")
    await cache.set(_voice_ack_fixture_key(user_id, "profile"), True, ttl=VOICE_ACK_FIXTURE_TTL_SECONDS)


async def set_voice_ack_fixture_fail_next_write(cache: Any, user_id: str) -> None:
    if not isolated_voice_fixture_enabled():
        raise RuntimeError("Isolated voice fixture is unavailable")
    await cache.set(_voice_ack_fixture_key(user_id, "fail_next_write"), True, ttl=VOICE_ACK_FIXTURE_TTL_SECONDS)


async def consume_voice_ack_fixture_write_failure(cache: Any, user_id: str) -> bool:
    if not isolated_voice_fixture_enabled():
        return False
    key = _voice_ack_fixture_key(user_id, "fail_next_write")
    if not await cache.get(key):
        return False
    await cache.delete(key)
    return True


class IsolatedGeminiVoiceFixture:
    model = "gemini-3.8-live"
    capabilities = LiveVoiceCapabilities(audio_input=True, text_input=True, audio_output=True, transcripts=True, tools=True)

    def __init__(self) -> None:
        if not isolated_voice_fixture_enabled():
            raise RuntimeError("Isolated voice fixture is unavailable")
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._audio_bytes = 0
        self._activity_reply_pending = False
        self._mic_answered = False
        self._tool_counter = 0
        self._answers: set[asyncio.Task[None]] = set()

    async def open(self, *, summary: str, messages: list[dict[str, str]],
                   base_instruction: str = "", app_catalogue: str = "",
                   active_focus: dict[str, Any] | None = None) -> None:
        # Context is deliberately ignored; the E2E tests exercise admission,
        # transport, identities, encryption and synchronization.
        return None

    async def _answer(self, user_text: str, assistant_text: str, *, audio_samples: int = 2400) -> None:
        await self._events.put({"serverContent": {"inputTranscription": {"text": user_text}}})
        await self._events.put({"serverContent": {
            "outputTranscription": {"text": assistant_text},
            "modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000",
                "data": base64.b64encode(b"\0\0" * audio_samples).decode("ascii"),
            }}]},
        }})
        await self._events.put({
            "serverContent": {"turnComplete": True},
            "usageMetadata": {
                "promptTokenCount": 10, "responseTokenCount": 10, "totalTokenCount": 20,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 10}],
                "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 10}],
            },
        })

    async def send_audio(self, encoded_pcm: str) -> None:
        if self._activity_reply_pending:
            self._activity_reply_pending = False
            # A real resumed microphone frame releases processing. The bounded
            # two-second playback proves queued speech after generation ended.
            await self._answer("", "Your voice activity fixture reply is ready.", audio_samples=48_000)
            return
        if self._mic_answered:
            return
        self._audio_bytes += len(base64.b64decode(encoded_pcm, validate=True))
        if self._audio_bytes >= 3200:
            self._mic_answered = True
            await self._answer("How do I make ramen?", "For ramen, simmer the broth and cook the noodles.")

    async def send_text(self, text: str) -> None:
        if text == "Hold this voice activity reply until I speak again.":
            self._activity_reply_pending = True
            return
        if text == "Voice stage two fixture: apply memory and search the web":
            self._tool_counter += 1
            await self._events.put({"toolCall": {"functionCalls": [{
                "id": f"voice-stage-two-{self._tool_counter}", "name": "process_request", "args": {"request": text},
            }]}})
            return
        await self._answer("", "I received your text: " + text[:500])

    async def receive(self) -> dict[str, Any]:
        return await self._events.get()

    async def update_context(self, **kwargs: Any) -> None:
        return None

    async def end_audio(self) -> None:
        return None

    async def send_tool_response(self, function_call_id: str, response: dict[str, Any]) -> None:
        memories = (response.get("context") or {}).get("memories")
        text = ("Your approved memory is loaded and the search results are ready." if memories
                else "The search results are ready. Your private memory was not loaded.")
        if response.get("status") == "permission_declined":
            text = "The requested access was declined. Your private context was not loaded."
        async def after_receipt() -> None:
            # Let the real main-WebSocket committed artifact receipt reach the
            # browser before synthetic speech, exercising artifact-only hangup.
            await asyncio.sleep(1)
            await self._answer("", text)
        task = asyncio.create_task(after_receipt())
        self._answers.add(task)
        task.add_done_callback(self._answers.discard)

    async def resume(self, handle: str) -> None:
        return None

    async def close(self) -> None:
        for task in self._answers:
            task.cancel()
        if self._answers:
            await asyncio.gather(*self._answers, return_exceptions=True)
            self._answers.clear()
        while not self._events.empty():
            self._events.get_nowait()
