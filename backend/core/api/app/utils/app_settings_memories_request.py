# backend/core/api/app/utils/app_settings_memories_request.py
"""
Helper functions for requesting app settings/memories from the client.

This implements the zero-knowledge architecture where:
1. Server creates a system message in chat history with app settings/memories request (YAML structure)
2. Message is encrypted with chat-specific key (zero-knowledge)
3. Client decrypts request message from chat history
4. Client decrypts app settings/memories using crypto API (encryptWithMasterKey/decryptWithMasterKey)
5. Client shows user confirmation UI
6. Client updates the system message's YAML structure with responses
7. Server checks chat history on next message and extracts accepted responses

This approach allows requests to persist indefinitely (days/weeks), survive server restarts,
and work across all devices via chat history sync.
"""

import logging
import uuid
import yaml
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


def _create_request_yaml(requested_keys: List[str]) -> str:
    """
    Creates a YAML structure for app settings/memories request.
    
    Args:
        requested_keys: List of app settings/memories keys in "app_id-item_key" format
    
    Returns:
        YAML string containing the request structure
    """
    request_id = str(uuid.uuid4())
    timestamp = int(datetime.utcnow().timestamp())
    
    # Initialize all keys as pending
    responses = {
        key: {
            "status": "pending",
            "content": None
        }
        for key in requested_keys
    }
    
    request_data = {
        "app_settings_memories_request": {
            "request_id": request_id,
            "requested_keys": requested_keys,
            "status": "pending",
            "responses": responses,
            "created_at": timestamp
        }
    }
    
    return yaml.dump(request_data, default_flow_style=False, sort_keys=False)


def _parse_request_yaml(yaml_content: str) -> Optional[Dict[str, Any]]:
    """
    Parses YAML structure from a request message.
    
    Args:
        yaml_content: YAML string containing the request structure
    
    Returns:
        Dictionary with request data, or None if parsing fails
    """
    try:
        data = yaml.safe_load(yaml_content)
        return data.get("app_settings_memories_request")
    except Exception as e:
        logger.error(f"Error parsing app settings/memories request YAML: {e}", exc_info=True)
        return None


def _extract_accepted_responses(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts accepted responses from a request message's YAML structure.
    
    Args:
        request_data: Parsed request data from YAML
    
    Returns:
        Dictionary mapping "app_id-item_key" to decrypted values (only accepted ones)
    """
    accepted_responses = {}
    responses = request_data.get("responses", {})
    
    for key, response_info in responses.items():
        if response_info.get("status") == "accepted" and response_info.get("content") is not None:
            accepted_responses[key] = response_info["content"]
    
    return accepted_responses


async def check_chat_history_for_app_settings_memories(
    message_history: List[Dict[str, Any]],
    requested_keys: List[str]
) -> Dict[str, Any]:
    """
    Checks chat history for existing app settings/memories request messages.
    Extracts accepted responses from the most recent request.
    
    Args:
        message_history: List of messages in the chat (from AskSkillRequest)
        requested_keys: List of keys we're looking for
    
    Returns:
        Dictionary mapping "app_id-item_key" to decrypted values (only accepted ones)
    """
    accepted_responses = {}
    
    # Scan message history backwards (most recent first)
    for message in reversed(message_history):
        # Check if this is a system message with app_settings_memories_request
        if message.get("role") != "system":
            continue
        
        content = message.get("content", "")
        if not content or "app_settings_memories_request" not in content:
            continue
        
        # Parse the YAML structure
        request_data = _parse_request_yaml(content)
        if not request_data:
            continue
        
        # Check if this request includes any of the keys we need
        request_keys = request_data.get("requested_keys", [])
        if not any(key in request_keys for key in requested_keys):
            continue
        
        # Extract accepted responses
        extracted = _extract_accepted_responses(request_data)
        accepted_responses.update(extracted)
        
        # If we found a request with all needed keys accepted, we can stop
        # (though we might want to check if there's a more recent partial request)
        if all(key in accepted_responses for key in requested_keys):
            break
    
    return accepted_responses


async def create_app_settings_memories_request_message(
    chat_id: str,
    requested_keys: List[str],
    cache_service: CacheService,
    connection_manager: Optional[ConnectionManager],
    user_id: str,
    device_fingerprint_hash: Optional[str],
    message_id: Optional[str] = None
) -> Optional[str]:
    """
    Creates a system message request for app settings/memories in chat history.
    
    This function:
    1. Creates YAML structure for the request
    2. Sends YAML content to client via WebSocket
    3. Client encrypts with chat key and creates system message in chat history
    4. Message persists indefinitely in Directus (survives restarts, works across devices)
    
    Args:
        chat_id: Chat ID where the request should be stored
        requested_keys: List of app settings/memories keys in "app_id-item_key" format
        cache_service: Cache service (for WebSocket notifications via Redis pub/sub)
        connection_manager: WebSocket connection manager (may be None in Celery tasks)
        user_id: User ID
        device_fingerprint_hash: Device fingerprint hash (optional)
        message_id: The user's message ID that triggered this request (for UI display)
    
    Returns:
        Request ID if successful, None otherwise
    """
    try:
        # Create YAML structure
        yaml_content = _create_request_yaml(requested_keys)
        request_data = _parse_request_yaml(yaml_content)
        if not request_data:
            logger.error("Failed to parse created request YAML")
            return None
        
        request_id = request_data.get("request_id")
        logger.info(f"Creating app_settings_memories request {request_id} in chat {chat_id} with {len(requested_keys)} keys")
        
        # Send YAML content to client via WebSocket
        # Client will encrypt with chat key and create system message in chat history
        if connection_manager:
            try:
                user_connections = connection_manager.get_connections_for_user(user_id)
                if user_connections:
                    target_device = device_fingerprint_hash if (device_fingerprint_hash and device_fingerprint_hash in user_connections) else list(user_connections.keys())[0]
                    
                    await connection_manager.send_personal_message(
                        {
                            "type": "request_app_settings_memories",
                            "payload": {
                                "request_id": request_id,
                                "chat_id": chat_id,
                                "requested_keys": requested_keys,
                                "yaml_content": yaml_content,
                                "message_id": message_id  # User message that triggered this request
                            }
                        },
                        user_id,
                        target_device
                    )
                    logger.info(f"Sent app_settings_memories request {request_id} to user {user_id}, device {target_device} via WebSocket")
            except Exception as e:
                logger.error(f"Error sending WebSocket message for app_settings_memories request {request_id}: {e}", exc_info=True)
        else:
            # Use Redis pub/sub for Celery tasks
            try:
                redis_client = await cache_service.client
                if redis_client:
                    channel = f"user_cache_events:{user_id}"
                    pubsub_message = {
                        "event_type": "send_app_settings_memories_request",
                        "payload": {
                            "request_id": request_id,
                            "chat_id": chat_id,
                            "requested_keys": requested_keys,
                            "yaml_content": yaml_content,
                            "message_id": message_id  # User message that triggered this request
                        }
                    }
                    await redis_client.publish(channel, json.dumps(pubsub_message))
                    logger.info(f"Published app_settings_memories request {request_id} for user {user_id} via Redis pub/sub")
            except Exception as e:
                logger.warning(f"Could not publish WebSocket notification via Redis pub/sub for request {request_id}: {e}")
        
        return request_id
        
    except Exception as e:
        logger.error(f"Error creating app_settings_memories request message: {e}", exc_info=True)
        return None
