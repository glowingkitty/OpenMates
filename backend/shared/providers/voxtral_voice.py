"""Voxtral realtime speech windows for a logical voice call.

The first-party call outlives its upstream streams. Each quiet window ends
provider input, drains remaining text, and leaves no idle PCM clock running.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
from typing import Any

import aiohttp

from backend.shared.providers.live_voice import LiveVoiceCapabilities
from backend.shared.providers.voice_websocket_proxy import isolated_voice_websocket_proxy

VOXTRAL_VOICE_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
VOXTRAL_VOICE_MODEL = "voxtral-mini-transcribe-realtime-3-0"
STREAMING_DELAY_MS = 240
# A new speech window can begin while the previous stream drains its last words.
MAX_CONCURRENT_WINDOWS = 3
STREAM_ACK_TIMEOUT = 4.0
STREAM_RECEIVE_TIMEOUT = 35.0
STREAM_CLOSE_TIMEOUT = 2.0
logger = logging.getLogger(__name__)


class VoxtralVoiceError(RuntimeError):
    """Provider failure with bounded diagnostics and no upstream payload text."""

    def __init__(self, provider_code: int | None = None) -> None:
        super().__init__("Voice transcription failed")
        self.provider_code = provider_code
        self.provider_category = "idle_timeout" if provider_code == 3804 else "provider_error"


@dataclass
class _SpeechWindow:
    socket: aiohttp.ClientWebSocketResponse
    finishing: bool = False
    last_input_frame: int = 0
    transcript: str = ""


class VoxtralVoiceSession:
    """Open a provider stream only on speech and keep its events in capture order."""

    model = VOXTRAL_VOICE_MODEL
    capabilities = LiveVoiceCapabilities()

    def __init__(self, key: str) -> None:
        self._key = key
        self._http: aiohttp.ClientSession | None = None
        self._send_lock = asyncio.Lock()
        self._windows: deque[_SpeechWindow] = deque()
        self._available = asyncio.Event()
        self._active: _SpeechWindow | None = None
        self._pending_final_frame: int | None = None
        self._sent_frames = 0
        self._retiring: deque[asyncio.Task[None]] = deque()
        self._context_bias: list[str] = []

    async def set_context_bias(self, terms: list[str]) -> None:
        """Keep caller terms in memory and apply them to the next speech window."""
        async with self._send_lock:
            self._context_bias = list(terms)

    async def open(self) -> None:
        """Prepare transport without opening a provider stream during silence."""
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=4))

    async def _open_window(self) -> _SpeechWindow:
        if self._http is None or len(self._windows) >= MAX_CONCURRENT_WINDOWS:
            raise RuntimeError("Voice transcription unavailable")
        socket = await self._http.ws_connect(
            f"{VOXTRAL_VOICE_URL}?model={self.model}",
            headers={"Authorization": f"Bearer {self._key}"}, heartbeat=20,
            max_msg_size=2 * 1024 * 1024, proxy=isolated_voice_websocket_proxy(),
        )
        try:
            if (await asyncio.wait_for(self._read(socket), STREAM_ACK_TIMEOUT))["type"] != "session.created":
                raise RuntimeError("Voice transcription session unavailable")
            settings: dict[str, Any] = {
                "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
                "target_streaming_delay_ms": STREAMING_DELAY_MS, "turn_detection": {},
            }
            if self._context_bias:
                settings["context_bias"] = self._context_bias
            await socket.send_json({"type": "session.update", "session": settings})
            if (await asyncio.wait_for(self._read(socket), STREAM_ACK_TIMEOUT))["type"] != "session.updated":
                raise RuntimeError("Voice transcription settings unavailable")
        except (RuntimeError, asyncio.CancelledError, aiohttp.ClientError, OSError, ValueError):
            await socket.close()
            raise
        window = _SpeechWindow(socket)
        self._windows.append(window)
        self._available.set()
        return window

    async def send_audio(self, encoded_pcm: str) -> None:
        """Write the next captured frame, opening a window if input has resumed."""
        async with self._send_lock:
            if self._active is None:
                self._active = await self._open_window()
            await self._active.socket.send_json({"type": "input_audio.append", "audio": encoded_pcm})
            self._sent_frames += 1
            self._active.last_input_frame = self._sent_frames

    async def end_audio(self) -> None:
        """Flush real audio, without adding synthetic PCM or ending the call."""
        async with self._send_lock:
            if self._active is None:
                return
            window = self._active
            window.finishing = True
            await window.socket.send_json({"type": "input_audio.end"})
            self._active = None

    @staticmethod
    async def _read(socket: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
        message = await socket.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Voice transcription disconnected")
        event = json.loads(message.data)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise RuntimeError("Voice transcription failed")
        if event["type"] == "error":
            details = event.get("error")
            code = details.get("code") if isinstance(details, dict) else None
            if type(code) is not int or not 0 <= code <= 999999:
                code = None
            error = VoxtralVoiceError(code)
            logger.warning("Voxtral transcription failed provider_code=%s category=%s",
                           error.provider_code, error.provider_category)
            raise error
        return event

    @staticmethod
    async def _close_window(window: _SpeechWindow) -> None:
        try:
            async with asyncio.timeout(STREAM_CLOSE_TIMEOUT):
                await window.socket.close()
        except TimeoutError:
            logger.info("Voxtral speech window close handshake timed out")

    async def _retire(self, window: _SpeechWindow) -> None:
        # Deliver the drained words without waiting for the network close.
        # Bound the number of closing sockets even when speech windows arrive
        # faster than the provider acknowledges their close handshakes.
        if len(self._retiring) >= MAX_CONCURRENT_WINDOWS:
            await asyncio.shield(self._retiring[0])
            self._retiring.popleft()
        async with self._send_lock:
            self._windows.popleft()
            if self._active is window:
                self._active = None
            if not self._windows:
                self._available.clear()
            self._retiring.append(asyncio.create_task(self._close_window(window)))

    async def receive(self) -> dict[str, Any]:
        """Return events in audio order, waiting locally between provider windows."""
        if self._pending_final_frame is not None:
            frame, self._pending_final_frame = self._pending_final_frame, None
            return {"type": "turn.end", "drained_input_frame": frame}
        await self._available.wait()
        window = self._windows[0]
        while True:
            try:
                event = await asyncio.wait_for(self._read(window.socket), STREAM_RECEIVE_TIMEOUT)
            except TimeoutError:
                # An inactive provider window can stop emitting without closing.
                # Retire it so the logical call can accept the next speech.
                logger.info("Voxtral speech window received no events before its deadline")
                await self._retire(window)
                return {"type": "turn.end"}
            except VoxtralVoiceError as error:
                if error.provider_category != "idle_timeout":
                    raise
                await self._retire(window)
                return {"type": "turn.end"}
            kind = event["type"]
            if kind == "session.updated":
                continue
            if kind == "transcription.text.delta" and isinstance(event.get("text"), str):
                window.transcript += event["text"]
            if kind == "transcription.done" and window.finishing:
                await self._retire(window)
                final = event.get("text")
                if isinstance(final, str) and final.startswith(window.transcript):
                    tail = final[len(window.transcript):]
                    if tail:
                        self._pending_final_frame = window.last_input_frame
                        return {"type": "transcription.text.delta", "text": tail}
                    return {"type": "turn.end", "drained_input_frame": window.last_input_frame}
                return {"type": "turn.end"}
            # Frame identities belong to the local audio writer.
            event.pop("drained_input_frame", None)
            return event

    async def close(self) -> None:
        """Release all upstream resources when the first-party call ends."""
        async with self._send_lock:
            windows = list(self._windows)
            self._windows.clear()
            self._active = None
            self._available.clear()
            http, self._http = self._http, None
            self._key = ""
            self._context_bias.clear()
            retiring, self._retiring = self._retiring, deque()
        try:
            await asyncio.gather(*retiring, *(self._close_window(window) for window in windows))
        finally:
            if http is not None:
                await http.close()
