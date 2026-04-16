"""
message_highlight_handlers.py

Handles the three client→server WS ops for message highlights/annotations:
  - add_message_highlight     → INSERT row into message_highlights
  - update_message_highlight  → UPDATE encrypted_payload (author-only)
  - remove_message_highlight  → DELETE row (author-only)

Architecture:
  - The `encrypted_payload` column is client-side encrypted with the chat key —
    the server never decrypts it. The server only enforces plaintext auth
    metadata: chat ownership for inserts, and author-only for edits/deletes.
  - Broadcast goes to the author's own connected devices. Other viewers of a
    shared chat pick up the changes via the next phased sync when they open
    the chat (no real-time cross-user fan-out in v1).
  - Persistence to Directus happens synchronously (quick single-row writes) so
    we don't need a separate Celery task.

See plans/when-a-user-is-fuzzy-turing.md for the full design.
"""
import logging
from typing import Dict, Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

COLLECTION = "message_highlights"


async def _verify_chat_accessible(
    directus_service: DirectusService,
    chat_id: str,
    user_id: str,
) -> bool:
    """
    Return True if the user is allowed to annotate this chat.

    Rules:
      - User owns the chat → allowed.
      - Chat doesn't exist in Directus yet → treat as local-only chat (allowed).
      - Otherwise (someone else's chat) → rejected.

    Shared-chat annotation is not enabled in v1 for cross-user writes; only the
    owner can add/edit/remove highlights. Viewers can still see them via sync.
    """
    try:
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if is_owner:
            return True
        metadata = await directus_service.chat.get_chat_metadata(chat_id)
        return metadata is None  # local-only chat
    except Exception as e:  # pragma: no cover — defensive
        logger.error(
            "[message_highlights] ownership check failed chat=%s user=%s err=%s",
            chat_id, user_id, e, exc_info=True,
        )
        return False


async def _load_existing_highlight(
    directus_service: DirectusService,
    highlight_id: str,
) -> Dict[str, Any]:
    """Fetch a highlight row by primary key. Returns {} if not found."""
    items = await directus_service.get_items(
        COLLECTION,
        params={
            "filter[id][_eq]": highlight_id,
            "limit": 1,
            "fields": "id,chat_id,message_id,author_user_id",
        },
        admin_required=True,
    ) or []
    return items[0] if items else {}


async def handle_add_message_highlight(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,  # noqa: ARG001 — reserved for future caching
    directus_service: DirectusService,
    encryption_service: EncryptionService,  # noqa: ARG001
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
):
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    highlight_id = payload.get("id")
    author_user_id = payload.get("author_user_id")
    encrypted_payload = payload.get("encrypted_payload")
    created_at = payload.get("created_at")
    key_version = payload.get("key_version")

    if not all([chat_id, message_id, highlight_id, encrypted_payload, created_at is not None]):
        logger.warning(
            "[message_highlights] add missing fields user=%s payload_keys=%s",
            user_id, list(payload.keys()),
        )
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing fields for add_message_highlight"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    # Author is always the sender — ignore any client-supplied author_user_id
    # that disagrees with the authenticated session.
    author_user_id = user_id

    if not await _verify_chat_accessible(directus_service, chat_id, user_id):
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "You do not have permission to annotate this chat.",
                "chat_id": chat_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    row = {
        "id": highlight_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "author_user_id": author_user_id,
        "key_version": key_version,
        "encrypted_payload": encrypted_payload,
        "created_at": int(created_at),
        "updated_at": int(created_at),
    }
    try:
        await directus_service.create_item(COLLECTION, row, admin_required=True)
    except Exception as e:
        logger.error("[message_highlights] INSERT failed id=%s err=%s", highlight_id, e, exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "Failed to save highlight",
                "highlight_id": highlight_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    # Broadcast to author's own devices (other viewers sync on next reload).
    await manager.broadcast_to_user(
        {
            "type": "message_highlight_added",
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "id": highlight_id,
                "author_user_id": author_user_id,
                "key_version": key_version,
                "encrypted_payload": encrypted_payload,
                "created_at": int(created_at),
            },
        },
        user_id,
        exclude_device_hash=None,
    )
    logger.info(
        "[message_highlights] added id=%s chat=%s message=%s user=%s",
        highlight_id, chat_id, message_id, user_id,
    )


async def handle_update_message_highlight(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,  # noqa: ARG001
    directus_service: DirectusService,
    encryption_service: EncryptionService,  # noqa: ARG001
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
):
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    highlight_id = payload.get("id")
    encrypted_payload = payload.get("encrypted_payload")
    updated_at = payload.get("updated_at")

    if not all([chat_id, message_id, highlight_id, encrypted_payload, updated_at is not None]):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing fields for update_message_highlight"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    existing = await _load_existing_highlight(directus_service, highlight_id)
    if not existing:
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "Highlight not found",
                "highlight_id": highlight_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return
    if existing.get("author_user_id") != user_id:
        logger.warning(
            "[message_highlights] update rejected — not author id=%s user=%s author=%s",
            highlight_id, user_id, existing.get("author_user_id"),
        )
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "Only the author may edit this highlight.",
                "highlight_id": highlight_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    try:
        await directus_service.update_item(
            COLLECTION,
            highlight_id,
            {
                "encrypted_payload": encrypted_payload,
                "updated_at": int(updated_at),
            },
        )
    except Exception as e:
        logger.error("[message_highlights] UPDATE failed id=%s err=%s", highlight_id, e, exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "Failed to update highlight",
                "highlight_id": highlight_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    await manager.broadcast_to_user(
        {
            "type": "message_highlight_updated",
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "id": highlight_id,
                "encrypted_payload": encrypted_payload,
                "updated_at": int(updated_at),
            },
        },
        user_id,
        exclude_device_hash=None,
    )


async def handle_remove_message_highlight(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,  # noqa: ARG001
    directus_service: DirectusService,
    encryption_service: EncryptionService,  # noqa: ARG001
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
):
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    highlight_id = payload.get("id")

    if not all([chat_id, message_id, highlight_id]):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing fields for remove_message_highlight"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    existing = await _load_existing_highlight(directus_service, highlight_id)
    if existing and existing.get("author_user_id") != user_id:
        logger.warning(
            "[message_highlights] delete rejected — not author id=%s user=%s",
            highlight_id, user_id,
        )
        await manager.send_personal_message(
            message={"type": "error", "payload": {
                "message": "Only the author may remove this highlight.",
                "highlight_id": highlight_id,
            }},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    try:
        await directus_service.delete_item(COLLECTION, highlight_id)
    except Exception as e:
        logger.error("[message_highlights] DELETE failed id=%s err=%s", highlight_id, e, exc_info=True)
        # Continue — we still want to broadcast removal locally so UIs catch up.

    await manager.broadcast_to_user(
        {
            "type": "message_highlight_removed",
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "id": highlight_id,
            },
        },
        user_id,
        exclude_device_hash=None,
    )
