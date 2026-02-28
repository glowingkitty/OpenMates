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
#   3. Persists the chat metadata and assistant message to Directus via Celery
#      tasks so the chat survives cache expiry and is available cross-device
#      after reload / logout / login.
#   4. Adds the assistant message to the AI inference cache (vault-encrypted)
#      so that when the user sends a follow-up message, the LLM has the
#      original inspiration as context.  Without this step, the AI cache is
#      empty until the first follow-up triggers a cache-miss → request_chat_history
#      round-trip, which can fail under race conditions (Celery not yet done
#      persisting messages_v to Directus).
#
# No AI processing, no billing, no title generation.  The chat is already
# complete (title, category, assistant message) and just needs to be propagated
# and persisted.
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

from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.schemas.chat import MessageInCache

logger = logging.getLogger(__name__)


async def handle_sync_inspiration_chat(
    manager: Any,
    cache_service: Any,
    encryption_service: Any,
    user_id: str,
    user_id_hash: str,
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
      3. Queue Celery tasks to persist the chat metadata and assistant message to
         Directus so the chat survives cache expiry (unlike the previous Redis-only
         approach with a 10-min TTL).

    Args:
        manager: ConnectionManager instance
        cache_service: CacheService instance
        encryption_service: EncryptionService instance (for vault-encrypting the
            assistant message content before adding it to the AI inference cache)
        user_id: User UUID (plaintext, for broadcast / cache lookups)
        user_id_hash: SHA-256 hex digest of user_id (for Directus hashed_user_id)
        device_fingerprint_hash: Sending device hash (excluded from broadcast)
        payload: WebSocket message payload dict
    """
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    content = payload.get("content")
    # LLM-generated follow-up suggestions, encrypted client-side with the chat key.
    # Server never decrypts — stored as-is for zero-knowledge compliance.
    encrypted_follow_up_suggestions = payload.get("encrypted_follow_up_suggestions")

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
        created_at = payload.get("created_at", now_ts)

        # Extract encrypted fields from the payload (zero-knowledge — server never decrypts)
        encrypted_title = payload.get("encrypted_title")
        encrypted_category = payload.get("encrypted_category")
        encrypted_content = payload.get("encrypted_content")
        encrypted_chat_key = payload.get("encrypted_chat_key")
        messages_v = payload.get("messages_v", 1)
        title_v = payload.get("title_v", 1)

        chat_cache_data = {
            "chat_id": chat_id,
            "encrypted_title": encrypted_title,
            "encrypted_category": encrypted_category,
            "encrypted_chat_key": encrypted_chat_key,
            "messages_v": messages_v,
            "title_v": title_v,
            "created_at": created_at,
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

        # CRITICAL: Add the chat to the user's chat_ids_versions sorted set so that
        # check_chat_ownership() can find it when the user sends a follow-up message.
        #
        # Without this, the ownership check fails because:
        #   1. check_chat_exists_for_user() → False (chat not in sorted set)
        #   2. is_user_cache_primed() → True (user was already synced)
        #   3. "primed + not found" → ownership returns False
        #   → Server rejects the message with the misleading "shared chat" error.
        #
        # The sorted set is the source-of-truth for the ownership check (cache path).
        # Adding the chat here makes follow-up messages work immediately, before
        # Directus persistence (which happens asynchronously via Celery).
        await cache_service.add_chat_to_ids_versions(user_id, chat_id, now_ts)
        logger.info(
            "[SyncInspirationChat] Added chat %s to chat_ids_versions sorted set for user %s",
            chat_id,
            user_id[:8],
        )

        # ── 1b. Add the assistant message to the AI inference cache ───────────
        # The AI inference cache (vault-encrypted, 72h TTL) is what the LLM uses
        # for conversation context.  Without this step, the cache is empty when
        # the user sends a follow-up message, causing the LLM to lose the
        # original inspiration context.
        #
        # We vault-encrypt the plaintext `content` (which the client sent for
        # broadcast purposes) using the user's server-side vault key, then store
        # it as a MessageInCache entry in the AI cache.  This mirrors what
        # save_chat_message_and_update_versions() does in the normal message
        # pipeline (cache_chat_mixin.py:1203).
        if content:
            try:
                # Get the user's vault key for server-side encryption
                user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
                if not user_vault_key_id:
                    # Fallback: look up from Directus via cache user profile
                    user_data = await cache_service.get_user(user_id)
                    if user_data:
                        user_vault_key_id = user_data.get("vault_key_id")

                if user_vault_key_id:
                    # Vault-encrypt the plaintext content
                    encrypted_content_for_ai, _ = await encryption_service.encrypt_with_user_key(
                        content,
                        user_vault_key_id,
                    )

                    # Build a MessageInCache and add to AI cache
                    ai_cache_msg = MessageInCache(
                        id=message_id,
                        chat_id=chat_id,
                        role="assistant",
                        category=payload.get("category"),
                        sender_name=None,
                        encrypted_content=encrypted_content_for_ai,
                        created_at=created_at,
                        status="delivered",
                    )
                    ai_cache_success = await cache_service.add_ai_message_to_history(
                        user_id,
                        chat_id,
                        ai_cache_msg.model_dump_json(),
                    )
                    if ai_cache_success:
                        logger.info(
                            "[SyncInspirationChat] Added inspiration assistant message to AI cache "
                            "for chat %s (user %s…). Follow-up messages will have context.",
                            chat_id,
                            user_id[:8],
                        )
                    else:
                        logger.warning(
                            "[SyncInspirationChat] Failed to add inspiration assistant message to AI cache "
                            "for chat %s. Follow-up messages may lack context (server will request history from client).",
                            chat_id,
                        )
                else:
                    logger.warning(
                        "[SyncInspirationChat] No vault_key_id found for user %s…. "
                        "Cannot add inspiration assistant message to AI cache for chat %s. "
                        "Follow-up messages may lack context.",
                        user_id[:8],
                        chat_id,
                    )
            except Exception as e_ai_cache:
                # Non-fatal: if AI cache population fails, the server's existing
                # request_chat_history fallback will still work (just slower).
                logger.warning(
                    "[SyncInspirationChat] Error adding inspiration assistant message to AI cache "
                    "for chat %s: %s. Follow-up messages may lack context.",
                    chat_id,
                    e_ai_cache,
                )
        else:
            logger.debug(
                "[SyncInspirationChat] No plaintext content in payload for chat %s — "
                "skipping AI cache population (no context to store).",
                chat_id,
            )

        # ── 2. Broadcast to other devices ─────────────────────────────────────
        # Reuse the same event shape as `new_chat_message` so the receiving-side
        # handler (handleNewChatMessageImpl) on other devices can create the chat
        # shell + message without any changes to the frontend handler.
        broadcast_inner: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "content": content or "",
            "role": payload.get("role", "assistant"),
            "created_at": created_at,
            "messages_v": messages_v,
            "last_edited_overall_timestamp": now_ts,
            "encrypted_chat_key": encrypted_chat_key,
            # Include encrypted title so receiving device can show it immediately
            "encrypted_title": encrypted_title,
            "encrypted_category": encrypted_category,
        }

        # Forward the inspiration embed data (encrypted content + key wrappers)
        # so the receiving device can store and decrypt the video embed immediately
        # without waiting for a Directus round-trip via request_embed.
        # The client sends this as `inspiration_embed` in the payload; we pass it
        # through as-is (zero-knowledge — all fields are client-encrypted).
        inspiration_embed = payload.get("inspiration_embed")
        if inspiration_embed and isinstance(inspiration_embed, dict):
            broadcast_inner["inspiration_embed"] = inspiration_embed
            logger.info(
                "[SyncInspirationChat] Including inspiration_embed (embed_id=%s, %d keys) in broadcast for chat %s",
                inspiration_embed.get("embed_id", "?"),
                len(inspiration_embed.get("embed_keys", [])),
                chat_id,
            )

        broadcast_payload = {
            "type": "new_chat_message",
            "payload": broadcast_inner,
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

        # ── 3. Persist to Directus via Celery tasks ──────────────────────────
        # Queue chat metadata creation/update.  This ensures the chat record
        # exists in Directus (with encrypted title, category, chat key) so it
        # survives beyond the Redis cache TTL.
        #
        # Pattern matches encrypted_chat_metadata_handler.py:
        #   persist_encrypted_chat_metadata → creates or updates the chat row
        #   persist_new_chat_message → creates the assistant message row
        chat_metadata_fields: dict = {
            "encrypted_title": encrypted_title,
            "encrypted_category": encrypted_category,
            "encrypted_chat_key": encrypted_chat_key,
            "title_v": title_v,
            "messages_v": messages_v,
            "last_edited_overall_timestamp": now_ts,
            "last_message_timestamp": now_ts,
            "updated_at": now_ts,
        }

        # Persist LLM-generated follow-up suggestions if the client included them.
        # Stored as encrypted_follow_up_request_suggestions in the Directus chats row —
        # the same field used by the normal post-processing flow, so phased sync and
        # load_more_chats will deliver them to other devices automatically.
        if encrypted_follow_up_suggestions:
            chat_metadata_fields["encrypted_follow_up_request_suggestions"] = encrypted_follow_up_suggestions
            logger.debug(
                "[SyncInspirationChat] Including encrypted follow-up suggestions in metadata for chat %s",
                chat_id,
            )

        celery_app.send_task(
            "app.tasks.persistence_tasks.persist_encrypted_chat_metadata",
            args=[chat_id, chat_metadata_fields, user_id_hash, user_id],
            queue="persistence",
        )
        logger.info(
            "[SyncInspirationChat] Queued persist_encrypted_chat_metadata for chat %s",
            chat_id,
        )

        # Persist the assistant message (the pre-built response shown in the chat).
        # Only queue if we have encrypted content — without it, nothing to store.
        if encrypted_content:
            celery_app.send_task(
                name="app.tasks.persistence_tasks.persist_new_chat_message",
                args=[
                    message_id,              # message_id
                    chat_id,                 # chat_id
                    user_id_hash,            # hashed_user_id
                    "assistant",             # role
                    None,                    # encrypted_sender_name (N/A for assistant)
                    encrypted_category,      # encrypted_category
                    None,                    # encrypted_model_name (N/A — no AI model was used)
                    encrypted_content,       # encrypted_content
                    created_at,              # created_at (client timestamp)
                    messages_v,              # new_chat_messages_version
                    now_ts,                  # new_last_edited_overall_timestamp
                    encrypted_chat_key,      # encrypted_chat_key
                    user_id,                 # user_id (for sync cache updates)
                    None,                    # encrypted_pii_mappings (N/A for assistant)
                ],
                queue="persistence",
            )
            logger.info(
                "[SyncInspirationChat] Queued persist_new_chat_message (assistant) for chat %s, msg %s",
                chat_id,
                message_id,
            )
        else:
            logger.warning(
                "[SyncInspirationChat] No encrypted_content in payload for chat %s — "
                "assistant message will NOT be persisted to Directus",
                chat_id,
            )

    except Exception as e:
        logger.error(
            "[SyncInspirationChat] Error syncing inspiration chat %s for user %s…: %s",
            chat_id,
            user_id[:8],
            e,
            exc_info=True,
        )
