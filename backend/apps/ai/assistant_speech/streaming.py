# backend/apps/ai/assistant_speech/streaming.py
#
# Dispatch immutable paragraph snapshots alongside authoritative text events.
# Speech tasks are intentionally detached from the text stream so provider work
# cannot delay, mutate, or fail normal assistant text persistence.
# Only content-free, safe status events are yielded for dispatch failures.

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from backend.apps.ai.assistant_speech.projection import project_streaming_speech_segment
from backend.shared.python_utils.generated_assets.service import _token_secret

DispatchSpeech = Callable[[dict[str, object]], Awaitable[None]]
InvalidateSpeech = Callable[[dict[str, object]], Awaitable[None]]
ReportSpeechStatus = Callable[[dict[str, object]], Awaitable[None]]
FinalizeSpeech = Callable[[dict[str, object]], Awaitable[None]]
SAFE_DISPATCH_ERROR = "Speech is temporarily unavailable."
MAX_AUTOMATIC_PARAGRAPH_LENGTH = 2_000
logger = logging.getLogger(__name__)


class ImmutableSpeechBoundaryTracker:
    """Detach one stable speech task per cumulative assistant-text boundary."""

    def __init__(
        self,
        *,
        metadata: dict[str, object],
        dispatch_speech: DispatchSpeech,
        invalidate_speech: InvalidateSpeech | None = None,
        report_status: ReportSpeechStatus | None = None,
        finalize_speech: FinalizeSpeech | None = None,
        enabled: bool = True,
        sequence_offset: int = 0,
    ) -> None:
        self._metadata = dict(metadata)
        self._dispatch_speech = dispatch_speech
        self._invalidate_speech = invalidate_speech
        self._report_status = report_status
        self._finalize_speech = finalize_speech
        self._enabled = enabled
        self._sequence_offset = sequence_offset
        self._dispatched: dict[int, dict[str, object]] = {}
        self._pending_tasks: list[asyncio.Task[None]] = []
        self._last_scheduled_task: asyncio.Task[None] | None = None

    def has_new_boundary(self, content: str) -> bool:
        """Return whether observing this snapshot will dispatch immutable speech."""
        paragraphs = [
            chunk
            for paragraph in _complete_paragraphs(content)
            for chunk in _split_automatic_paragraph(paragraph)
        ]
        for index, paragraph in enumerate(paragraphs):
            sequence = index + self._sequence_offset
            segment = self._segment(sequence, paragraph)
            previous = self._dispatched.get(sequence)
            if segment and (not previous or previous["source_hash"] != segment["source_hash"]):
                return True
        return False

    def observe(self, content: str, *, is_final: bool = False) -> None:
        """Schedule only immutable paragraph snapshots without awaiting speech work."""
        if not self._enabled:
            return
        paragraphs = _complete_paragraphs(content)
        if is_final:
            remainder = _final_paragraph(content, paragraphs)
            if remainder:
                paragraphs.append(remainder)

        bounded_paragraphs = [
            chunk
            for paragraph in paragraphs
            for chunk in _split_automatic_paragraph(paragraph)
        ]
        for index, paragraph in enumerate(bounded_paragraphs):
            sequence = index + self._sequence_offset
            segment = self._segment(sequence, paragraph)
            if not segment:
                continue
            previous = self._dispatched.get(sequence)
            if previous and previous["source_hash"] == segment["source_hash"]:
                continue
            if previous and self._invalidate_speech is not None:
                self._schedule(self._invalidate_speech(previous), sequence)
                segment["replaces_segment_id"] = previous["segment_id"]
            self._dispatched[sequence] = segment
            self._schedule(self._dispatch_speech(segment), sequence)

        if is_final:
            for sequence in tuple(self._dispatched):
                if sequence < len(bounded_paragraphs) + self._sequence_offset:
                    continue
                previous = self._dispatched.pop(sequence)
                if self._invalidate_speech is not None:
                    self._schedule(self._invalidate_speech(previous), sequence)
            if self._finalize_speech is not None:
                task = asyncio.create_task(self._finalize_after_dispatch())
                task.add_done_callback(lambda completed: _consume_detached_exception(completed, -1, self._report_status))

    def dispatch_projected_segment(self, *, sequence: int, kind: str, speakable_text: str) -> None:
        """Schedule one deterministic non-prose segment without blocking text."""
        if not self._enabled:
            return
        segment = self._segment(sequence, speakable_text, kind=kind)
        if not segment:
            return
        self._dispatched[sequence] = segment
        self._schedule(self._dispatch_speech(segment), sequence)

    def _segment(self, sequence: int, text: str, *, kind: str | None = None) -> dict[str, object]:
        if kind is None:
            projected = project_streaming_speech_segment(text)
            if projected is None:
                return {}
            kind, speakable_text = projected
        else:
            speakable_text = text.strip()
            if not speakable_text:
                return {}
        source_hash = _speech_source_identity(speakable_text)
        source_version = int(self._metadata["source_version"])
        chat_id = str(self._metadata["chat_id"])
        assistant_message_id = str(self._metadata["assistant_message_id"])
        segment_id = hashlib.sha256(
            f"{chat_id}:{assistant_message_id}:{source_version}:{sequence}:{source_hash}".encode("utf-8"),
        ).hexdigest()
        return {
            **self._metadata,
            "segment_id": segment_id,
            "sequence": sequence,
            "kind": kind,
            "playback_class": "passive_prelude" if kind == "app_use_announcement" else "replayable_response_track",
            "source_hash": source_hash,
            "speakable_text": speakable_text,
        }

    def _schedule(self, coroutine: Awaitable[None], sequence: int) -> None:
        previous = self._last_scheduled_task

        async def run_in_order() -> None:
            if previous is not None:
                try:
                    await previous
                except Exception:
                    pass
            await coroutine

        task = asyncio.create_task(run_in_order())
        self._last_scheduled_task = task
        self._pending_tasks.append(task)
        task.add_done_callback(lambda completed: _consume_detached_exception(completed, sequence, self._report_status))

    async def _finalize_after_dispatch(self) -> None:
        await asyncio.gather(*tuple(self._pending_tasks), return_exceptions=True)
        await self._finalize_speech({
            **self._metadata,
            "segment_ids": [segment["segment_id"] for segment in self._dispatched.values()],
        })


