# backend/apps/audio/assistant_speech/live_mock.py
#
# Narrow binary replay support for the deployed assistant speech E2E flow.
# Production, unmarked requests, and unrelated test groups always resolve None.
# The worker still encrypts and stores replayed bytes through the normal path.
#

from __future__ import annotations

import os
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

ASSISTANT_SPEECH_LIVE_MOCK_GROUP = "assistant_response_speech_web"
ASSISTANT_SPEECH_LIVE_MOCK_AUDIO = (
    Path(__file__).resolve().parents[4]
    / "frontend/apps/web_app/static/audio/assistant-acknowledgements/hiro/en-US/general-1.mp3"
)


class AssistantSpeechReplayStreamClient:
    """Feed the already-authorized CI fixture through the real live transport."""

    def __init__(self, audio_path: Path) -> None:
        # Only assistant_speech_live_mock_audio can authorize this test boundary.
        if assistant_speech_live_mock_audio({
            "live_mock_mode": "mock", "live_mock_group": ASSISTANT_SPEECH_LIVE_MOCK_GROUP,
        }) != audio_path:
            raise RuntimeError("Assistant speech replay stream is unavailable")
        self.audio_path = audio_path

    async def stream_text_to_speech(self, **_kwargs: object) -> AsyncIterator[bytes]:
        audio = self.audio_path.read_bytes()
        yield audio[:16384]
        # Give native playback a measurable window before provider completion.
        await asyncio.sleep(0.75)
        for offset in range(16384, len(audio), 4096):
            yield audio[offset:offset + 4096]


def assistant_speech_live_mock_audio(arguments: dict[str, Any]) -> Path | None:
    """Resolve the binary fixture only for the exact marked non-production flow."""
    required = arguments.get("live_mock_required") == "true"
    if os.getenv("SERVER_ENVIRONMENT", "production") == "production":
        if required:
            raise RuntimeError("Assistant speech live-mock replay is disabled in production")
        return None
    if os.getenv("MOCK_EXTERNAL_APIS") != "true":
        if required:
            raise RuntimeError("Assistant speech live-mock replay is disabled")
        return None
    if arguments.get("live_mock_mode") not in {"mock", "record"}:
        if required:
            raise RuntimeError("Assistant speech live-mock mode is unavailable")
        return None
    if arguments.get("live_mock_group") != ASSISTANT_SPEECH_LIVE_MOCK_GROUP:
        if required:
            raise RuntimeError("Assistant speech live-mock group is unavailable")
        return None
    if not ASSISTANT_SPEECH_LIVE_MOCK_AUDIO.is_file():
        raise RuntimeError("Assistant speech live-mock audio fixture is unavailable")
    return ASSISTANT_SPEECH_LIVE_MOCK_AUDIO
