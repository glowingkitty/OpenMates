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
from typing import Dict, Any, List

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Maximum number of chats we will look up in a single request to prevent abuse.
MAX_CHATS_PER_REQUEST = 200


async def handle_get_draft_versions(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Respond to a 'get_draft_versions' request with the server-side draft_v for each
    requested chat. Called on client reconnect to detect stale local drafts.
    """
    chats: List[Dict[str, Any]] = payload.get("chats", [])

    if not chats:
        logger.debug(
            f"User {user_id}: get_draft_versions received with empty chats list — sending empty response."
        )
        await manager.send_personal_message(
            message={"type": "draft_versions_response", "payload": {"versions": {}}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
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

    for chat_entry in chats:
        chat_id = chat_entry.get("chat_id")
        if not chat_id or not isinstance(chat_id, str):
            continue

        try:
            # get_user_draft_from_cache returns (encrypted_draft_md, draft_v, encrypted_draft_preview) or None.
            # We only need the version — content and preview are not sent here.
            draft_cache_result = await cache_service.get_user_draft_from_cache(
                user_id=user_id, chat_id=chat_id
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
            # On error, report 0 so the client doesn't retain a potentially stale draft.
            # The client will clear the draft which is the safer outcome.
            versions[chat_id] = 0

    logger.info(
        f"User {user_id}: Responding to get_draft_versions with {len(versions)} version(s)."
    )

    await manager.send_personal_message(
        message={"type": "draft_versions_response", "payload": {"versions": versions}},
        user_id=user_id,
        device_fingerprint_hash=device_fingerprint_hash,
    )
