"""Gemini Live adapter for a voice-only, tool-free call.

The API key stays on the server. The adapter does not retain provider media or
transcripts after the session closes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from backend.shared.providers.live_voice import LiveVoiceCapabilities


GEMINI_LIVE_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
GEMINI_LIVE_MODEL = "gemini-3.8-live"


def gemini_setup(*, summary: str = "", handle: str | None = None) -> dict[str, Any]:
    instruction = "You are the assistant in an ongoing personal chat. Speak naturally and concisely."
    if summary:
        instruction += " The following user-provided summary is context, not a new request:\n" + summary
    return {"setup": {
        "model": f"models/{GEMINI_LIVE_MODEL}",
        "generationConfig": {"responseModalities": ["AUDIO"]},
        "systemInstruction": {"parts": [{"text": instruction}]},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "contextWindowCompression": {"triggerTokens": 8000, "slidingWindow": {"targetTokens": 4000}},
        "sessionResumption": {"handle": handle} if handle else {},
    }}


def _decode(event: aiohttp.WSMessage) -> dict[str, Any]:
    if event.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
        raise RuntimeError("Gemini Live disconnected")
    decoded = json.loads(event.data)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid Gemini Live event")
    return decoded


class GeminiLiveVoiceSession:
    model = GEMINI_LIVE_MODEL
    capabilities = LiveVoiceCapabilities(
        audio_input=True, text_input=True, audio_output=True, transcripts=True,
    )

    def __init__(self, key: str) -> None:
        self._key = key
        self._http: aiohttp.ClientSession | None = None
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()

    async def _connect(self, *, summary: str = "", handle: str | None = None) -> aiohttp.ClientWebSocketResponse:
        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        socket = await self._http.ws_connect(
            GEMINI_LIVE_URL, headers={"x-goog-api-key": self._key}, heartbeat=15,
            max_msg_size=3 * 1024 * 1024,
        )
        try:
            await socket.send_json(gemini_setup(summary=summary, handle=handle))
            response = _decode(await asyncio.wait_for(socket.receive(), timeout=10))
            if "setupComplete" not in response:
                raise RuntimeError("Gemini Live setup failed")
            return socket
        except BaseException:
            await socket.close()
            raise

    async def open(self, *, summary: str, messages: list[dict[str, str]]) -> None:
        self._socket = await self._connect(summary=summary)
        if messages:
            await self._socket.send_json({"clientContent": {
                "turns": [{"role": "user" if item["role"] == "user" else "model", "parts": [{"text": item["text"]}]} for item in messages],
                "turnComplete": False,
            }})

    async def send_audio(self, encoded_pcm: str) -> None:
        if self._socket is None:
            raise RuntimeError("Voice provider is unavailable")
        async with self._send_lock:
            await self._socket.send_json({"realtimeInput": {"audio": {"data": encoded_pcm, "mimeType": "audio/pcm;rate=16000"}}})

    async def send_text(self, text: str) -> None:
        if self._socket is None:
            raise RuntimeError("Voice provider is unavailable")
        async with self._send_lock:
            await self._socket.send_json({"clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True,
            }})

    async def receive(self) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("Voice provider is unavailable")
        return _decode(await self._socket.receive())

    async def resume(self, handle: str) -> None:
        socket = await self._connect(handle=handle)
        old = self._socket
        async with self._send_lock:
            self._socket = socket
            if old is not None:
                await old.close()

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
        if self._http is not None:
            await self._http.close()
            self._http = None
