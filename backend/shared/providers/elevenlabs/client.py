# backend/shared/providers/elevenlabs/client.py
#
# Pure ElevenLabs HTTP client for OpenMates. This module owns authentication,
# endpoint URLs, timeouts, and provider response normalization only. App skills
# are responsible for OpenMates-specific validation, safety, billing, storage,
# and embed metadata.

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_SECRET_PATH = "kv/data/providers/elevenlabs"
ELEVENLABS_ENV_KEY = "SECRET__ELEVENLABS__API_KEY"
DEFAULT_SOUND_EFFECT_MODEL = "eleven_text_to_sound_v2"
DEFAULT_TTS_MODEL = "eleven_v3"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_TIMEOUT_SECONDS = 60.0
BITS_PER_BYTE = 8
KILOBITS_PER_SECOND = 1000
ID3V2_HEADER_BYTES = 10
ID3V1_TAG_BYTES = 128


def _mp3_payload_size(audio_bytes: bytes) -> int:
    payload = audio_bytes or b""
    start = 0
    end = len(payload)
    if payload.startswith(b"ID3") and len(payload) >= ID3V2_HEADER_BYTES:
        size_bytes = payload[6:10]
        tag_size = (
            ((size_bytes[0] & 0x7F) << 21)
            | ((size_bytes[1] & 0x7F) << 14)
            | ((size_bytes[2] & 0x7F) << 7)
            | (size_bytes[3] & 0x7F)
        )
        start = min(ID3V2_HEADER_BYTES + tag_size, end)
    if end - start >= ID3V1_TAG_BYTES and payload[end - ID3V1_TAG_BYTES : end - ID3V1_TAG_BYTES + 3] == b"TAG":
        end -= ID3V1_TAG_BYTES
    return max(0, end - start)


def _estimate_mp3_duration_seconds(audio_bytes: bytes, output_format: str) -> Optional[float]:
    """Estimate generated MP3 duration from ElevenLabs' fixed bitrate output format."""

    parts = output_format.split("_")
    if len(parts) != 3 or parts[0] != "mp3":
        return None
    try:
        bitrate_bps = int(parts[2]) * KILOBITS_PER_SECOND
    except ValueError:
        return None
    if bitrate_bps <= 0:
        return None
    payload_size = _mp3_payload_size(audio_bytes)
    if payload_size <= 0:
        return None
    return round((payload_size * BITS_PER_BYTE) / bitrate_bps, 3)


class ElevenLabsClient:
    """Minimal async ElevenLabs client with Vault-first secret loading."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        secrets_manager: Optional[SecretsManager] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._secrets_manager = secrets_manager
        self._timeout_seconds = timeout_seconds

    async def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key

        if self._secrets_manager:
            try:
                self._api_key = await self._secrets_manager.get_secret(
                    secret_path=ELEVENLABS_SECRET_PATH,
                    secret_key="api_key",
                )
            except Exception as exc:
                logger.error("Failed to load ElevenLabs API key from Vault: %s", exc)

        self._api_key = self._api_key or os.getenv(ELEVENLABS_ENV_KEY)
        if not self._api_key:
            raise RuntimeError("ElevenLabs API key is not configured")
        return self._api_key

    async def _post_audio(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        output_format: str,
    ) -> tuple[bytes, str]:
        api_key = await self._get_api_key()
        url = f"{ELEVENLABS_BASE_URL}{path}"
        headers = {
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                url,
                params={"output_format": output_format},
                headers=headers,
                json=payload,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            logger.error("ElevenLabs audio request failed with status %s", status_code)
            raise RuntimeError("ElevenLabs audio generation failed") from exc

        audio_bytes = response.content or b""
        if not audio_bytes:
            raise RuntimeError("ElevenLabs returned empty audio")
        content_type = response.headers.get("content-type") or "audio/mpeg"
        return audio_bytes, content_type.split(";", 1)[0]

    async def generate_sound_effect(
        self,
        *,
        prompt: str,
        duration_seconds: float,
        prompt_influence: float = 0.3,
        loop: bool = False,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        model: str = DEFAULT_SOUND_EFFECT_MODEL,
    ) -> ElevenLabsAudioResult:
        """Generate a short sound effect from text."""

        payload = {
            "text": prompt,
            "duration_seconds": duration_seconds,
            "prompt_influence": prompt_influence,
            "loop": loop,
            "model_id": model,
        }
        audio_bytes, mime_type = await self._post_audio(
            path="/sound-generation",
            payload=payload,
            output_format=output_format,
        )
        return ElevenLabsAudioResult(
            audio_bytes=audio_bytes,
            mime_type=mime_type or "audio/mpeg",
            model=model,
            duration_seconds=duration_seconds,
        )

    async def text_to_speech(
        self,
        *,
        text: str,
        voice_id: str,
        model: str = DEFAULT_TTS_MODEL,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        speed: float = 1.0,
    ) -> ElevenLabsAudioResult:
        """Generate speech audio for approved text."""

        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {"speed": speed},
        }
        audio_bytes, mime_type = await self._post_audio(
            path=f"/text-to-speech/{voice_id}",
            payload=payload,
            output_format=output_format,
        )
        return ElevenLabsAudioResult(
            audio_bytes=audio_bytes,
            mime_type=mime_type or "audio/mpeg",
            model=model,
            duration_seconds=_estimate_mp3_duration_seconds(audio_bytes, output_format),
        )

    async def get_subscription(self) -> dict[str, Any]:
        """Low-cost account probe for configured-key checks."""

        api_key = await self._get_api_key()
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{ELEVENLABS_BASE_URL}/user/subscription",
                headers={"xi-api-key": api_key, "Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
