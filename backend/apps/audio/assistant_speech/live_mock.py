# backend/apps/audio/assistant_speech/live_mock.py
#
# Narrow binary replay support for the deployed assistant speech E2E flow.
# Production, unmarked requests, and unrelated test groups always resolve None.
# The worker still encrypts and stores replayed bytes through the normal path.
#

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ASSISTANT_SPEECH_LIVE_MOCK_GROUP = "assistant_response_speech_web"
ASSISTANT_SPEECH_LIVE_MOCK_AUDIO = (
    Path(__file__).resolve().parents[4]
    / "frontend/apps/web_app/static/audio/assistant-acknowledgements/hiro/en-US/general-1.mp3"
)


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
