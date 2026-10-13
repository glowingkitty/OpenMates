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


class IsolatedGeminiVoiceFixture:
    model = "gemini-3.8-live"
    capabilities = LiveVoiceCapabilities(audio_input=True, text_input=True, audio_output=True, transcripts=True)

    def __init__(self) -> None:
        if not isolated_voice_fixture_enabled():
            raise RuntimeError("Isolated voice fixture is unavailable")
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._audio_bytes = 0
        self._mic_answered = False

    async def open(self, *, summary: str, messages: list[dict[str, str]]) -> None:
        # Context is deliberately ignored; the E2E tests exercise admission,
        # transport, identities, encryption and synchronization.
        return None

    async def _answer(self, user_text: str, assistant_text: str) -> None:
        await self._events.put({"serverContent": {"inputTranscription": {"text": user_text}}})
        await self._events.put({"serverContent": {
            "outputTranscription": {"text": assistant_text},
            "modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000",
                "data": base64.b64encode(b"\0\0" * 2400).decode("ascii"),
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
        if self._mic_answered:
            return
        self._audio_bytes += len(base64.b64decode(encoded_pcm, validate=True))
        if self._audio_bytes >= 3200:
            self._mic_answered = True
            await self._answer("How do I make ramen?", "For ramen, simmer the broth and cook the noodles.")

    async def send_text(self, text: str) -> None:
        await self._answer("", "I received your text: " + text[:500])

    async def receive(self) -> dict[str, Any]:
        return await self._events.get()

    async def resume(self, handle: str) -> None:
        return None

    async def close(self) -> None:
        return None
