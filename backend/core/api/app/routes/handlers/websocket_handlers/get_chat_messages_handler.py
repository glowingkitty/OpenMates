# backend/core/api/app/routes/handlers/websocket_handlers/get_chat_messages_handler.py
# Purpose: Handles client requests to fetch messages for a specific chat.
import logging
from typing import Dict, Any, List

from fastapi import WebSocket

from app.services.directus import DirectusService, chat_methods
from app.utils.encryption import EncryptionService
from app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_get_chat_messages(
    websocket: WebSocket,
    manager: ConnectionManager,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str, # Authenticated user ID
    device_fingerprint_hash: str, # For sending response to the correct device
    payload: Dict[str, Any]
):
    """
    Handles a client's request to fetch all messages for a specific chat.
    Messages are decrypted before being sent.
    """
    chat_id = payload.get("chat_id")

    if not chat_id:
        logger.warning(f"User {user_id}/{device_fingerprint_hash} sent get_chat_messages with missing chat_id.")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chat_id for get_chat_messages request."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"User {user_id}/{device_fingerprint_hash} requesting messages for chat_id: {chat_id}")

    try:
        # Fetch and decrypt messages
        # get_all_messages_for_chat returns List[Dict[str, Any]] when decrypt_content=True
        messages: List[Dict[str, Any]] = await chat_methods.get_all_messages_for_chat(
            directus_service=directus_service,
            encryption_service=encryption_service,
            chat_id=chat_id,
            decrypt_content=True
        )

        if messages is None: # Indicates an error during fetching/decryption in chat_methods
            logger.error(f"Failed to retrieve or decrypt messages for chat {chat_id} for user {user_id}.")
            await manager.send_personal_message(
                message={"type": "error", "payload": {"message": f"Failed to retrieve messages for chat {chat_id}."}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            return
        
        logger.info(f"Successfully fetched and decrypted {len(messages)} messages for chat {chat_id} for user {user_id}.")
        
        response_payload = {
            "chat_id": chat_id,
            "messages": messages
        }
        await manager.send_personal_message(
            message={"type": "chat_messages_response", "payload": response_payload},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )

    except Exception as e:
        logger.error(f"Error in handle_get_chat_messages for chat {chat_id}, user {user_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Server error while fetching messages for chat {chat_id}."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )