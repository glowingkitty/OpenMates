# backend/core/api/app/routes/handlers/websocket_handlers/delete_app_settings_memories_handler.py
"""
Handler for deleting app settings/memories entries across all devices.

When a client deletes a memory entry:
1. Client sends delete event with the entry ID
2. Server deletes the entry from Directus
3. Server broadcasts deletion to all other logged-in devices for cross-device sync

Zero-knowledge: the server only uses the entry ID (UUID) for deletion — it
never needs to decrypt or inspect the entry content.

Architecture doc: docs/architecture/openmates-cli.md
Tests: backend/tests/test_rest_api_memories.py
"""

import logging
import hashlib
from typing import Dict, Any

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def handle_delete_app_settings_memories_entry(
    websocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Handle deletion of an app settings/memories entry.

    Validates ownership (entry must belong to the requesting user via
    hashed_user_id), deletes from Directus, then broadcasts the deletion
    event to all other logged-in devices so their IndexedDB stays in sync.

    Args:
        websocket: WebSocket connection
        manager: ConnectionManager instance
        cache_service: CacheService instance
        directus_service: DirectusService instance
        user_id: Authenticated user ID
        device_fingerprint_hash: Source device fingerprint hash
        payload: Must contain { entry_id: str }
    """
    try:
        entry_id = payload.get("entry_id")
        if not entry_id or not isinstance(entry_id, str):
            logger.warning(
                "[DeleteAppSettingsMemories] Missing entry_id from user %s", user_id[:8]
            )
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing entry_id"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        # Verify the entry belongs to this user before deleting (zero-knowledge
        # ownership check — we compare hashed_user_id, never decrypt content).
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        existing = await directus_service.get_items(
            "user_app_settings_and_memories",
            params={
                "filter": {
                    "id": {"_eq": entry_id},
                    "hashed_user_id": {"_eq": hashed_user_id},
                },
                "limit": 1,
                "fields": ["id", "app_id", "item_type"],
            },
        )

        if not existing:
            logger.warning(
                "[DeleteAppSettingsMemories] Entry %s not found or not owned by user %s",
                entry_id,
                user_id[:8],
            )
            await manager.send_personal_message(
                {
                    "type": "error",
                    "payload": {"message": "Entry not found or access denied"},
                },
                user_id,
                device_fingerprint_hash,
            )
            return

        entry_meta = existing[0]
        app_id = entry_meta.get("app_id")
        item_type = entry_meta.get("item_type")

        await directus_service.delete_item("user_app_settings_and_memories", entry_id)
        logger.info(
            "[DeleteAppSettingsMemories] Deleted entry %s for user %s (app=%s, type=%s)",
            entry_id,
            user_id[:8],
            app_id,
            item_type,
        )

        # ACK to the source device
        await manager.send_personal_message(
            {
                "type": "app_settings_memories_entry_deleted",
                "payload": {
                    "entry_id": entry_id,
                    "app_id": app_id,
                    "item_type": item_type,
                    "success": True,
                },
            },
            user_id,
            device_fingerprint_hash,
        )

        # Broadcast deletion to all other devices so they remove from IndexedDB
        await manager.broadcast_to_user(
            message={
                "type": "app_settings_memories_entry_deleted",
                "payload": {
                    "entry_id": entry_id,
                    "app_id": app_id,
                    "item_type": item_type,
                    "success": True,
                },
            },
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )

    except Exception as e:
        logger.error(
            "[DeleteAppSettingsMemories] Error for user %s: %s",
            user_id[:8],
            e,
            exc_info=True,
        )
        try:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "payload": {"message": "Failed to delete entry"},
                },
                user_id,
                device_fingerprint_hash,
            )
        except Exception as send_err:
            logger.error(
                "[DeleteAppSettingsMemories] Failed to send error message: %s", send_err
            )
