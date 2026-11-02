"""Cold-start hooks of the chat sync feed for phased sync (architecture.sync@2).

Only sockets that advertise `chat_sync_feed_v1` are affected; for every other
socket `begin_cold_start` returns an inactive handle and phased sync stays
byte-identical. For capable sockets a cold start (phase=all, or the headless
metadata-only phase2):
1. reads the feed clock BEFORE any snapshot read (cursor for phased_sync_complete),
2. sends `chat_overview_priority_ready` (last opened chat, even outside the recent
   window, plus the personal due-soon set) concurrently with Phase 1a,
3. registers the socket for content-free `chat_sync_hint` events.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.core.api.app.services.chat_sync_feed_service import socket_has_capability

logger = logging.getLogger(__name__)
COLD_START_PHASES = frozenset({"all", "phase2"})


@dataclass
class ColdStartFeed:
    cursor: str | None = None
    overview_task: asyncio.Task | None = None
    _register: Any = field(default=None, repr=False)

    def completion_fields(self) -> dict[str, Any]:
        return {"sync_cursor": self.cursor} if self.cursor else {}

    async def finish(self) -> None:
        if self.overview_task is not None:
            await asyncio.wait({self.overview_task})
        if self._register is not None and self.cursor:
            self._register()


async def _last_opened(cache_service: Any, directus_service: Any, user_id: str) -> Any:
    cached = await cache_service.get_user_by_id(user_id)
    if cached and cached.get("last_opened"):
        return cached.get("last_opened")
    profile = await directus_service.get_user_profile(user_id)
    return profile[1].get("last_opened") if profile and profile[1] else None


async def _send_overview(feed: Any, manager: Any, cache_service: Any, directus_service: Any, user_id: str,
                         device_fingerprint_hash: str, team_id: str | None, context_epoch: Any) -> None:
    try:
        last_opened = await _last_opened(cache_service, directus_service, user_id)
        overview = await feed.build_overview(user_id, team_id, last_opened)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Overview is additive; Phase 1a still renders the list.
        logger.warning("Chat overview priority deferred: %s", type(exc).__name__)
        return
    await manager.send_personal_message(
        {"type": "chat_overview_priority_ready",
         "payload": {**overview, "team_id": team_id, "context_epoch": context_epoch}},
        user_id, device_fingerprint_hash,
    )


async def begin_cold_start(websocket: Any, manager: Any, cache_service: Any, directus_service: Any,
                           user_id: str, device_fingerprint_hash: str, team_id: str | None,
                           context_epoch: Any, sync_phase: str) -> ColdStartFeed:
    feed = getattr(getattr(getattr(websocket, "app", None), "state", None), "chat_sync_feed", None)
    # phase2 is the headless metadata-only cold start (native CLI inventory);
    # its clock is read before the snapshot exactly like phase=all.
    if feed is None or sync_phase not in COLD_START_PHASES or not socket_has_capability(websocket):
        return ColdStartFeed()
    try:
        cursor = await feed.cold_start_cursor(user_id, team_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Without a cursor the client simply cold-starts again next time.
        logger.warning("Chat sync cold-start cursor unavailable: %s", type(exc).__name__)
        cursor = None
    task = asyncio.create_task(_send_overview(
        feed, manager, cache_service, directus_service, user_id, device_fingerprint_hash, team_id, context_epoch,
    ))
    return ColdStartFeed(cursor=cursor, overview_task=task,
                         _register=lambda: feed.register(websocket, user_id, team_id))
