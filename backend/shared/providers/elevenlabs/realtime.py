"""Single-turn Eleven v4 Turbo incremental text/audio transport.

Pure provider mechanics: callers own prose authorization, call leases, admission,
billing and publication. Audio is yielded, never accumulated or persisted. MP3
turn markers aren't independent file boundaries (the provider encoder can bleed).
See docs/apis/elevenlabs-realtime-call-speech.md for the supported wire contract.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import suppress
from dataclasses import dataclass, field
import json
import math
import os
import re
from time import monotonic
from typing import AsyncIterator, TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

ELEVENLABS_REALTIME_MODEL = "eleven_v4_turbo"
ELEVENLABS_REALTIME_URL = (
    "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
    "?model_id=eleven_v4_turbo&output_format=mp3_44100_128&sync_alignment=true"
)
MAX_EVENT_BYTES = 1024 * 1024
MAX_AUDIO_CHUNK_BYTES = 512 * 1024
MAX_ALIGNMENT_CHARACTERS = 4096


class ElevenLabsRealtimeError(RuntimeError):
    """Content-free failure category; never retains upstream exceptions/bodies."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("ElevenLabs realtime speech failed: " + code)


@dataclass(frozen=True)
class ElevenLabsRealtimeAlignment:
    chars: tuple[str, ...] = field(repr=False)
    char_start_times_ms: tuple[float, ...]
    char_durations_ms: tuple[float, ...]
    # Do not claim global/chunk-relative offsets until a real-provider proof.
    timebase: str = "provider_unspecified"


@dataclass(frozen=True)
class ElevenLabsRealtimeEvent:
    audio_bytes: bytes = field(default=b"", repr=False)
    alignment: ElevenLabsRealtimeAlignment | None = None
    final_for_turn: bool = False
    final: bool = False


def _alignment(value: object) -> ElevenLabsRealtimeAlignment | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ElevenLabsRealtimeError("invalid_alignment")
    chars = value.get("chars")
    starts, durations = value.get("char_start_times_ms"), value.get("char_durations_ms")
    if (not isinstance(chars, list) or not 0 < len(chars) <= MAX_ALIGNMENT_CHARACTERS
            or not all(isinstance(char, str) and 0 < len(char) <= 8 for char in chars)
            or not isinstance(starts, list) or not isinstance(durations, list)
            or len(starts) != len(chars) or len(durations) != len(chars)):
        raise ElevenLabsRealtimeError("invalid_alignment")
    if not all(type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 3600000
               for number in starts + durations):
        raise ElevenLabsRealtimeError("invalid_alignment")
    if any(left > right for left, right in zip(starts, starts[1:])):
        raise ElevenLabsRealtimeError("invalid_alignment")
    return ElevenLabsRealtimeAlignment(tuple(chars), tuple(starts), tuple(durations))


