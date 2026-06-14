# backend/core/api/app/services/notification_event_service.py
"""
Unified notification event service.

This service stores short-lived, safe notification events in Redis and publishes
them to per-user channels for SSE consumers. It intentionally serializes only an
allowlisted event schema: assistant response plaintext and chat titles must not
enter this model unless encrypted in a channel-specific payload.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

NOTIFICATION_RECENT_LIMIT = 100
NOTIFICATION_RECENT_TTL_SECONDS = 7 * 24 * 60 * 60
NOTIFICATION_TYPE_CHAT_ASSISTANT_MESSAGE = "chat.assistant_message_received"
SAFE_TITLE_KEY_OPENMATES = "apps.openmates"
SAFE_BODY_KEY_NEW_MESSAGE = "notifications.chat_message.new_message_received"


class NotificationEvent(BaseModel):
    """Safe, user-scoped notification event returned by APIs and SSE."""

    id: str = Field(default_factory=lambda: f"notif_{uuid4().hex}")
    user_id: str
    type: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    safe_title_key: str
    safe_body_key: str
    routing: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    read_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Return the public shape exposed to clients without internal user_id."""
        data = self.model_dump(mode="json")
        data.pop("user_id", None)
        return data


class NotificationEventService:
    """Redis-backed notification event store and publisher."""

    def __init__(self, cache_service: "CacheService"):
        self.cache_service = cache_service

    async def create_chat_assistant_message_event(
        self,
        *,
        user_id: str,
        chat_id: str,
        has_encrypted_preview: bool = False,
    ) -> NotificationEvent:
        """Create the safe event for an assistant response notification."""
        event = NotificationEvent(
            user_id=user_id,
            type=NOTIFICATION_TYPE_CHAT_ASSISTANT_MESSAGE,
            safe_title_key=SAFE_TITLE_KEY_OPENMATES,
            safe_body_key=SAFE_BODY_KEY_NEW_MESSAGE,
            routing={"chat_id": chat_id},
            metadata={"has_encrypted_preview": has_encrypted_preview},
        )
        await self.store_and_publish(event)
        return event

    async def store_and_publish(self, event: NotificationEvent) -> None:
        """Store a recent event and publish it to the user's SSE channel."""
        await self._store_recent(event)
        published = await self.cache_service.publish_event(
            self.channel_key(event.user_id),
            event.public_dict(),
        )
        if not published:
            logger.warning(
                "Notification event publish skipped for user %s event %s",
                event.user_id[:8],
                event.id,
            )

    async def get_recent(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent safe events for a user, newest first."""
        bounded_limit = max(1, min(limit, NOTIFICATION_RECENT_LIMIT))
        client = await self.cache_service.client
        if not client:
            logger.warning("Notification recent lookup skipped: cache unavailable")
            return []

        raw_events = await client.lrange(self.recent_key(user_id), 0, bounded_limit - 1)
        events: list[dict[str, Any]] = []
        for raw_event in raw_events:
            if isinstance(raw_event, bytes):
                raw_event = raw_event.decode("utf-8")
            try:
                event = NotificationEvent(**json.loads(raw_event))
            except Exception as exc:
                logger.warning("Skipping invalid notification event for user %s: %s", user_id[:8], exc)
                continue
            events.append(event.public_dict())
        return events

    async def _store_recent(self, event: NotificationEvent) -> None:
        client = await self.cache_service.client
        if not client:
            logger.warning("Notification recent store skipped: cache unavailable")
            return

        key = self.recent_key(event.user_id)
        await client.lpush(key, event.model_dump_json())
        await client.ltrim(key, 0, NOTIFICATION_RECENT_LIMIT - 1)
        await client.expire(key, NOTIFICATION_RECENT_TTL_SECONDS)

    @staticmethod
    def recent_key(user_id: str) -> str:
        return f"notifications:recent:{user_id}"

    @staticmethod
    def channel_key(user_id: str) -> str:
        return f"notifications:stream:{user_id}"
