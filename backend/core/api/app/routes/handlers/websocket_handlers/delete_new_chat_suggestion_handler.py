# backend/core/api/app/routes/handlers/websocket_handlers/delete_new_chat_suggestion_handler.py
import logging
import hashlib
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_delete_new_chat_suggestion(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles deletion of a new chat suggestion when user explicitly deletes it from the UI.
    This is separate from the suggestion deletion that happens when a user clicks on a suggestion
    to start a new chat (which is handled in message_received_handler.py).

    Expected payload structure:
    {
        "encrypted_suggestion": "encrypted_suggestion_text"
    }
    """
    try:
        encrypted_suggestion_to_delete = payload.get("encrypted_suggestion")

        if not encrypted_suggestion_to_delete:
            logger.error(f"Missing encrypted_suggestion in delete_new_chat_suggestion payload from {user_id}/{device_fingerprint_hash}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing encrypted_suggestion in delete request"}},
                user_id,
                device_fingerprint_hash
            )
            return

        logger.info(f"User {user_id} requested deletion of new chat suggestion: {encrypted_suggestion_to_delete[:50]}...")

        # Hash user_id for database query
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

        # Query for the suggestion to get its ID
        query_params = {
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'filter[encrypted_suggestion][_eq]': encrypted_suggestion_to_delete,
            'fields': 'id',
            'limit': 1
        }

        suggestions = await directus_service.get_items('new_chat_suggestions', params=query_params)

        if suggestions and len(suggestions) > 0:
            suggestion_id = suggestions[0].get('id')
            if suggestion_id:
                # Delete the suggestion using its ID
                delete_success = await directus_service.delete_item('new_chat_suggestions', suggestion_id)

                if delete_success:
                    logger.info(f"✅ Successfully deleted new chat suggestion for user {user_id[:8]}... (ID: {suggestion_id})")

                    # Invalidate the cache so next sync fetches updated suggestions
                    await cache_service.delete_new_chat_suggestions(hashed_user_id)
                    logger.debug(f"Invalidated new chat suggestions cache for user {user_id[:8]}...")

                    # Send success confirmation to client
                    await manager.send_personal_message(
                        {
                            "type": "new_chat_suggestion_deleted",
                            "payload": {
                                "success": True,
                                "encrypted_suggestion": encrypted_suggestion_to_delete,
                                "message": "Suggestion deleted successfully"
                            }
                        },
                        user_id,
                        device_fingerprint_hash
                    )
                else:
                    logger.warning(f"Failed to delete suggestion {suggestion_id} for user {user_id[:8]}...")

                    await manager.send_personal_message(
                        {
                            "type": "error",
                            "payload": {
                                "message": "Failed to delete suggestion from database",
                                "encrypted_suggestion": encrypted_suggestion_to_delete
                            }
                        },
                        user_id,
                        device_fingerprint_hash
                    )
            else:
                logger.warning(f"Suggestion found but no ID present for user {user_id[:8]}...")

                await manager.send_personal_message(
                    {
                        "type": "error",
                        "payload": {
                            "message": "Suggestion found but missing ID",
                            "encrypted_suggestion": encrypted_suggestion_to_delete
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
        else:
            logger.warning(f"No matching suggestion found to delete for user {user_id[:8]}...")

            # Still send success to client since the suggestion doesn't exist anyway
            await manager.send_personal_message(
                {
                    "type": "new_chat_suggestion_deleted",
                    "payload": {
                        "success": True,
                        "encrypted_suggestion": encrypted_suggestion_to_delete,
                        "message": "Suggestion not found, already deleted"
                    }
                },
                user_id,
                device_fingerprint_hash
            )

    except Exception as e:
        logger.error(f"Failed to delete new chat suggestion for user {user_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            {
                "type": "error",
                "payload": {
                    "message": "Error deleting suggestion",
                    "error_details": str(e),
                    "encrypted_suggestion": payload.get("encrypted_suggestion")
                }
            },
            user_id,
            device_fingerprint_hash
        )