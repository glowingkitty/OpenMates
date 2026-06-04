# backend/core/api/app/routes/handlers/websocket_handlers/chat_content_batch_handler.py
# Handles requests from clients to fetch message content for a batch of chats.
# Used for immediate re-sync when data inconsistency is detected (local message
# count < server message count). This handler fetches encrypted messages from
# sync cache (or Directus fallback) and includes per-chat messages_v so the
# client can update its local version tracking.

import logging
from typing import List, Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.handlers.websocket_handlers.chat_compression_checkpoint_handler import (
    get_latest_chat_compression_checkpoint,
)

logger = logging.getLogger(__name__)


async def _fetch_code_run_outputs_for_chats(
    directus_service: DirectusService,
    chat_ids: List[str],
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch encrypted Code Run output sidecars for requested on-demand chats."""
    if not chat_ids:
        return []
    try:
        rows = await directus_service.get_items(
            "code_run_outputs",
            params={
                "filter[chat_id][_in]": ",".join(chat_ids),
                "filter[author_user_id][_eq]": user_id,
                "fields": "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
                "sort": "-updated_at",
                "limit": -1,
            },
            admin_required=True,
        ) or []
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.warning("Failed to fetch Code Run outputs for on-demand sync: %s", exc, exc_info=True)
        return []


async def handle_chat_content_batch(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any,  # ConnectionManager
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,) -> None:
    """
    Handles a client's request to fetch full message content for a batch of chat IDs.
    Triggered when the client detects a data inconsistency (local message count < server count)
    during Phase 2/3 sync. Fetches encrypted messages (zero-knowledge architecture) and includes
    per-chat messages_v so the client can update its version tracking.

    Response format:
    {
        "messages_by_chat_id": {
            "<chat_id>": [<JSON-serialized encrypted message strings>],
            ...
        },
        "versions_by_chat_id": {
            "<chat_id>": { "messages_v": <int>, "server_message_count": <int> },
            ...
        },
        "partial_error": true  // optional, only if some chats failed
    }
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("chat_content_batch", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        chat_ids: Optional[List[str]] = payload.get("chat_ids")

        if not chat_ids:
            logger.warning(
                f"User {user_id}, Device {device_fingerprint_hash}: "
                f"Received 'request_chat_content_batch' with no chat_ids."
            )
            await manager.send_personal_message(
                message={
                    "type": "error",
                    "payload": {"message": "No chat_ids provided in request_chat_content_batch."},
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash,
            )
            return

        logger.info(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Handling 'request_chat_content_batch' for {len(chat_ids)} chats."
        )

        messages_by_chat_id: Dict[str, List[str]] = {}
        versions_by_chat_id: Dict[str, Dict[str, Any]] = {}
        compression_checkpoints_by_chat_id: Dict[str, List[Dict[str, Any]]] = {}
        errors_occurred = False
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        for chat_id in chat_ids:
            try:
                # Verify chat ownership
                is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
                if not is_owner:
                    logger.warning(
                        f"User {user_id} attempted to fetch messages for chat {chat_id} they don't own. Skipping."
                    )
                    messages_by_chat_id[chat_id] = []
                    continue

                # --- Fetch messages: try sync cache first, fall back to Directus ---
                messages_data: List[str] = []

                # 1. Try sync cache (pre-serialized JSON strings with encrypted fields)
                cached_messages = await cache_service.get_sync_messages_history(user_id, chat_id)
                if cached_messages:
                    messages_data = cached_messages
                    logger.debug(
                        f"User {user_id}, Chat {chat_id}: "
                        f"Fetched {len(messages_data)} messages from sync cache for batch response."
                    )
                else:
                    # 2. Fall back to Directus (also returns JSON-serialized strings)
                    directus_messages = await directus_service.chat.get_all_messages_for_chat(
                        chat_id=chat_id,
                        decrypt_content=False,  # Zero-knowledge: keep encrypted
                    )
                    if directus_messages is not None:
                        messages_data = directus_messages
                        logger.debug(
                            f"User {user_id}, Chat {chat_id}: "
                            f"Fetched {len(messages_data)} messages from Directus for batch response."
                        )
                    else:
                        logger.info(
                            f"User {user_id}, Chat {chat_id}: "
                            f"No messages found for batch response."
                        )

                messages_by_chat_id[chat_id] = messages_data

                # --- Fetch messages_v: try cache first, fall back to Directus ---
                messages_v = 0
                cached_versions = await cache_service.get_chat_versions(user_id, chat_id)
                if cached_versions and cached_versions.messages_v is not None:
                    messages_v = cached_versions.messages_v
                else:
                    # Fall back to Directus chat metadata for messages_v
                    chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                    if chat_metadata:
                        messages_v = chat_metadata.get("messages_v", 0)

                # Use max of messages_v and actual message count to handle async gaps
                # (Celery may have updated messages but not yet incremented messages_v)
                server_message_count = len(messages_data)
                effective_messages_v = max(messages_v, server_message_count)

                versions_by_chat_id[chat_id] = {
                    "messages_v": effective_messages_v,
                    "server_message_count": server_message_count,
                }

                checkpoint = await get_latest_chat_compression_checkpoint(
                    directus_service,
                    chat_id,
                    user_id_hash,
                )
                if checkpoint:
                    compression_checkpoints_by_chat_id[chat_id] = [checkpoint]

            except Exception as e:
                errors_occurred = True
                logger.error(
                    f"User {user_id}, Device {device_fingerprint_hash}: "
                    f"Error fetching messages for chat {chat_id} in batch request: {e}",
                    exc_info=True,
                )
                messages_by_chat_id[chat_id] = []

        # Fetch embeds + embed_keys for all requested chats (on-demand path)
        # This enables opening chats from 101-1000 range that weren't synced in Phase 1b
        all_embeds: List[Dict[str, Any]] = []
        all_embed_keys: List[Dict[str, Any]] = []
        seen_embed_ids: set = set()
        seen_key_ids: set = set()
        hashed_ids_for_keys: List[str] = []

        for chat_id in chat_ids:
            hashed_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_ids_for_keys.append(hashed_id)

            try:
                embeds = await cache_service.get_sync_embeds_for_chat(chat_id)
                if not embeds:
                    embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_id)
                if embeds:
                    for embed in embeds:
                        embed_id = embed.get("embed_id")
                        embed_status = embed.get("status")
                        if embed_id and embed_id not in seen_embed_ids and embed_status not in ("error", "cancelled"):
                            all_embeds.append(embed)
                            seen_embed_ids.add(embed_id)
            except Exception as e:
                logger.warning(f"Batch handler: Error fetching embeds for {chat_id}: {e}")

        if hashed_ids_for_keys:
            try:
                batch_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_ids_batch(hashed_ids_for_keys)
                if batch_keys:
                    for key_entry in batch_keys:
                        key_id = key_entry.get("id")
                        if key_id and key_id not in seen_key_ids:
                            all_embed_keys.append(key_entry)
                            seen_key_ids.add(key_id)
            except Exception as e:
                logger.warning(f"Batch handler: Error fetching embed_keys: {e}")

        code_run_outputs = await _fetch_code_run_outputs_for_chats(
            directus_service,
            chat_ids,
            user_id,
        )

        response_payload_data: Dict[str, Any] = {
            "messages_by_chat_id": messages_by_chat_id,
            "versions_by_chat_id": versions_by_chat_id,
            "compression_checkpoints_by_chat_id": compression_checkpoints_by_chat_id,
            "embeds": all_embeds,
            "embed_keys": all_embed_keys,
            "code_run_outputs": code_run_outputs,
        }

        if errors_occurred:
            response_payload_data["partial_error"] = True

        try:
            await manager.send_personal_message(
                message={"type": "chat_content_batch_response", "payload": response_payload_data},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash,
            )
            logger.info(
                f"User {user_id}, Device {device_fingerprint_hash}: "
                f"Sent 'chat_content_batch_response' for {len(messages_by_chat_id)} chats."
            )
        except Exception as e:
            logger.error(
                f"User {user_id}, Device {device_fingerprint_hash}: "
                f"Failed to send 'chat_content_batch_response': {e}",
                exc_info=True,
            )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
