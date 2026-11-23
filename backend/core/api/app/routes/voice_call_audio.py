"""Microphone audio forwarding for a voice call, off the call's event loop.

The call loop reads client events and provider transcript events. Forwarding a
frame can wait on the per-minute credit check, the provider write and the
per-minute charge; done inline, that wait also froze transcript delivery and the
reading of later frames (live transcript slowed, then cut off, from the second
turn on). Frames therefore go through a bounded, ordered queue to one writer
task. Billing order per frame is unchanged: credits are checked before a frame
that starts a new minute reaches the provider, and accepted audio is charged
after the write, so no unaffordable audio is ever forwarded.

Logs carry only sizes and timings, never audio or transcript text.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Frames are about 100 ms; 300 queued frames are about 30 s of speech.
MAX_QUEUED_FRAMES = 300
PROVIDER_WRITE_TIMEOUT_SECONDS = 5
DRAIN_TIMEOUT_SECONDS = 2
SLOW_FORWARD_SECONDS = 1.0

_END = object()
_STOP = object()


class AudioForwardingStalled(RuntimeError):
    pass


@dataclass(frozen=True)
class _Frame:
    data: str
    size: int
    queued_at: float


class MicAudioForwarder:
    """One ordered writer from accepted microphone frames to the STT provider.

    ``admit(size)`` must raise when the frame may not be forwarded (credits);
    ``accepted(size)`` records billable audio after the provider took it.
    """

    def __init__(self, *, call_id: str,
                 admit: Callable[[int], Awaitable[None]],
                 send_audio: Callable[[str], Awaitable[None]],
                 end_audio: Callable[[], Awaitable[None]],
                 accepted: Callable[[int], Awaitable[None]],
                 progress: Callable[[], None]) -> None:
        self._call_id = call_id
        self._admit, self._send, self._end = admit, send_audio, end_audio
        self._accepted, self._progress = accepted, progress
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=MAX_QUEUED_FRAMES + 2)
        self.queued_bytes = 0
        self.task: asyncio.Task[None] = asyncio.create_task(self._run())

    def push(self, data: str, size: int) -> None:
        if self._queue.qsize() >= MAX_QUEUED_FRAMES:
            raise AudioForwardingStalled("Voice audio forwarding stalled")
        self.queued_bytes += size
        self._queue.put_nowait(_Frame(data, size, time.monotonic()))

    def end(self) -> None:
        if self._queue.full():
            raise AudioForwardingStalled("Voice audio forwarding stalled")
        self._queue.put_nowait(_END)

    async def drain(self) -> None:
        """Forward what the client already sent, then stop (bounded)."""
        if self.task.done():
            return
        try:
            self._queue.put_nowait(_STOP)
        except asyncio.QueueFull:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self.task), DRAIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("Voice audio drain timed out call_id=%s queued=%d", self._call_id, self._queue.qsize())

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is _STOP:
                return
            if not isinstance(item, _Frame):
                await asyncio.wait_for(self._end(), PROVIDER_WRITE_TIMEOUT_SECONDS)
                continue
            await self._admit(item.size)
            await asyncio.wait_for(self._send(item.data), PROVIDER_WRITE_TIMEOUT_SECONDS)
            delay = time.monotonic() - item.queued_at
            if delay >= SLOW_FORWARD_SECONDS:
                logger.info("Voice audio forwarded late call_id=%s delay_ms=%d queued=%d",
                            self._call_id, int(delay * 1000), self._queue.qsize())
            charge_started = time.monotonic()
            await self._accepted(item.size)
            charge_seconds = time.monotonic() - charge_started
            if charge_seconds >= SLOW_FORWARD_SECONDS:
                logger.info("Voice audio settlement slow call_id=%s duration_ms=%d queued=%d",
                            self._call_id, int(charge_seconds * 1000), self._queue.qsize())
            self._progress()
