# backend/core/api/app/routes/notifications.py
"""
Authenticated notification event APIs.

The list and SSE endpoints expose only safe notification events. They do not
return assistant response plaintext, chat titles, APNs tokens, or encrypted
payload ciphertext.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_cache_service, get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.notification_event_service import NotificationEventService
from backend.core.api.app.services.notification_sse import sse_comment, sse_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])

SSE_HEARTBEAT_SECONDS = 15


@router.get("")
async def list_notifications(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    """Return recent safe notification events for the current user."""
    service = NotificationEventService(cache_service)
    events = await service.get_recent(str(current_user.id), limit=limit)
    return {"events": events}


@router.get("/stream")
async def stream_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> StreamingResponse:
    """Stream safe notification events for the current user using SSE."""
    user_id = str(current_user.id)
    channel = NotificationEventService.channel_key(user_id)

    async def event_generator():
        yield sse_comment("connected")
        client = await cache_service.client
        if not client:
            yield sse_event("error", {"message": "Notification stream unavailable"})
            return

        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=SSE_HEARTBEAT_SECONDS)
                if not message:
                    yield sse_comment("heartbeat")
                    continue

                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    event_data = json.loads(data) if isinstance(data, str) else data
                except json.JSONDecodeError:
                    logger.warning("Notification SSE skipped invalid event for user %s", user_id[:8])
                    continue
                if isinstance(event_data, dict):
                    yield sse_event("notification", event_data, event_id=event_data.get("id"))
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Notification SSE stream ended for user %s: %s", user_id[:8], exc)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
