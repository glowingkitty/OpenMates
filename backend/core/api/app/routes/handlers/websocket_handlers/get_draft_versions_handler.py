# backend/core/api/app/routes/handlers/websocket_handlers/get_draft_versions_handler.py
#
# Handles the 'get_draft_versions' WebSocket message sent by the client on reconnect.
#
# Purpose:
#   When a client reconnects after being offline (or after a cold start), it asks the
#   server "which of these chats still have an active draft?". The server replies with
#   the current server-side draft_v for each requested chat_id. The client compares
#   against its locally-stored draft_v values:
#
#     - server draft_v == 0 (or missing) and client draft_v > 0
#       → the draft was deleted on another device while this device was offline.
#         The client must clear the local draft so it stops showing as a draft in the
#         chat list.
#
#     - server draft_v == client draft_v
#       → in sync, nothing to do.
#
#     - server draft_v > client draft_v
#       → the draft was updated on another device. The normal sync flow (initial_sync /
#         phased_sync) will deliver the newer draft content. This handler does not push
#         content; it only sends back version numbers.
#
# This is a zero-knowledge-safe operation: draft content is NOT returned here — only
# integer version numbers. The client uses the versions to decide whether to issue a
# further fetch or clear its local state.
#
# Request payload (client → server):
#   {
#     "type": "get_draft_versions",
#     "payload": {
#       "chats": [
#         { "chat_id": "<uuid>", "client_draft_v": 3 },
#         ...
#       ]
#     }
#   }
#
# Response payload (server → client):
#   {
#     "type": "draft_versions_response",
#     "payload": {
#       "versions": {
#         "<chat_id>": 3,   # current server draft_v (0 = no draft)
#         ...
#       }
#     }
#   }

import logging
import hashlib
from typing import Dict, Any, List

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Maximum number of chats we will look up in a single request to prevent abuse.
MAX_CHATS_PER_REQUEST = 200


async def get_authoritative_user_draft(
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    chat_id: str,
):
    """Read a draft cache-first, falling back to its encrypted Directus row."""
    cached = await cache_service.get_user_draft_from_cache(user_id=user_id, chat_id=chat_id)
    cached_version_int = 0
    if cached is not None:
        cached_md, cached_version, cached_preview = cached
        try:
            cached_version_int = int(cached_version or 0)
        except (TypeError, ValueError):
            cached_version_int = 0
        if cached_md is not None and cached_md != "null" and cached_version_int > 0:
            return cached
        logger.info(
            "Ignoring empty cached draft for user %s, chat %s until Directus fallback is checked.",
            user_id,
            chat_id,
        )
    else:
        cached_md = None
        cached_version = 0

    rows = await directus_service.get_items(
        "drafts",
        params={
            "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(),
            "filter[chat_id][_eq]": chat_id,
            "fields": "encrypted_content,version",
            "limit": 1,
        },
        admin_required=True,
    )
    if not rows:
        return None
    row = rows[0]
    draft_version = int(row.get("version") or 0)
    encrypted_content = row.get("encrypted_content")
    if not encrypted_content or draft_version <= 0 or draft_version < cached_version_int:
        return None
    draft = (encrypted_content, draft_version, None)
    await cache_service.update_user_draft_in_cache(
        user_id,
        chat_id,
        draft[0],
        draft[1],
        encrypted_draft_preview=None,
    )
    return draft


async def handle_get_draft_versions(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,) -> None:
    """
    Respond to a 'get_draft_versions' request with the server-side draft_v for each
    requested chat. Called on client reconnect to detect stale local drafts.
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("get_draft_versions", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        chats: List[Dict[str, Any]] = payload.get("chats", [])

        if not chats:
            logger.debug(
                f"User {user_id}: get_draft_versions received with empty chats list — sending empty response."
            )
            await websocket.send_json(
                {"type": "draft_versions_response", "payload": {"versions": {}}}
            )
            return

        if len(chats) > MAX_CHATS_PER_REQUEST:
            logger.warning(
                f"User {user_id}: get_draft_versions request contains {len(chats)} chats "
                f"(max {MAX_CHATS_PER_REQUEST}). Truncating."
            )
            chats = chats[:MAX_CHATS_PER_REQUEST]

        logger.info(
            f"User {user_id}: get_draft_versions requested for {len(chats)} chat(s)."
        )

        versions: Dict[str, int] = {}
        unavailable_chat_ids: List[str] = []

        for chat_entry in chats:
            chat_id = chat_entry.get("chat_id")
            if not chat_id or not isinstance(chat_id, str):
                continue

            try:
                # get_user_draft_from_cache returns (encrypted_draft_md, draft_v, encrypted_draft_preview) or None.
                # We only need the version — content and preview are not sent here.
                draft_cache_result = await get_authoritative_user_draft(
                    cache_service,
                    directus_service,
                    user_id,
                    chat_id,
                )
                if draft_cache_result:
                    _, server_draft_v, _ = draft_cache_result
                    versions[chat_id] = server_draft_v if server_draft_v else 0
                else:
                    # No draft entry in Redis → draft_v = 0 (draft was deleted or never saved)
                    versions[chat_id] = 0
            except Exception as e:
                logger.error(
                    f"User {user_id}: Error fetching draft version for chat {chat_id}: {e}",
                    exc_info=True,
                )
                # A cache failure is not authoritative deletion evidence. Omitting
                # the version keeps valid local drafts until a later successful sync.
                unavailable_chat_ids.append(chat_id)

        logger.info(
            f"User {user_id}: Responding to get_draft_versions with {len(versions)} version(s)."
        )

        await websocket.send_json(
            {
                "type": "draft_versions_response",
                "payload": {
                    "versions": versions,
                    "unavailable_chat_ids": unavailable_chat_ids,
                },
            }
        )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
