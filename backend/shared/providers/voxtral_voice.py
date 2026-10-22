"""Mistral Voxtral 3 realtime STT; no conversation context or answer model.

Provider turn.end precedes some final text deltas. Consumers must retain the
current utterance for STREAMING_DELAY_MS, or until the next turn.start.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import aiohttp

from backend.shared.providers.live_voice import LiveVoiceCapabilities

VOXTRAL_VOICE_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
VOXTRAL_VOICE_MODEL = "voxtral-mini-transcribe-realtime-3-0"
STREAMING_DELAY_MS = 240
# Exceed the documented default 3s endpoint timeout. Padding is never user usage.
FLUSH_SILENCE_BYTES = 32000 * 7 // 2


class VoxtralVoiceSession:
    model = VOXTRAL_VOICE_MODEL
    capabilities = LiveVoiceCapabilities()

    def __init__(self, key: str) -> None:
        self._key = key
        self._http: aiohttp.ClientSession | None = None
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._unflushed_audio = False

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
        except BaseException:
            await self.close()
            raise

    async def send_audio(self, encoded_pcm: str) -> None:
        if self._socket is None:
            raise RuntimeError("Voice transcription unavailable")
        async with self._send_lock:
            await self._socket.send_json({"type": "input_audio.append", "audio": encoded_pcm})
            self._unflushed_audio = True

    async def end_audio(self) -> None:
        """Flush a muted microphone without ending the continuous STT session."""
        if self._socket is None:
            raise RuntimeError("Voice transcription unavailable")
        async with self._send_lock:
            if self._unflushed_audio:
                await self._socket.send_json({"type": "input_audio.append", "audio":
                    base64.b64encode(bytes(FLUSH_SILENCE_BYTES)).decode("ascii")})
                self._unflushed_audio = False

    async def receive(self) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("Voice transcription unavailable")
        message = await self._socket.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Voice transcription disconnected")
        event = json.loads(message.data)
        if not isinstance(event, dict) or event.get("type") == "error":
            raise RuntimeError("Voice transcription failed")
        return event

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._key = ""
