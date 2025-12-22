# backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py
import logging
import json
from typing import Dict, Any
from datetime import datetime, timezone

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.tasks.celery_config import app as celery_app

logger = logging.getLogger(__name__)


async def handle_ai_response_completed(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles completed AI response sent from client for encrypted Directus storage.
    This is part of the zero-knowledge architecture where:
    1. Client encrypts the completed AI response
    2. Client sends only encrypted content to server (no plaintext)
    3. Server stores encrypted content in Directus without decryption
    4. Server NEVER encrypts AI responses - that's the client's job
    """
    try:
        chat_id = payload.get("chat_id")
        message_payload_from_client = payload.get("message")
        versions = payload.get("versions")  # Get version info for multi-device sync

        if not chat_id or not message_payload_from_client or not isinstance(message_payload_from_client, dict):
            logger.error(f"Invalid AI response payload structure from {user_id}/{device_fingerprint_hash}: {payload}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid AI response payload structure"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Extract message details
        message_id = message_payload_from_client.get("message_id")
        role = message_payload_from_client.get("role")
        encrypted_content = message_payload_from_client.get("encrypted_content")
        encrypted_sender_name = message_payload_from_client.get("encrypted_sender_name")
        encrypted_category = message_payload_from_client.get("encrypted_category")
        encrypted_model_name = message_payload_from_client.get("encrypted_model_name")
        created_at = message_payload_from_client.get("created_at")
        user_message_id = message_payload_from_client.get("user_message_id")

        # Validate required fields
        if not all([message_id, role, encrypted_content, created_at]):
            logger.error(f"Missing required fields in AI response from {user_id}/{device_fingerprint_hash}: {message_payload_from_client}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing required fields in AI response"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Validate that this is an AI response
        if role != "assistant":
            logger.error(f"Invalid role '{role}' for AI response from {user_id}/{device_fingerprint_hash}. Expected 'assistant'.")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid role for AI response"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Validate that only encrypted content is provided (zero-knowledge architecture)
        if message_payload_from_client.get("content"):
            logger.warning(f"Client sent plaintext content in AI response for {user_id}/{device_fingerprint_hash}. This violates zero-knowledge architecture.")
            # Remove plaintext content to enforce zero-knowledge
            message_payload_from_client = {k: v for k, v in message_payload_from_client.items() if k != "content"}

        logger.info(f"Received completed AI response for storage: chat_id={chat_id}, message_id={message_id}, user_id={user_id}")

        # Create message data for Directus storage (encrypted only)
        message_data_for_directus = {
            "message_id": message_id,
            "chat_id": chat_id,
            "role": role,
            "encrypted_content": encrypted_content,
            "created_at": created_at,
            "status": "synced"
        }

        # Add optional encrypted fields if present
        if encrypted_sender_name:
            message_data_for_directus["encrypted_sender_name"] = encrypted_sender_name
        if encrypted_category:
            message_data_for_directus["encrypted_category"] = encrypted_category
        if encrypted_model_name:
            message_data_for_directus["encrypted_model_name"] = encrypted_model_name
        if user_message_id:
            message_data_for_directus["user_message_id"] = user_message_id

        # user_id_hash is already provided from the WebSocket context

        # Send task to Celery to persist encrypted AI response to Directus
        # CRITICAL: Server never encrypts AI responses - client sends pre-encrypted content
        # Pass versions for multi-device deduplication
        task_result = celery_app.send_task(
            name="app.tasks.persistence_tasks.persist_ai_response_to_directus",
            args=[user_id, user_id_hash, message_data_for_directus, versions],
            queue="persistence"
        )

        logger.info(f"Queued AI response persistence task {task_result.id} for message {message_id} in chat {chat_id}")

        # Send confirmation to client
        await manager.send_personal_message(
            {
                "type": "ai_response_storage_confirmed",
                "payload": {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "task_id": task_result.id
                }
            },
            user_id,
            device_fingerprint_hash
        )

        logger.debug(f"Sent AI response storage confirmation to {user_id}/{device_fingerprint_hash} for message {message_id}")

    except Exception as e:
        logger.error(f"Error handling AI response completion from {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to process AI response completion"}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as send_err:
            logger.error(f"Failed to send error message to {user_id}/{device_fingerprint_hash}: {send_err}")
