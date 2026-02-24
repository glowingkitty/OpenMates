# backend/core/api/app/routes/handlers/websocket_handlers/sync_inspiration_chat_handler.py
#
# WebSocket handler for the `sync_inspiration_chat` client->server message.
#
# When a user clicks a Daily Inspiration banner, a chat is created purely in
# local IndexedDB (with a pre-built assistant message).  This handler receives
# the encrypted chat metadata and first message, then:
#   1. Stores the chat in the server's sync cache (so phased sync includes it).
#   2. Broadcasts a `new_chat_message` event to the user's OTHER connected
#      devices so the chat appears immediately without waiting for a sync cycle.
#
# This is intentionally lightweight — no AI processing, no billing, no title
# generation.  The chat is already complete (title, category, assistant message)
# and just needs to be propagated to other devices.
#
# Message format (client -> server):
#   {
#     "type": "sync_inspiration_chat",
#     "payload": {
#       "chat_id": str,
#       "message_id": str,
#       "content": str,            # cleartext assistant message (for broadcast)
#       "role": "assistant",
#       "category": str,
#       "created_at": int,         # unix ts
#       "messages_v": int,
#       "title_v": int,
#       "encrypted_title": str,
#       "encrypted_category": str,
#       "encrypted_content": str,
#       "encrypted_chat_key": str,
#     }
#   }

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_sync_inspiration_chat(
    manager: Any,
    cache_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict,
) -> None:
    """
    Sync an inspiration-created chat to the server and broadcast to other devices.

    The chat already exists on the sending device.  We:
      1. Update the server-side sync cache so the chat appears in Phase 1/2/3 sync
         for any device that reconnects later.
      2. Broadcast to all OTHER connected devices of the same user so they can
         create the chat locally (same shape as the existing new_chat_message handler
         on the frontend).

    Args:
        manager: ConnectionManager instance
        cache_service: CacheService instance
        user_id: User UUID
        device_fingerprint_hash: Sending device hash (excluded from broadcast)
        payload: WebSocket message payload dict
    """
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    content = payload.get("content")

    if not chat_id or not message_id:
        logger.warning(
            "[SyncInspirationChat] Missing chat_id or message_id in payload from user %s…",
            user_id[:8],
        )
        return

    try:
        # ── 1. Update the sync cache ──────────────────────────────────────────
        # Store minimal chat metadata in Redis so the next phased sync includes
        # this chat.  We store the encrypted fields exactly as received — the
        # server never decrypts them (zero-knowledge architecture).
        import hashlib
        import json
        import time

        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        now_ts = int(time.time())

        chat_cache_data = {
            "chat_id": chat_id,
            "encrypted_title": payload.get("encrypted_title"),
            "encrypted_category": payload.get("encrypted_category"),
            "encrypted_chat_key": payload.get("encrypted_chat_key"),
            "messages_v": payload.get("messages_v", 1),
            "title_v": payload.get("title_v", 1),
            "created_at": payload.get("created_at", now_ts),
            "updated_at": now_ts,
            "last_edited_overall_timestamp": now_ts,
        }

        # Store in the per-user sync cache with a short TTL (matches phased sync cache)
        cache_key = f"sync_inspiration_chat:{hashed_user_id}:{chat_id}"
        client = await cache_service.client
        if client:
            await client.set(
                cache_key,
                json.dumps(chat_cache_data),
                ex=600,  # 10 min TTL — same as sync cache entries
            )
            logger.debug(
                "[SyncInspirationChat] Cached inspiration chat %s for user %s…",
                chat_id,
                user_id[:8],
            )

        # ── 2. Broadcast to other devices ─────────────────────────────────────
        # Reuse the same event shape as `new_chat_message` so the receiving-side
        # handler (handleNewChatMessageImpl) on other devices can create the chat
        # shell + message without any changes to the frontend handler.
        broadcast_payload = {
            "type": "new_chat_message",
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "content": content or "",
                "role": payload.get("role", "assistant"),
                "created_at": payload.get("created_at", now_ts),
                "messages_v": payload.get("messages_v", 1),
                "last_edited_overall_timestamp": now_ts,
                "encrypted_chat_key": payload.get("encrypted_chat_key"),
                # Include encrypted title so receiving device can show it immediately
                "encrypted_title": payload.get("encrypted_title"),
                "encrypted_category": payload.get("encrypted_category"),
            },
        }

        await manager.broadcast_to_user(
            message=broadcast_payload,
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )

        logger.info(
            "[SyncInspirationChat] Broadcast inspiration chat %s to other devices of user %s…",
            chat_id,
            user_id[:8],
        )

    except Exception as e:
        logger.error(
            "[SyncInspirationChat] Error syncing inspiration chat %s for user %s…: %s",
            chat_id,
            user_id[:8],
            e,
            exc_info=True,
        )
