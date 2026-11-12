"""Live progress of a running app skill for its processing embed.

Wire contract: the existing ``send_embed_data`` event is re-sent with
``status: "processing"`` for the same placeholder embed id. The content is the
original placeholder content plus::

    progress: {"sources_total": int, "sources_done": int, "result_count": int, "seq": int}

``seq`` strictly increases per embed. The frames are never persisted (no cache,
no Directus); only the finished embed is stored.

Flow: the AI processor opens a ``skill_progress_scope`` around one skill call
(``open_progress_channel`` builds the channel from the placeholder embeds). The
skill reports through ``BaseSkill.publish_progress`` or, for source counting,
through ``SkillProgress``. The channel lives in a ``ContextVar``: it follows the
asyncio tasks of one call and never leaks into other calls, even when skill
instances are shared.

To register one more source of an item (for example a web search next to the
installed providers), call ``await progress.add_sources(1)`` before it starts
and ``await progress.source_done(result_count)`` when it ends.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence, Tuple

from toon_format import encode as toon_encode

from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

logger = logging.getLogger(__name__)

MIN_FRAME_INTERVAL_SECONDS = 0.4
PROGRESS_EMBED_TYPE = "app_skill_use"

# What the publish path can raise (embed service, Redis/WebSocket publishing, TOON encoding).
_PUBLISH_ERRORS = (RequiredRecoveryOutputError, OSError, RuntimeError, ValueError, TypeError)

ProgressState = Tuple[int, int, int]


@dataclass(frozen=True)
class ProgressTarget:
    """One placeholder embed and its original placeholder content."""

    embed_id: str
    content: Dict[str, Any]


class SkillProgressChannel:
    """Throttled sender of progress frames to the placeholder embeds of one skill call."""

    def __init__(self, *, embed_service: Any, chat_id: str, message_id: str, user_id: str, user_id_hash: str,
                 task_id: Optional[str], targets: Sequence[ProgressTarget],
                 min_interval: float = MIN_FRAME_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._embed_service = embed_service
        self._chat_id = chat_id
        self._message_id = message_id
        self._user_id = user_id
        self._user_id_hash = user_id_hash
        self._task_id = task_id
        self._targets = list(targets)
        self._min_interval = min_interval
        self._clock = clock
        self._latest: Optional[ProgressState] = None
        self._last_sent: Optional[ProgressState] = None
        self._last_sent_at: Optional[float] = None
        self._seq = 0
        self._trailing: Optional["asyncio.Task[None]"] = None
        self._lock = asyncio.Lock()

    async def publish(self, sources_total: int, sources_done: int, result_count: int) -> None:
        """Send now when due or final; otherwise schedule the latest state for the end of the interval."""
        state: ProgressState = (int(sources_total), int(sources_done), int(result_count))
        self._latest = state
        if state == self._last_sent:
            return
        final = state[0] > 0 and state[1] >= state[0]
        wait = 0.0 if self._last_sent_at is None else self._min_interval - (self._clock() - self._last_sent_at)
        if final or wait <= 0:
            self._cancel_trailing()
            await self._send_latest()
        elif self._trailing is None:
            self._trailing = asyncio.create_task(self._send_after(wait))

    async def close(self) -> None:
        """Flush the latest unsent state and stop the trailing timer."""
        self._cancel_trailing()
        await self._send_latest()

    def _cancel_trailing(self) -> None:
        if self._trailing is not None:
            self._trailing.cancel()
            self._trailing = None

    async def _send_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._trailing = None
        await self._send_latest()

    async def _send_latest(self) -> None:
        async with self._lock:
            state = self._latest
            if state is None or state == self._last_sent:
                return
            self._seq += 1
            self._last_sent = state
            self._last_sent_at = self._clock()
            progress = {"sources_total": state[0], "sources_done": state[1],
                        "result_count": state[2], "seq": self._seq}
            for target in self._targets:
                await self._send_frame(target, progress)

    async def _send_frame(self, target: ProgressTarget, progress: Dict[str, int]) -> None:
        content = {**target.content, "status": "processing", "progress": progress}
        try:
            await self._embed_service.send_embed_data_to_client(
                embed_id=target.embed_id,
                embed_type=PROGRESS_EMBED_TYPE,
                content_toon=toon_encode(content),
                chat_id=self._chat_id,
                message_id=self._message_id,
                user_id=self._user_id,
                user_id_hash=self._user_id_hash,
                status="processing",
                task_id=self._task_id,
                is_private=False,
                is_shared=False,
                log_prefix="[SkillProgress]",
                check_cache_status=False,
            )
        except _PUBLISH_ERRORS as exc:
            logger.warning("[SkillProgress] Progress frame for embed %s failed: %s", target.embed_id, exc)


_CHANNEL: ContextVar[Optional[SkillProgressChannel]] = ContextVar("skill_progress_channel", default=None)


def targets_from_placeholder(placeholder: Any) -> List[ProgressTarget]:
    """Progress targets of a placeholder result (single, or ``multiple`` with ``placeholders``)."""
    if not isinstance(placeholder, dict):
        return []
    items = placeholder.get("placeholders") if placeholder.get("multiple") else [placeholder]
    targets: List[ProgressTarget] = []
    for item in items or []:
        if isinstance(item, dict) and item.get("embed_id") and isinstance(item.get("placeholder_content"), dict):
            targets.append(ProgressTarget(str(item["embed_id"]), dict(item["placeholder_content"])))
    return targets


def open_progress_channel(*, cache_service: Any, directus_service: Any, encryption_service: Any, placeholder: Any, chat_id: Optional[str],
                          message_id: Optional[str], user_id: Optional[str], user_id_hash: Optional[str],
                          task_id: Optional[str], external_request: bool = False) -> Optional[SkillProgressChannel]:
    """Channel for one skill call, or None when progress cannot be shown (no chat, no placeholder, API call)."""
    targets = targets_from_placeholder(placeholder)
    if external_request or not targets or not (cache_service and encryption_service):
        return None
    if not (chat_id and message_id and user_id and user_id_hash):
        return None
    from backend.core.api.app.services.embed_service import EmbedService

    embed_service = EmbedService(cache_service=cache_service, directus_service=directus_service,
                                 encryption_service=encryption_service)
    return SkillProgressChannel(embed_service=embed_service, chat_id=chat_id, message_id=message_id,
                                user_id=user_id, user_id_hash=user_id_hash, task_id=task_id, targets=targets)


@contextlib.asynccontextmanager
async def skill_progress_scope(channel: Optional[SkillProgressChannel]) -> AsyncIterator[None]:
    """Make ``channel`` the progress channel of the skill call run inside; flush it on exit."""
    if channel is None:
        yield
        return
    token = _CHANNEL.set(channel)
    try:
        yield
    finally:
        _CHANNEL.reset(token)
        await channel.close()


async def publish_current_progress(*, sources_total: int, sources_done: int, result_count: int) -> None:
    """Report progress to the current call's channel; silent no-op without one. Never raises."""
    channel = _CHANNEL.get()
    if channel is None:
        return
    try:
        await channel.publish(sources_total, sources_done, result_count)
    except _PUBLISH_ERRORS as exc:
        logger.warning("[SkillProgress] Progress update failed: %s", exc)


class SkillProgress:
    """Counts the sources (providers) of one skill call and reports them through ``skill.publish_progress``."""

    def __init__(self, skill: Any) -> None:
        self._skill = skill
        self.sources_total = 0
        self.sources_done = 0
        self.result_count = 0

    async def add_sources(self, count: int = 1) -> None:
        """Register sources that are about to be searched."""
        self.sources_total += max(0, int(count))
        await self._publish()

    async def source_done(self, result_count: int = 0) -> None:
        """One source finished with ``result_count`` results (0 for a failed source)."""
        self.sources_done += 1
        self.result_count += max(0, int(result_count))
        await self._publish()

    async def _publish(self) -> None:
        await self._skill.publish_progress(sources_total=self.sources_total, sources_done=self.sources_done,
                                           result_count=self.result_count)
