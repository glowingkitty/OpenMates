# backend/shared/python_utils/stream_content_coalescer.py
#
# Bounded publisher for cumulative AI content snapshots.
# Ordinary snapshots may be replaced within a short window, while callers can
# force a flush before structural stream events to preserve ordering.
# The utility is request-local and stores no message content after publication.

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


STREAM_CONTENT_COALESCE_SECONDS = 0.05


class CumulativeContentPublisher:
    """Publish only the newest cumulative content update per short window."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any], str], Awaitable[None]],
        on_published: Callable[[], None] | None = None,
        coalesce_seconds: float = STREAM_CONTENT_COALESCE_SECONDS,
    ) -> None:
        self._publish = publish
        self._on_published = on_published
        self._coalesce_seconds = coalesce_seconds
        self._pending: tuple[dict[str, Any], str] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

    async def publish(self, payload: dict[str, Any], action_description: str) -> None:
        self._pending = (payload, action_description)
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_after_delay())

    async def flush(self) -> None:
        current_task = asyncio.current_task()
        try:
            async with self._flush_lock:
                while self._pending:
                    payload, action_description = self._pending
                    self._pending = None
                    await self._publish(payload, action_description)
                    if self._on_published:
                        self._on_published()
        finally:
            if self._flush_task is current_task:
                self._flush_task = None

    async def _flush_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._coalesce_seconds)
            await self.flush()
        except asyncio.CancelledError:
            pass
