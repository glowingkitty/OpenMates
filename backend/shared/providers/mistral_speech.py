"""Mistral speech HTTP boundary. No chat, billing or persistence dependencies."""
from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Any

import httpx

MISTRAL_SPEECH_MODEL = "voxtral-mini-tts-3-0"
MISTRAL_SECRET_PATH = "kv/data/providers/mistral_ai"
MISTRAL_SPEECH_URL = "https://api.mistral.ai/v1/audio/speech"


@dataclass(frozen=True)
class SpeechAudio:
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    duration_seconds: float | None = None


class MistralSpeechClient:
    def __init__(self, *, secrets_manager: Any = None, api_key: str | None = None,
                 timeout_seconds: float = 60) -> None:
        self.secrets_manager = secrets_manager
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def text_to_speech(self, *, text: str, voice_id: str,
                             model: str = MISTRAL_SPEECH_MODEL) -> SpeechAudio:
        if not text.strip() or not voice_id:
            raise ValueError("Speech requires text and a configured voice")
        key = self.api_key
        if not key and self.secrets_manager:
            key = await self.secrets_manager.get_secret(MISTRAL_SECRET_PATH, "api_key")
        key = key or os.getenv("SECRET__MISTRAL_AI__API_KEY") or os.getenv("SECRET__MISTRAL__API_KEY")
        if not key or key == "IMPORTED_TO_VAULT":
            raise RuntimeError("Mistral speech is unavailable")
        # Paid generation is retried by the existing leased segment task, never
        # transparently inside this client. Do not log source, credentials or bodies.
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(MISTRAL_SPEECH_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "input": text, "voice_id": voice_id,
                          "response_format": "mp3", "stream": False})
                response.raise_for_status()
                audio = base64.b64decode(response.json()["audio_data"], validate=True)
                if not audio or not (audio.startswith(b"ID3") or audio.startswith(b"\xff")):
                    raise ValueError("Invalid MP3 response")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, binascii.Error):
            raise RuntimeError("Mistral speech generation failed") from None
        return SpeechAudio(audio_bytes=audio)
