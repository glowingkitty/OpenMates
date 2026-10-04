# backend/core/api/app/routes/handlers/websocket_handlers/chat_content_batch_handler.py
# Handles requests from clients to fetch message content for a batch of chats.
# Used for immediate re-sync when data inconsistency is detected (local message
# count < server message count). This handler fetches encrypted messages from
# sync cache (or Directus fallback) and includes per-chat messages_v so the
# client can update its local version tracking.

import logging
import hashlib
import re
from typing import List, Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.handlers.websocket_handlers.chat_compression_checkpoint_handler import (
    get_latest_chat_compression_checkpoint,
)
from backend.core.api.app.routes.handlers.websocket_handlers.sync_sidecar_hydration import (
    load_sync_sidecars_for_chats,
)
from backend.core.api.app.routes.handlers.websocket_handlers.sync_message_hydration import (
    load_bounded_sync_message_window,
)

logger = logging.getLogger(__name__)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


async def _send_apps_legacy_embed_page(
    *, manager: Any, directus_service: DirectusService, user_id: str,
    device_fingerprint_hash: str, payload: Dict[str, Any],
) -> None:
    """A bounded, ownership-checked ciphertext page for local legacy indexing."""
    chat_ids = payload.get("chat_ids")
    chat_id = chat_ids[0] if isinstance(chat_ids, list) and len(chat_ids) == 1 else None
    team_id = payload.get("team_id") or None
    request_id = payload.get("request_id")
    offset = payload.get("embed_offset", 0)
    context_epoch = payload.get("context_epoch")
    response: Dict[str, Any] = {
        "apps_legacy_embeds_only": True, "request_id": request_id,
        "team_id": team_id, "context_epoch": context_epoch,
        "chat_id": chat_id, "embed_offset": offset,
        "messages_by_chat_id": {}, "embeds": [], "embed_keys": [], "next_embed_offset": None,
    }
    try:
        if (not isinstance(chat_id, str) or not _UUID_RE.fullmatch(chat_id)
                or not isinstance(request_id, str) or not _UUID_RE.fullmatch(request_id)
                or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 1_000_000
                or (team_id is not None and (not isinstance(team_id, str) or not _UUID_RE.fullmatch(team_id)))):
            raise ValueError("Invalid legacy embed page request")
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()
        team_hash = hashlib.sha256(team_id.encode()).hexdigest() if team_id else None
        team_membership = None
        if team_id:
            team_membership = await directus_service.team.require_team_role(
                team_id, user_id, {"owner", "admin", "member", "viewer"},
            )
        chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
        if not chat or (team_hash and chat.get("hashed_team_id") != team_hash) or (
            not team_hash and (chat.get("hashed_team_id") or chat.get("hashed_user_id") != user_hash)
        ):
            raise PermissionError("Chat is outside the requested account scope")

        chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
        rows = await directus_service.get_items("embeds", params={
            "filter[hashed_chat_id][_eq]": chat_hash,
            "filter[parent_embed_id][_null]": True,
            "fields": "embed_id,hashed_chat_id,hashed_user_id,hashed_team_id,root_embed_id,encrypted_type,encrypted_content,status,parent_embed_id,created_at",
            "sort": "embed_id", "offset": offset, "limit": 51,
        }, no_cache=True, admin_required=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise ValueError("Invalid embed page")
        page = rows[:50]
        if len(rows) > 50:
            response["next_embed_offset"] = offset + 50
        can_migrate_team = bool(team_membership and team_membership.get("role") in {"owner", "admin", "member"})
        response["embeds"] = [row for row in page if row.get("status") not in ("error", "cancelled")
            and row.get("root_embed_id") in (None, row.get("embed_id")) and (
            (not team_hash and not row.get("hashed_team_id") and row.get("hashed_user_id") == user_hash)
            or (team_hash and row.get("hashed_team_id") == team_hash)
            or (team_hash and can_migrate_team and not row.get("hashed_team_id") and
                row.get("hashed_user_id") in {chat.get("hashed_user_id"), user_hash})
        )]

        hashed_ids = [hashlib.sha256(row["embed_id"].encode()).hexdigest()
                      for row in response["embeds"] if isinstance(row.get("embed_id"), str)]
        if hashed_ids:
            wrappers: List[Dict[str, Any]] = []
            for key_offset in range(0, 1000, 250):
                key_page = await directus_service.get_items("embed_keys", params={
                    "filter[hashed_embed_id][_in]": ",".join(hashed_ids),
                    "fields": "hashed_embed_id,key_type,hashed_chat_id,encrypted_embed_key,hashed_user_id,created_at",
                    "offset": key_offset, "limit": 250,
                }, no_cache=True, admin_required=True, raise_on_error=True)
                if not isinstance(key_page, list):
                    raise ValueError("Invalid embed key page")
                wrappers.extend(key_page)
                if len(key_page) < 250:
                    break
            else:
                raise ValueError("Too many embed key wrappers for one page")
            response["embed_keys"] = [key for key in wrappers if (
                key.get("key_type") == "chat" and key.get("hashed_chat_id") == chat_hash
            ) or (
                not team_hash and key.get("key_type") == "master" and key.get("hashed_user_id") == user_hash
            )]
    except Exception as exc:
        logger.warning("Apps legacy embed page rejected: %s", type(exc).__name__)
        response.update({"embeds": [], "embed_keys": [], "next_embed_offset": None, "error": "Legacy embed page unavailable"})
    await manager.send_personal_message(
        message={"type": "chat_content_batch_response", "payload": response},
        user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
    )


async def handle_chat_content_batch(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any,  # ConnectionManager
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
    archive_service: Any = None,
) -> None:
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
        if payload.get("apps_legacy_embeds_only") is True:
            await _send_apps_legacy_embed_page(
                manager=manager, directus_service=directus_service, user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash, payload=payload,
            )
            return
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

        chat_ids = list(dict.fromkeys(chat_ids))
        if len(chat_ids) > 5:
            # Older clients may request many chats in one frame. Preserve their
            # complete result by emitting several bounded response frames.
            for offset in range(0, len(chat_ids), 5):
                await handle_chat_content_batch(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                    manager=manager,
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                    payload={**payload, "chat_ids": chat_ids[offset:offset + 5]},
                    user_otel_attrs=user_otel_attrs,
                    archive_service=archive_service,
                )
            return

        logger.info(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Handling 'request_chat_content_batch' for {len(chat_ids)} chats."
        )

        messages_by_chat_id: Dict[str, List[str]] = {}
        versions_by_chat_id: Dict[str, Dict[str, Any]] = {}
        compression_checkpoints_by_chat_id: Dict[str, List[Dict[str, Any]]] = {}
        message_windows_by_chat_id: Dict[str, Dict[str, Any]] = {}
        errors_occurred = False
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        authorized_chat_ids: List[str] = []
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
                authorized_chat_ids.append(chat_id)

                window = await load_bounded_sync_message_window(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    user_id=user_id,
                    chat_id=chat_id,
                    log_prefix="[CHAT_CONTENT_BATCH]",
                    user_otel_attrs=user_otel_attrs,
                    archive_service=archive_service,
                )
                messages_data = window["messages"]
                messages_by_chat_id[chat_id] = messages_data
                message_windows_by_chat_id[chat_id] = {
                    "has_more_before": window["has_more_before"],
                    "start_cursor": window["start_cursor"],
                    "oversized_message": window["oversized_message"],
                    "oversized_message_cursor": window.get("oversized_message_cursor"),
                }

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
                server_message_count = window["server_message_count"]
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
        embed_windows_by_chat_id: Dict[str, Dict[str, Any]] = {}
        embed_key_windows_by_chat_id: Dict[str, Dict[str, Any]] = {}

        for chat_id in authorized_chat_ids:
            hashed_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_ids_for_keys.append(hashed_id)

            try:
                embed_window = await directus_service.embed.get_embed_window_by_hashed_chat_id(hashed_id)
                embeds = embed_window["embeds"]
                embed_windows_by_chat_id[chat_id] = {
                    "has_more_before": embed_window["has_more_before"],
                    "start_cursor": embed_window["start_cursor"],
                    "oversized_embed_id": embed_window["oversized_embed_id"],
                    "oversized_embed_cursor": embed_window.get("oversized_embed_cursor"),
                }
                page_hashes = [
                    embed.get("hashed_embed_id") or hashlib.sha256(embed["embed_id"].encode()).hexdigest()
                    for embed in embeds if embed.get("embed_id")
                ]
                key_window = await directus_service.embed.get_sync_embed_key_window_for_page(
                    hashed_id, user_id_hash, page_hashes,
                )
                keys = key_window["embed_keys"]
                embed_key_windows_by_chat_id[chat_id] = {**key_window, "embed_ids": [embed["embed_id"] for embed in embeds if embed.get("embed_id")]}
                embed_key_windows_by_chat_id[chat_id].pop("embed_keys")
                if embeds:
                    for embed in embeds:
                        embed_id = embed.get("embed_id")
                        embed_status = embed.get("status")
                        if embed_id and embed_id not in seen_embed_ids and embed_status not in ("error", "cancelled"):
                            all_embeds.append(embed)
                            seen_embed_ids.add(embed_id)
                for key_entry in keys:
                    key_id = key_entry.get("id")
                    if key_id and key_id not in seen_key_ids:
                        all_embed_keys.append(key_entry)
                        seen_key_ids.add(key_id)
            except Exception as e:
                errors_occurred = True
                logger.warning(f"Batch handler: Error fetching embeds for {chat_id}: {e}")

        code_run_outputs, code_windows = await load_sync_sidecars_for_chats(
            directus_service, collection="code_run_outputs", chat_ids=authorized_chat_ids, user_id=user_id,
        )
        notebook_run_outputs, notebook_windows = await load_sync_sidecars_for_chats(
            directus_service, collection="notebook_run_outputs", chat_ids=authorized_chat_ids, user_id=user_id,
        )
        chat_key_wrappers: List[Dict[str, Any]] = []
        wrapper_windows: Dict[str, Dict[str, Any]] = {}
        for chat_id, hashed_id in zip(authorized_chat_ids, hashed_ids_for_keys):
            page = await directus_service.chat_key_wrapper.get_sync_wrapper_window_for_chat(
                hashed_id, hashed_user_id=user_id_hash,
            )
            chat_key_wrappers.extend(page["wrappers"])
            wrapper_windows[chat_id] = {
                "has_more_before": page["has_more_before"],
                "start_cursor": page["start_cursor"],
                "oversized_wrapper_id": page["oversized_wrapper_id"],
            }

        response_payload_data: Dict[str, Any] = {
            "messages_by_chat_id": messages_by_chat_id,
            "message_windows_by_chat_id": message_windows_by_chat_id,
            "embed_windows_by_chat_id": embed_windows_by_chat_id,
            "versions_by_chat_id": versions_by_chat_id,
            "compression_checkpoints_by_chat_id": compression_checkpoints_by_chat_id,
            "embeds": all_embeds,
            "embed_keys": all_embed_keys,
            "embed_key_windows_by_chat_id": embed_key_windows_by_chat_id,
            "chat_key_wrappers": chat_key_wrappers,
            "chat_key_wrapper_windows_by_chat_id": wrapper_windows,
            "code_run_outputs": code_run_outputs,
            "code_run_output_windows_by_chat_id": code_windows,
            "notebook_run_outputs": notebook_run_outputs,
            "notebook_run_output_windows_by_chat_id": notebook_windows,
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