def _consume_detached_exception(
    task: asyncio.Task[None],
    sequence: int,
    report_status: ReportSpeechStatus | None,
) -> None:
    """Retrieve detached speech failures so they cannot affect text streaming."""
    try:
        task.result()
    except Exception:
        # Do not include the exception: dependencies can include transient text
        # in their errors, and this work must never alter the text stream.
        logger.warning("Detached assistant speech dispatch failed")
        if report_status is not None:
            follow_up = asyncio.create_task(report_status(_error_status(sequence)))
            follow_up.add_done_callback(lambda completed: _consume_status_exception(completed))


def _consume_status_exception(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception:
        logger.warning("Assistant speech status delivery failed")


def _speech_source_identity(speakable_text: str) -> str:
    """Return a server-secret identity for transient source text."""
    return hmac.new(_token_secret(), speakable_text.encode("utf-8"), hashlib.sha256).hexdigest()


async def stream_text_with_speech_dispatch(
    text_events: AsyncIterator[dict[str, object]],
    *,
    dispatch_speech: DispatchSpeech,
) -> AsyncIterator[dict[str, object]]:
    """Yield text unchanged while independently dispatching completed paragraphs."""
    dispatched_count = 0
    tasks: list[tuple[int, asyncio.Task[None]]] = []

    async for event in text_events:
        content = event.get("content")
        if isinstance(content, str):
            complete_paragraphs = _complete_paragraphs(content)
            for paragraph in complete_paragraphs[dispatched_count:]:
                sequence = dispatched_count
                dispatched_count += 1
                segment = _segment(sequence, paragraph)
                if segment:
                    tasks.append((sequence, asyncio.create_task(dispatch_speech(segment))))

            if event.get("type") == "final":
                # A final single paragraph has no earlier boundary to freeze. Once
                # boundaries exist, leave the trailing mutable snapshot to the
                # stream integration that owns final message revision semantics.
                remaining = _final_paragraph(content, complete_paragraphs)
                if remaining and not complete_paragraphs:
                    sequence = dispatched_count
                    dispatched_count += 1
                    segment = _segment(sequence, remaining)
                    if segment:
                        tasks.append((sequence, asyncio.create_task(dispatch_speech(segment))))
                async for status in _completed_statuses(tasks, wait=True):
                    yield status
                tasks.clear()
            else:
                async for status in _completed_statuses(tasks, wait=False):
                    yield status

        yield event


def _complete_paragraphs(content: str) -> list[str]:
    return [paragraph.strip() for paragraph in content.split("\n\n")[:-1] if paragraph.strip()]


def _final_paragraph(content: str, complete_paragraphs: list[str]) -> str:
    consumed = "\n\n".join(complete_paragraphs)
    remainder = content[len(consumed) :].lstrip("\n") if consumed else content
    return remainder.strip()


def _split_automatic_paragraph(paragraph: str) -> list[str]:
    """Split at whitespace, with a deterministic hard split for one long token."""
    if len(paragraph) <= MAX_AUTOMATIC_PARAGRAPH_LENGTH:
        return [paragraph]
    chunks: list[str] = []
    remainder = paragraph
    while len(remainder) > MAX_AUTOMATIC_PARAGRAPH_LENGTH:
        boundary = remainder.rfind(" ", 0, MAX_AUTOMATIC_PARAGRAPH_LENGTH + 1)
        if boundary <= 0:
            boundary = MAX_AUTOMATIC_PARAGRAPH_LENGTH
        chunks.append(remainder[:boundary].strip())
        remainder = remainder[boundary:].lstrip()
    if remainder:
        chunks.append(remainder)
    return chunks


def _segment(sequence: int, text: str) -> dict[str, object]:
    projected = project_streaming_speech_segment(text)
    if projected is None:
        return {}
    kind, speakable_text = projected
    return {"sequence": sequence, "kind": kind, "speakable_text": speakable_text}


async def _completed_statuses(
    tasks: list[tuple[int, asyncio.Task[None]]],
    *,
    wait: bool,
) -> AsyncIterator[dict[str, object]]:
    remaining: list[tuple[int, asyncio.Task[None]]] = []
    for sequence, task in tasks:
        if wait:
            try:
                await task
            except Exception:
                yield _error_status(sequence)
        elif task.done():
            try:
                task.result()
            except Exception:
                yield _error_status(sequence)
        else:
            remaining.append((sequence, task))
    tasks[:] = remaining


def _error_status(sequence: int) -> dict[str, object]:
    return {
        "type": "assistant_speech_status",
        "status": "error",
        "sequence": sequence,
        "error": SAFE_DISPATCH_ERROR,
    }
