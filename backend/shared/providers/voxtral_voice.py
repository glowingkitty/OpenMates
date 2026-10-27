"""Mistral Voxtral 3 realtime STT; no conversation context or answer model.

Provider turn.end precedes some final text deltas. Consumers must retain the
current utterance for STREAMING_DELAY_MS, or until the next turn.start.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
import json
import logging
from time import monotonic
from typing import Any

import aiohttp

from backend.shared.providers.live_voice import LiveVoiceCapabilities

VOXTRAL_VOICE_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
VOXTRAL_VOICE_MODEL = "voxtral-mini-transcribe-realtime-3-0"
STREAMING_DELAY_MS = 240
# Exceed the documented default 3s endpoint timeout. Padding is never user usage.
FLUSH_SILENCE_BYTES = 32000 * 7 // 2
# WebSocket pings don't reset Voxtral's ~30s application audio idle timeout.
# Send only 200ms per idle interval; synthetic PCM never counts as user audio.
IDLE_AUDIO_INTERVAL_SECONDS = 10.0
IDLE_SILENCE_PCM = base64.b64encode(bytes(32000 // 5)).decode("ascii")
logger = logging.getLogger(__name__)


class VoxtralVoiceError(RuntimeError):
    """Provider failure with bounded diagnostics and no upstream payload text."""

    def __init__(self, provider_code: int | None = None) -> None:
        super().__init__("Voice transcription failed")
        self.provider_code = provider_code
        self.provider_category = "idle_timeout" if provider_code == 3804 else "provider_error"


class VoxtralVoiceSession:
    model = VOXTRAL_VOICE_MODEL
    capabilities = LiveVoiceCapabilities()

    def __init__(self, key: str) -> None:
        self._key = key
        self._http: aiohttp.ClientSession | None = None
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._unflushed_audio = False
        self._last_audio_sent = monotonic()
        self._idle_audio_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        try:
            self._socket = await self._http.ws_connect(
                f"{VOXTRAL_VOICE_URL}?model={self.model}",
                headers={"Authorization": f"Bearer {self._key}"}, heartbeat=20,
                max_msg_size=2 * 1024 * 1024,
            )
            if (await asyncio.wait_for(self.receive(), 10)).get("type") != "session.created":
                raise RuntimeError("Voice transcription session unavailable")
            await self._socket.send_json({"type": "session.update", "session": {
                "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
                "target_streaming_delay_ms": STREAMING_DELAY_MS, "turn_detection": {},
            }})
            if (await asyncio.wait_for(self.receive(), 10)).get("type") != "session.updated":
                raise RuntimeError("Voice transcription settings unavailable")
            self._last_audio_sent = monotonic()
            self._idle_audio_task = asyncio.create_task(self._maintain_idle_audio())
        except BaseException:
            await self.close()
            raise

    async def send_audio(self, encoded_pcm: str) -> None:
        async with self._send_lock:
            if self._socket is None:
                raise RuntimeError("Voice transcription unavailable")
            await self._socket.send_json({"type": "input_audio.append", "audio": encoded_pcm})
            self._last_audio_sent = monotonic()
            self._unflushed_audio = True

    async def end_audio(self) -> None:
        """Flush a muted microphone without ending the continuous STT session."""
        async with self._send_lock:
            if self._socket is None:
                raise RuntimeError("Voice transcription unavailable")
            if self._unflushed_audio:
                await self._socket.send_json({"type": "input_audio.append", "audio":
                    base64.b64encode(bytes(FLUSH_SILENCE_BYTES)).decode("ascii")})
                self._last_audio_sent = monotonic()
                self._unflushed_audio = False

    async def _maintain_idle_audio(self) -> None:
        """Keep an authenticated call's idle STT stream alive without a turn flush."""
        while True:
            await asyncio.sleep(max(0, IDLE_AUDIO_INTERVAL_SECONDS - (monotonic() - self._last_audio_sent)))
            async with self._send_lock:
                # Real mic audio or its flush may have arrived while we waited.
                if monotonic() - self._last_audio_sent < IDLE_AUDIO_INTERVAL_SECONDS:
                    continue
                if self._socket is None:
                    return
                try:
                    await self._socket.send_json({"type": "input_audio.append", "audio": IDLE_SILENCE_PCM})
                except Exception:
                    # Close wakes the receiver's normal disconnect path. Never log
                    # upstream exception text, which can contain private payloads.
                    logger.warning("Voxtral idle audio keepalive failed")
                    try:
                        await self._socket.close()
                    except Exception:
                        logger.warning("Voxtral idle audio disconnect failed")
                    return
                self._last_audio_sent = monotonic()

    async def receive(self) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("Voice transcription unavailable")
        message = await self._socket.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Voice transcription disconnected")
        event = json.loads(message.data)
        if not isinstance(event, dict):
            raise RuntimeError("Voice transcription failed")
        if event.get("type") == "error":
            details = event.get("error")
            code = details.get("code") if isinstance(details, dict) else None
            if type(code) is not int or not 0 <= code <= 999999:
                code = None
            error = VoxtralVoiceError(code)
            logger.warning("Voxtral transcription failed provider_code=%s category=%s",
                           error.provider_code, error.provider_category)
            raise error
        return event

    async def close(self) -> None:
        if self._idle_audio_task is not None:
            self._idle_audio_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._idle_audio_task
            self._idle_audio_task = None
        async with self._send_lock:
            if self._socket is not None:
                await self._socket.close()
                self._socket = None
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._key = ""
