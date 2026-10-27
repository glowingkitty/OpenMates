"""Mistral speech HTTP boundary. No chat, billing or persistence dependencies."""
from __future__ import annotations

import base64
import binascii
from collections.abc import AsyncIterator
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

MISTRAL_SPEECH_MODEL = "voxtral-mini-tts-3-0"
MISTRAL_SECRET_PATH = "kv/data/providers/mistral_ai"
MISTRAL_SPEECH_URL = "https://api.mistral.ai/v1/audio/speech"
MAX_SPEECH_EVENT_BYTES = 2 * 1024 * 1024
MAX_SPEECH_AUDIO_BYTES = 32 * 1024 * 1024
MAX_SPEECH_STREAM_BYTES = 48 * 1024 * 1024
SPEECH_PARSE_CHUNK_BYTES = 8192


async def _speech_events(response: httpx.Response) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Read SSE incrementally; bound unfinished lines, events and total wire bytes."""
    pending = b""
    event_name = ""
    data: list[str] = []
    event_bytes = wire_bytes = 0
    skip_lf = False
    async for chunk in response.aiter_bytes():
        wire_bytes += len(chunk)
        if wire_bytes > MAX_SPEECH_STREAM_BYTES:
            raise ValueError("Speech stream too large")
        # Avoid aiter_lines' unbounded unfinished-line buffer, without waiting
        # for an arbitrary network chunk size before delivering first audio.
        for offset in range(0, len(chunk), SPEECH_PARSE_CHUNK_BYTES):
            part = chunk[offset:offset + SPEECH_PARSE_CHUNK_BYTES]
            if skip_lf:
                part = part.removeprefix(b"\n")
                skip_lf = False
            pending += part
            while True:
                cr, lf = pending.find(b"\r"), pending.find(b"\n")
                newline = cr if cr >= 0 and (lf < 0 or cr < lf) else lf
                if newline < 0:
                    break
                raw, delimiter, pending = pending[:newline], pending[newline:newline + 1], pending[newline + 1:]
                if delimiter == b"\r":
                    if not pending:
                        skip_lf = True
                    pending = pending.removeprefix(b"\n")
                event_bytes += len(raw) + 1
                if event_bytes > MAX_SPEECH_EVENT_BYTES:
                    raise ValueError("Speech event too large")
                line = raw.decode("utf-8")
                if not line:
                    if data:
                        payload = json.loads("\n".join(data))
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid speech event")
                        name = event_name or payload.get("type")
                        if not isinstance(name, str) or payload.get("type", name) != name:
                            raise ValueError("Invalid speech event type")
                        yield name, payload
                    elif event_name:
                        raise ValueError("Missing speech event data")
                    event_name, data, event_bytes = "", [], 0
                elif not line.startswith(":"):
                    field, _, value = line.partition(":")
                    value = value.removeprefix(" ")
                    if field == "event":
                        event_name = value
                    elif field == "data":
                        data.append(value)
            if event_bytes + len(pending) > MAX_SPEECH_EVENT_BYTES:
                raise ValueError("Speech event too large")
    if pending or data or event_name:
        raise ValueError("Incomplete speech event")


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

    async def stream_text_to_speech(self, *, text: str, voice_id: str,
                                    model: str = MISTRAL_SPEECH_MODEL) -> AsyncIterator[bytes]:
        """Yield ordered MP3 bytes from one complete-text request, without retries.

        Exhaustion confirms provider completion; partial bytes must not be saved
        as a completed asset if iteration raises. Use ``contextlib.aclosing``
        when stopping early to release HTTP immediately. The initial MP3 magic
        may span deltas; only that bounded prefix is buffered before yielding.
        Contract: https://docs.mistral.ai/studio/audio/text-to-speech/stream-speech
        """
        if not text.strip() or not voice_id:
            raise ValueError("Speech requires text and a configured voice")
        key = self.api_key
        if not key and self.secrets_manager:
            key = await self.secrets_manager.get_secret(MISTRAL_SECRET_PATH, "api_key")
        key = key or os.getenv("SECRET__MISTRAL_AI__API_KEY") or os.getenv("SECRET__MISTRAL__API_KEY")
        if not key or key == "IMPORTED_TO_VAULT":
            raise RuntimeError("Mistral speech is unavailable")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", MISTRAL_SPEECH_URL,
                    headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
                    json={"model": model, "input": text, "voice_id": voice_id,
                          "response_format": "mp3", "stream": True}) as response:
                    response.raise_for_status()
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                        raise ValueError("Invalid speech stream content type")
                    total = 0
                    prefix = b""
                    validated = False
                    async for event, payload in _speech_events(response):
                        if event == "speech.audio.done":
                            if not validated:
                                raise ValueError("Empty or incomplete speech audio")
                            return
                        if event != "speech.audio.delta":
                            raise ValueError("Unexpected speech event")
                        audio = base64.b64decode(payload["audio_data"], validate=True)
                        if not audio:
                            raise ValueError("Empty speech delta")
                        total += len(audio)
                        if total > MAX_SPEECH_AUDIO_BYTES:
                            raise ValueError("Speech audio too large")
                        if not validated:
                            prefix += audio
                            if len(prefix) < 3:
                                continue
                            # ID3 metadata or an MPEG Layer III frame header.
                            mp3_frame = (prefix[0] == 0xff and prefix[1] & 0xe0 == 0xe0
                                and prefix[1] & 0x18 != 0x08 and prefix[1] & 0x06 == 0x02
                                and prefix[2] & 0xf0 != 0xf0 and prefix[2] & 0x0c != 0x0c)
                            if not (prefix.startswith(b"ID3") or mp3_frame):
                                raise ValueError("Invalid MP3 response")
                            audio, prefix, validated = prefix, b"", True
                        yield audio
                    raise ValueError("Missing speech completion")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, binascii.Error, TimeoutError, RecursionError):
            raise RuntimeError("Mistral speech generation failed") from None

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
