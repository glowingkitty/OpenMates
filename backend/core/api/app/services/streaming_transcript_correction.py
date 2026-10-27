"""Correct bounded dictation batches while audio keeps streaming, in memory only."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)
CORRECTION_INTERVAL_SECONDS = 15.0
CORRECTION_BATCH_CHARACTERS = 800
CORRECTION_TIMEOUT_SECONDS = 35.0

Correction = Callable[[str, str | None], Awaitable[dict[str, str]]]
Progress = Callable[[int], Awaitable[None]]


def correction_batch_end(text: str) -> int:
    """Prefer paragraphs, then complete sentences, then word boundaries."""
    window = text[:CORRECTION_BATCH_CHARACTERS]
    paragraphs = list(re.finditer(r"\n[ \t]*\n", window))
    sentences = list(re.finditer(r"[.!?。！？][\"'”’)]*(?:\s+|$)", window))
    boundaries = paragraphs or sentences
    if boundaries:
        return boundaries[-1].end()
    words = list(re.finditer(r"\s+", window))
    return words[-1].end() if words else len(window)


class StreamingTranscriptCorrection:
    """Serialize correction work without blocking the audio/WebSocket receiver.

    A failed batch retains its raw text. Only the unprocessed suffix is sent on
    finish; completed batches are never submitted to the provider again.
    """

    def __init__(self, correct: Correction, on_progress: Progress) -> None:
        self._correct = correct
        self._on_progress = on_progress
        self._raw = ""
        self._offset = 0
        self._parts: list[str] = []
        self._result: dict[str, str] | None = None
        self._language: str | None = None
        self._models: list[str] = []
        self._changed = asyncio.Event()
        self._pending_since = asyncio.get_running_loop().time()
        self._finishing = False
        self._task: asyncio.Task[None] | None = None

    def append(self, delta: str, language: str | None = None) -> None:
        """Notify the worker of new transcript text without awaiting a provider."""
        if not self._raw:
            delta = delta.lstrip()
        if not delta:
            return
        if self._offset == len(self._raw):
            self._pending_since = asyncio.get_running_loop().time()
        self._raw += delta
        if language:
            self._language = language
        self._changed.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def finish(self, transcript: str, language: str | None) -> dict[str, str]:
        """Finish pending batches and combine them with already corrected text."""
        # The provider may extend the last delta in its final event. The route
        # preserves the streamed prefix; normalize outer whitespace consistently.
        transcript = transcript.strip()
        if not transcript.startswith(self._raw.rstrip()):
            raise ValueError("Final transcript changed the streamed prefix")
        self._raw = transcript
        self._offset = min(self._offset, len(transcript))
        self._language = language or self._language
        self._finishing = True
        self._changed.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        await self._task
        if self._result is None:
            raise RuntimeError("No transcript batch could be corrected")
        return {
            **self._result,
            "transcript": "".join(self._parts).strip(),
            "correction_model": ", ".join(self._models),
        }

    async def cancel(self) -> None:
        """Cancel and observe any provider request when its recording goes away."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            self._changed.clear()
            pending = self._raw[self._offset :]
            if not pending:
                if self._finishing:
                    return
                await self._changed.wait()
                continue
            remaining = (
                self._pending_since
                + CORRECTION_INTERVAL_SECONDS
                - asyncio.get_running_loop().time()
            )
            if (
                not self._finishing
                and len(pending) < CORRECTION_BATCH_CHARACTERS
                and remaining > 0
            ):
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
                continue
            end = (
                len(pending)
                if self._finishing and len(pending) <= CORRECTION_BATCH_CHARACTERS
                else correction_batch_end(pending)
            )
            batch = pending[:end]
            raw = batch.strip()
            separator = "\n\n" if re.search(r"\n[ \t]*\n[ \t]*$", batch) else " "
            self._offset += end
            # New text arriving while this request is in flight starts the next
            # interval; a large backlog is drained immediately, one call at a time.
            self._pending_since = asyncio.get_running_loop().time()
            if not raw:
                continue
            try:
                async with asyncio.timeout(CORRECTION_TIMEOUT_SECONDS):
                    result = await self._correct(raw, self._language)
                corrected = result["transcript"].strip()
                if not corrected:
                    raise ValueError("Transcript correction returned empty text")
            except Exception as exc:
                logger.warning(
                    "Streaming transcript batch correction failed: %s",
                    type(exc).__name__,
                )
                self._parts.append(raw + separator)
            else:
                self._parts.append(corrected + separator)
                model = result["correction_model"]
                if model not in self._models:
                    self._models.append(model)
                # The first successful batch supplies the compact recording title.
                if self._result is None:
                    self._result = result
                await self._on_progress(self._offset)
