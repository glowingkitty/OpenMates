"""Per-carrier progress of a streaming authored-results block, and its background work.

While the assistant streams an ``openmates_embeds`` block, the stream consumer
calls the carrier update with ``status="processing"`` and the text so far. The
authored-result service keeps one ``CarrierProgress`` per carrier here: the
incremental envelope reader, the cards already published (same stable ids as
the closed-block path) and the last carrier snapshot sent, so unchanged lines
publish nothing.

Venue geocoding of published cards runs as background tasks tracked per
assistant message. The stream consumer awaits ``drain_authored_result_background``
once streaming ends, so the event loop never closes over unfinished lookups.
State lives in the worker process that runs the stream; it is bounded and
removed when the carrier finishes or the stream is interrupted.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Coroutine

from backend.apps.ai.utils.authored_result_stream import ProgressiveEnvelope

logger = logging.getLogger(__name__)

MAX_TRACKED_CARRIERS = 256


@dataclass
class PublishedCard:
    """One own card already published finished while the block streamed."""

    child_id: str
    local_id: str
    kind: str
    title: str
    embed_ref: str
    content_hash: str


@dataclass
class CarrierProgress:
    """Streaming progress of one carrier; ids and order match the closed block."""

    carrier_id: str
    message_id: str
    envelope: ProgressiveEnvelope
    cards: list[PublishedCard] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    geocoding: set[str] = field(default_factory=set)
    last_snapshot: tuple[Any, ...] | None = None

    def bind(self, local_id: str, embed_id: str) -> None:
        """Record an accepted label in source order."""
        self.bindings[local_id] = embed_id
        self.order.append(local_id)

    def member_ids(self) -> list[str]:
        """Members so far; a label repeated later is dropped as the closed block drops it."""
        return [self.bindings[label] for label in self.order
                if label not in self.envelope.duplicated_labels]

    def own_cards(self) -> list[PublishedCard]:
        """Own published cards that remain members."""
        return [card for card in self.cards if card.local_id not in self.envelope.duplicated_labels]

    def card(self, child_id: str) -> PublishedCard | None:
        """The published card with this id, if any."""
        return next((card for card in self.cards if card.child_id == child_id), None)


_progress: "OrderedDict[str, CarrierProgress]" = OrderedDict()
_background: dict[str, set[asyncio.Task[Any]]] = {}


def carrier_progress(
    carrier_id: str, message_id: str, *, source_byte_limit: int, item_limit: int,
) -> CarrierProgress:
    """Return the carrier's progress, creating it on the first streamed update."""
    progress = _progress.get(carrier_id)
    if progress is None or progress.message_id != message_id:
        progress = CarrierProgress(carrier_id, message_id, ProgressiveEnvelope(
            source_byte_limit=source_byte_limit, item_limit=item_limit,
        ))
        _progress[carrier_id] = progress
        while len(_progress) > MAX_TRACKED_CARRIERS:
            _progress.popitem(last=False)
    return progress


def existing_progress(carrier_id: str) -> CarrierProgress | None:
    """The carrier's progress if it streamed, else None."""
    return _progress.get(carrier_id)


def finish_progress(carrier_id: str) -> None:
    """Forget a carrier once it is finished or interrupted."""
    _progress.pop(carrier_id, None)


def track_background(message_id: str, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """Run ``work`` without blocking the stream; the stream end drains it."""
    task = asyncio.get_running_loop().create_task(work)
    tasks = _background.setdefault(message_id, set())
    tasks.add(task)

    def _forget(done: asyncio.Task[None]) -> None:
        tasks.discard(done)
        if not tasks and _background.get(message_id) is tasks:
            _background.pop(message_id, None)

    task.add_done_callback(_forget)
    return task


async def drain_authored_result_background(message_id: str | None, log_prefix: str = "") -> None:
    """Await this message's pending card geocoding; a failed lookup is only logged.

    A failure leaves that card published without coordinates, which is the
    documented outcome of a missed venue lookup; it never fails the answer.
    """
    tasks = list(_background.get(message_id or "", ()))
    if not tasks:
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            logger.error(
                "%s Authored card coordinate update failed (%s); card keeps no map",
                log_prefix, type(result).__name__,
            )