class ElevenLabsRealtimeSession:
    """One transport/voice per assistant turn; one concurrent reader plus writer.

    ``finish_input`` sends a draining close_socket. ``cancel`` only closes the
    transport. Neither failure nor cancellation reconnects/retries paid input.
    Counts include exact successfully sent text (no trimming or normalization).
    """

    model = ELEVENLABS_REALTIME_MODEL
    mime_type = "audio/mpeg"

    def __init__(self, *, voice_id: str, api_key: str | None = None,
                 secrets_manager: SecretsManager | None = None,
                 connect_timeout_seconds: float = 10, send_timeout_seconds: float = 10,
                 receive_timeout_seconds: float = 30, keepalive_seconds: float = 10,
                 max_session_seconds: float = 300, max_input_characters: int = 20000,
                 max_input_count: int = 1024, max_audio_bytes: int = 20 * 1024 * 1024) -> None:
        if (not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice_id)
                or not all(type(number) in (int, float) and math.isfinite(number) and number > 0
                           for number in (connect_timeout_seconds, send_timeout_seconds, receive_timeout_seconds,
                                          keepalive_seconds, max_session_seconds))
                or keepalive_seconds >= 20
                or not all(type(number) is int and number > 0 for number in
                           (max_input_characters, max_input_count, max_audio_bytes))):
            raise ElevenLabsRealtimeError("invalid_configuration")
        self._voice_id, self._api_key, self._secrets_manager = voice_id, api_key, secrets_manager
        self._connect_timeout, self._send_timeout = connect_timeout_seconds, send_timeout_seconds
        self._receive_timeout, self._keepalive_seconds = receive_timeout_seconds, keepalive_seconds
        self._max_session_seconds = max_session_seconds
        self._max_characters, self._max_inputs, self._max_audio = max_input_characters, max_input_count, max_audio_bytes
        self._http: aiohttp.ClientSession | None = None
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._open_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._reading = False
        self._state = "new"
        self._failure: str | None = None
        self.last_event_shape: dict[str, object] | None = None
        self._started = self._last_sent = 0.0
        self.submitted_characters = self.input_count = self.audio_bytes_received = 0

    async def _credentials(self) -> str:
        # Same Vault-first source as ElevenLabsClient, with safe exception handling.
        key = self._api_key
        if not key and self._secrets_manager is not None:
            try:
                key = await self._secrets_manager.get_secret(
                    secret_path="kv/data/providers/elevenlabs", secret_key="api_key")
            except Exception:
                pass
        key = key or os.getenv("SECRET__ELEVENLABS__API_KEY")
        if not isinstance(key, str) or not key.strip() or key == "IMPORTED_TO_VAULT":
            raise ElevenLabsRealtimeError("credentials_unavailable")
        return key

    async def open(self) -> None:
        if self._state != "new":
            raise ElevenLabsRealtimeError("invalid_state")
        self._state = "opening"
        self._open_task = asyncio.current_task()
        try:
            key = await self._credentials()
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
            self._socket = await asyncio.wait_for(self._http.ws_connect(
                ELEVENLABS_REALTIME_URL, headers={"xi-api-key": key},
                max_msg_size=MAX_EVENT_BYTES, autoclose=True), self._connect_timeout)
            self._started = monotonic()
            self._state = "open"
            async with self._send_lock:
                await self._send({"voices": [self._voice_id]})
            self._keepalive_task = asyncio.create_task(self._keepalive())
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except ElevenLabsRealtimeError:
            await self._fail("handshake_failed")
            raise
        except Exception:
            await self._fail("handshake_failed")
            raise ElevenLabsRealtimeError("handshake_failed") from None
        finally:
            self._api_key = None
            self._open_task = None

    def _require_open(self) -> None:
        if self._failure:
            raise ElevenLabsRealtimeError(self._failure)
        if self._state != "open" or self._socket is None:
            raise ElevenLabsRealtimeError("invalid_state")
        if monotonic() - self._started >= self._max_session_seconds:
            raise ElevenLabsRealtimeError("session_timeout")

    async def _send(self, payload: dict) -> None:
        try:
            if self._socket is None:
                raise ElevenLabsRealtimeError("invalid_state")
            await asyncio.wait_for(self._socket.send_json(payload), self._send_timeout)
            self._last_sent = monotonic()
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception:
            await self._fail("send_failed")
            raise ElevenLabsRealtimeError("send_failed") from None

    async def append_text(self, text: str, *, new_turn: bool = False) -> None:
        # A single assistant response is one continuous track. Do not let provider
        # prosody turns masquerade as exact independent MP3 clause boundaries.
        if not isinstance(text, str) or not text.strip() or new_turn is not False:
            raise ElevenLabsRealtimeError("invalid_input")
        async with self._send_lock:
            self._require_open()
            if self.submitted_characters + len(text) > self._max_characters or self.input_count >= self._max_inputs:
                raise ElevenLabsRealtimeError("input_limit")
            await self._send({"inputs": [{"text": text, "voice_id": self._voice_id, "new_turn": False}]})
            self.submitted_characters += len(text)
            self.input_count += 1

    async def flush(self) -> None:
        async with self._send_lock:
            self._require_open()
            await self._send({"flush": True})

    async def finish_input(self) -> None:
        async with self._send_lock:
            self._require_open()
            self._state = "draining"
            await self._send({"close_socket": True})

    async def _keepalive(self) -> None:
        try:
            while self._state == "open":
                await asyncio.sleep(self._keepalive_seconds)
                async with self._send_lock:
                    if self._state != "open":
                        return
                    self._require_open()
                    if monotonic() - self._last_sent >= self._keepalive_seconds:
                        await self._send({"keep_alive": True})
        except asyncio.CancelledError:
            return
        except Exception:
            await self._fail("keepalive_failed")

    def _normalize(self, raw: object) -> ElevenLabsRealtimeEvent:
        self.last_event_shape = {"wire_type": "text" if isinstance(raw, str) else "non_text"}
        if isinstance(raw, str):
            self.last_event_shape["wire_characters"] = len(raw)
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ElevenLabsRealtimeError("invalid_event")
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise ElevenLabsRealtimeError("invalid_event") from None
        if not isinstance(value, dict):
            raise ElevenLabsRealtimeError("invalid_event")
        # Diagnostic field names are an allowlist, never provider-controlled keys.
        # Record types/counts only, including for error/message fields: no values.
        fields = ("audio", "alignment", "is_final", "is_final_audio_for_turn", "error", "error_message", "message", "code", "detail")
        def shape(item: object) -> dict[str, object]:
            kind = ("null" if item is None else "boolean" if type(item) is bool else "string" if isinstance(item, str)
                    else "array" if isinstance(item, list) else "object" if isinstance(item, dict) else "number")
            result: dict[str, object] = {"type": kind}
            if isinstance(item, (str, list, dict)):
                result["length"] = len(item)
            return result
        self.last_event_shape["fields"] = {key: shape(value[key]) for key in fields if key in value}
        self.last_event_shape["unknown_field_count"] = sum(key not in fields for key in value)
        if isinstance(value.get("alignment"), dict):
            alignment_fields = value["alignment"]
            self.last_event_shape["alignment_fields"] = {
                key: shape(alignment_fields[key]) for key in ("chars", "char_start_times_ms", "char_durations_ms")
                if key in alignment_fields}
        if any(value.get(key) is not None for key in ("error", "error_message")):
            raise ElevenLabsRealtimeError("provider_error")
        for flag in ("is_final", "is_final_audio_for_turn"):
            if flag in value and type(value[flag]) is not bool:
                raise ElevenLabsRealtimeError("invalid_event")
        final, final_for_turn = value.get("is_final", False), value.get("is_final_audio_for_turn", False)
        audio = b""
        # Real v4 emits {"audio":""} between chunks and during drain. It is
        # a bounded no-op, never generated bytes or evidence of completion.
        noop_fields = {"audio", "alignment", "is_final", "is_final_audio_for_turn", "error", "error_message"}
        empty_audio_noop = (value.get("audio") == "" and not final and not final_for_turn
                            and value.get("alignment") is None and set(value) <= noop_fields)
        terminal_empty_audio = (final or final_for_turn) and value.get("audio") in (None, "")
        if "audio" in value and not terminal_empty_audio and not empty_audio_noop:
            encoded = value["audio"]
            if not isinstance(encoded, str) or not encoded or len(encoded) > (MAX_AUDIO_CHUNK_BYTES + 2) // 3 * 4:
                raise ElevenLabsRealtimeError("audio_limit")
            try:
                audio = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise ElevenLabsRealtimeError("invalid_audio") from None
            if not audio or len(audio) > MAX_AUDIO_CHUNK_BYTES or self.audio_bytes_received + len(audio) > self._max_audio:
                raise ElevenLabsRealtimeError("audio_limit")
            self.audio_bytes_received += len(audio)
        alignment = _alignment(value.get("alignment"))
        if not audio and not final and not final_for_turn and alignment is None and not empty_audio_noop:
            raise ElevenLabsRealtimeError("invalid_event")
        if final and (self._state != "draining" or not self.audio_bytes_received or not self.input_count):
            raise ElevenLabsRealtimeError("unexpected_final")
        return ElevenLabsRealtimeEvent(audio, alignment, final_for_turn, final)

    async def receive(self) -> ElevenLabsRealtimeEvent:
        if self._reading:
            raise ElevenLabsRealtimeError("concurrent_receive")
        if self._failure:
            raise ElevenLabsRealtimeError(self._failure)
        if self._state not in ("open", "draining") or self._socket is None:
            raise ElevenLabsRealtimeError("invalid_state")
        self._reading = True
        try:
            remaining = self._max_session_seconds - (monotonic() - self._started)
            if remaining <= 0:
                raise ElevenLabsRealtimeError("session_timeout")
            message = await asyncio.wait_for(self._socket.receive(), min(self._receive_timeout, remaining))
            if monotonic() - self._started >= self._max_session_seconds:
                raise ElevenLabsRealtimeError("session_timeout")
            if self._failure:
                raise ElevenLabsRealtimeError(self._failure)
            if self._state == "cancelled":
                raise ElevenLabsRealtimeError("cancelled")
            if message.type != aiohttp.WSMsgType.TEXT:
                self.last_event_shape = {"wire_type": "binary" if message.type == aiohttp.WSMsgType.BINARY else "closed_or_error"}
                raise ElevenLabsRealtimeError("truncated_stream")
            event = self._normalize(message.data)
            if event.final:
                self._state = "final"
                await self._close()
            return event
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except ElevenLabsRealtimeError as error:
            await self._fail(error.code)
            raise
        except asyncio.TimeoutError:
            await self._fail("receive_timeout")
            raise ElevenLabsRealtimeError("receive_timeout") from None
        except Exception:
            await self._fail("transport_failed")
            raise ElevenLabsRealtimeError("transport_failed") from None
        finally:
            self._reading = False

    async def audio_events(self) -> AsyncIterator[ElevenLabsRealtimeEvent]:
        try:
            while True:
                event = await self.receive()
                yield event
                if event.final:
                    return
        finally:
            if self._state != "final":
                await self.cancel()

    async def _fail(self, code: str) -> None:
        self._failure = self._failure or code
        self._state = "failed"
        await self._close()

    async def _close(self) -> None:
        task, self._keepalive_task = self._keepalive_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        socket, self._socket = self._socket, None
        http, self._http = self._http, None
        for resource in (socket, http):
            if resource is not None:
                with suppress(Exception):
                    await asyncio.wait_for(resource.close(), 2)
        self._api_key = None

    async def cancel(self) -> None:
        """Abort without flush or close_socket. Safe for repeated caller cleanup."""
        if self._state != "final":
            self._state = "cancelled"
        opening = self._open_task
        if opening is not None and opening is not asyncio.current_task():
            opening.cancel()
            with suppress(asyncio.CancelledError):
                await opening
        await self._close()
