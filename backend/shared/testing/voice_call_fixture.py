"""Isolated CI-only Voxtral-shaped voice events for transport and ciphertext E2E.

This module is unreachable without all four isolated CI environment guards.
It does not contact a provider or retain media/transcript content.
"""

from __future__ import annotations

import asyncio
import base64
import os
import struct
from typing import Any

from backend.shared.providers.live_voice import LiveVoiceCapabilities


def isolated_voice_fixture_enabled() -> bool:
    return (
        os.getenv("CI") == "true"
        and os.getenv("OPENMATES_CI_ISOLATED") == "1"
        and os.getenv("OPENMATES_CI_AI_FIXTURES") == "1"
        and os.getenv("MOCK_EXTERNAL_APIS") == "true"
    )


def isolated_voice_completion_fixture(text: str) -> str | None:
    """Classify only known CI microphone transcripts, behind every CI guard."""
    if not isolated_voice_fixture_enabled():
        return None
    return {
        "How do I make": "incomplete",
        "How do I make ramen?": "complete",
    }.get(text)


VOICE_RICH_SOURCE_URL = "https://app.dev.openmates.org/store-examples/generate-1.webp"


def isolated_voice_source_url_fixture(url: str) -> bool:
    """Substitute upstream verdicts only for the existing public image fixture."""
    return isolated_voice_fixture_enabled() and url == VOICE_RICH_SOURCE_URL


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


class IsolatedVoxtralVoiceFixture:
    model = "voxtral-mini-transcribe-realtime-3-0"
    capabilities = LiveVoiceCapabilities()

    def __init__(self) -> None:
        if not isolated_voice_fixture_enabled():
            raise RuntimeError("Isolated voice fixture is unavailable")
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._audio_bytes = 0
        self._mic_started = False
        self._mic_answered = False

    async def open(self) -> None:
        return None

    async def send_audio(self, encoded_pcm: str) -> None:
        pcm = base64.b64decode(encoded_pcm, validate=True)
        # Silent fixture microphone chunks must never invent a user request.
        voiced = any(abs(sample) >= 128 for (sample,) in struct.iter_unpack("<h", pcm[:len(pcm) // 2 * 2]))
        if voiced:
            self._audio_bytes += len(pcm)
        if self._audio_bytes >= 3200 and not self._mic_started:
            self._mic_started = True
            await self._events.put({"type": "turn.start", "time_s": 0})
            await self._events.put({"type": "transcription.text.delta", "text": "How do I make"})
            await self._events.put({"type": "turn.end", "time_s": 0.1, "end_reason": "threshold"})
        # The continuation requires later voiced microphone input. A short
        # initial clip followed by silence therefore holds indefinitely, while
        # ordinary fixture playback resumes across a native provider boundary.
        elif voiced and self._audio_bytes >= 32000 and not self._mic_answered:
            self._mic_answered = True
            await self._events.put({"type": "turn.start", "time_s": 1})
            await self._events.put({"type": "transcription.text.delta", "text": "ramen?"})
            await self._events.put({"type": "turn.end", "time_s": 1.1, "end_reason": "threshold"})

    async def receive(self) -> dict[str, Any]:
        return await self._events.get()

    async def end_audio(self) -> None:
        return None

    async def close(self) -> None:
        while not self._events.empty():
            self._events.get_nowait()
