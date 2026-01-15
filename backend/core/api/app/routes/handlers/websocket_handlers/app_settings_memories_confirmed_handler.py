# backend/core/api/app/routes/handlers/websocket_handlers/app_settings_memories_confirmed_handler.py
"""
Handler for app settings/memories confirmation from client.

When user confirms app settings/memories request:
1. Client sends decrypted app settings/memories data (like embeds)
2. Server encrypts with vault key and stores in cache
3. Server loads the pending request context
4. Server triggers a NEW ask_skill task to continue processing
5. The new task finds the data in cache and generates the LLM response

This treats confirmation/rejection as a trigger for re-processing the original
user message, rather than waiting/blocking the original task.
"""

import logging
import time
import json
import os
import yaml
from datetime import datetime, timezone
from typing import Dict, Any, List
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


def _load_ask_skill_config_from_app_yml() -> Dict[str, Any]:
    """
    Load the 'ask' skill's configuration from the AI app's app.yml.
    
    This includes the default_llms, preprocessing_thresholds, and always_include_skills
    that are needed for the task to function correctly.
    
    Returns:
        Dictionary containing the skill_config for the 'ask' skill, or an empty dict
        with a warning if loading fails.
    """
    # Find the AI app's directory relative to this file
    # This handler is at: backend/core/api/app/routes/handlers/websocket_handlers/
    # AI app.yml is at: backend/apps/ai/app.yml
    # Path traversal:
    #   websocket_handlers/ (1) → handlers/ (2) → routes/ (3) → app/ (4) → 
    #   api/ (5) → core/ (6) → backend/ (7)
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up 7 levels to get to 'backend', then down to 'apps/ai'
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file_dir))))))
    app_yml_path = os.path.join(backend_dir, "apps", "ai", "app.yml")
    
    if not os.path.exists(app_yml_path):
        logger.error(f"AI app.yml not found at {app_yml_path} - using empty skill config")
        return {}
    
    try:
        with open(app_yml_path, 'r', encoding='utf-8') as f:
            app_config = yaml.safe_load(f)
        
        if not app_config:
            logger.error(f"AI app.yml is empty or malformed at {app_yml_path}")
            return {}
        
        # Find the 'ask' skill and return its skill_config
        skills = app_config.get("skills", [])
        for skill in skills:
            if skill.get("id", "").strip() == "ask":
                skill_config = skill.get("skill_config", {})
                if skill_config:
                    logger.debug(f"Loaded ask skill config from app.yml: {list(skill_config.keys())}")
                    return skill_config
                else:
                    logger.warning("Ask skill found in app.yml but has no skill_config")
                    return {}
        
        logger.warning(f"Ask skill not found in AI app.yml at {app_yml_path}")
        return {}
        
    except Exception as e:
        logger.error(f"Error loading ask skill config from {app_yml_path}: {e}", exc_info=True)
        return {}


async def handle_app_settings_memories_confirmed(
    websocket,
    manager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles app settings/memories confirmation from client.
    
    This handler:
    1. Encrypts and caches the confirmed app settings/memories
    2. Loads the pending request context stored when the request was created
    3. Triggers a NEW ask_skill Celery task to continue processing
    4. Deletes the pending context
    
    The user does NOT need to send another message - the original message is
    re-processed with the app settings/memories now available in cache.
    
    Args:
        websocket: WebSocket connection
        manager: ConnectionManager instance
        cache_service: CacheService instance
        directus_service: DirectusService instance
        encryption_service: EncryptionService instance
        user_id: User ID
        device_fingerprint_hash: Device fingerprint hash
        payload: Payload containing chat_id and app_settings_memories array
    """
    try:
        chat_id = payload.get("chat_id")
        app_settings_memories = payload.get("app_settings_memories", [])
        
        if not chat_id:
            logger.warning(f"Invalid app_settings_memories payload from user {user_id}: missing chat_id")
            return
        
        # app_settings_memories can be empty if user rejected all categories
        # We still need to continue processing (without the data)
        is_rejection = not app_settings_memories or not isinstance(app_settings_memories, list) or len(app_settings_memories) == 0
        
        if is_rejection:
            logger.info(f"User {user_id} rejected all app settings/memories for chat {chat_id} - will continue processing without data")
        else:
            # Cache the confirmed app settings/memories
            await _cache_app_settings_memories(
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service,
                manager=manager,
                user_id=user_id,
                chat_id=chat_id,
                device_fingerprint_hash=device_fingerprint_hash,
                app_settings_memories=app_settings_memories
            )
        
        # Load the pending request context and trigger re-processing
        await _trigger_continuation(
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id=user_id,
            chat_id=chat_id,
            device_fingerprint_hash=device_fingerprint_hash,
            is_rejection=is_rejection
        )
        
    except Exception as e:
        logger.error(f"Error handling app settings/memories confirmation for user {user_id}: {e}", exc_info=True)


async def _cache_app_settings_memories(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager,
    user_id: str,
    chat_id: str,
    device_fingerprint_hash: str,
    app_settings_memories: list
) -> int:
    """
    Cache app settings/memories entries with vault encryption.
    
    Returns:
        Number of entries successfully cached
    """
    # Get user's vault_key_id (try cache first, fallback to Directus)
    user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not user_vault_key_id:
        logger.debug(f"vault_key_id not in cache for user {user_id}, fetching from Directus")
        try:
            user_profile_result = await directus_service.get_user_profile(user_id)
            if not user_profile_result or not user_profile_result[0]:
                logger.error(f"Failed to fetch user profile for encryption: {user_id}")
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: user profile not found"}},
                    user_id,
                    device_fingerprint_hash
                )
                return 0
            
            user_vault_key_id = user_profile_result[1].get("vault_key_id")
            if not user_vault_key_id:
                logger.error(f"User {user_id} missing vault_key_id in Directus profile")
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: encryption key not found"}},
                    user_id,
                    device_fingerprint_hash
                )
                return 0
            
            # Cache the vault_key_id for future use
            await cache_service.update_user(user_id, {"vault_key_id": user_vault_key_id})
            logger.debug(f"Cached vault_key_id for user {user_id}")
        except Exception as e_profile:
            logger.error(f"Error fetching user profile for encryption: {e_profile}", exc_info=True)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to encrypt app settings/memories: profile error"}},
                user_id,
                device_fingerprint_hash
            )
            return 0
    
    logger.info(f"Caching {len(app_settings_memories)} app settings/memories confirmations for chat {chat_id} from user {user_id}")
    
    # DEBUG: Log the raw items received from client
    for i, item in enumerate(app_settings_memories):
        logger.info(f"[DEBUG] Caching item {i}: app_id={item.get('app_id')!r}, item_key={item.get('item_key')!r}")
    
    # Group entries by app_id:item_key (category) since multiple entries can share the same category
    # e.g., "preferred_tech" category might have entries for "Python" and "Svelte 5"
    # We aggregate all entries per category into a single cache entry with an array of contents
    from collections import defaultdict
    entries_by_category: Dict[str, List[Any]] = defaultdict(list)
    
    for item in app_settings_memories:
        app_id = item.get("app_id")
        item_key = item.get("item_key")  # This is the category name (e.g., "preferred_tech")
        content = item.get("content")  # Decrypted content from client
        
        if not app_id or not item_key or content is None:
            logger.warning("Invalid app settings/memories item: missing required fields")
            continue
        
        category_key = f"{app_id}:{item_key}"
        entries_by_category[category_key].append({
            "app_id": app_id,
            "item_key": item_key,
            "content": content
        })
    
    logger.info(f"Grouped {len(app_settings_memories)} entries into {len(entries_by_category)} categories")
    
    cached_count = 0
    for category_key, entries in entries_by_category.items():
        try:
            # Extract app_id and item_key from the first entry (all entries in group share same values)
            app_id = entries[0]["app_id"]
            item_key = entries[0]["item_key"]
            
            # Aggregate all contents into a list
            all_contents = [entry["content"] for entry in entries]
            
            # Serialize the aggregated content as JSON
            import json as json_module
            aggregated_content_str = json_module.dumps(all_contents)
            
            # Encrypt aggregated content with vault key for server cache
            # Server can decrypt for AI context building
            # encrypt_with_user_key returns (ciphertext, key_version) tuple
            encrypted_content, _ = await encryption_service.encrypt_with_user_key(
                plaintext=aggregated_content_str,
                key_id=user_vault_key_id
            )
            
            # Prepare cache data (vault-encrypted)
            cache_data = {
                "app_id": app_id,
                "item_key": item_key,
                "content": encrypted_content,  # Vault-encrypted aggregated content (JSON array)
                "entry_count": len(entries),  # Track how many entries were aggregated
                "cached_at": int(time.time())
            }
            
            # Store in cache (chat-specific, similar to embeds)
            success = await cache_service.set_app_settings_memories_in_cache(
                user_id=user_id,
                chat_id=chat_id,
                app_id=app_id,
                item_key=item_key,
                data=cache_data,
                ttl=86400  # 24 hours, same as message cache
            )
            
            if success:
                cached_count += 1
                logger.info(f"Cached {len(entries)} entries for category {app_id}:{item_key} in chat {chat_id}")
            else:
                logger.warning(f"Failed to cache app settings/memories {app_id}:{item_key} for chat {chat_id}")
                
        except Exception as e:
            logger.error(f"Error processing app settings/memories category {category_key}: {e}", exc_info=True)
            continue
    
    logger.info(f"Successfully cached {cached_count}/{len(entries_by_category)} categories for chat {chat_id}")
    return cached_count


async def _trigger_continuation(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    chat_id: str,
    device_fingerprint_hash: str,
    is_rejection: bool
) -> None:
    """
    Load pending request context and trigger a new ask_skill task.
    
    This re-processes the original user message, but this time the app
    settings/memories are available in cache (if confirmed) or processing
    continues without them (if rejected).
    
    NOTE: We only store minimal context in the pending request - NOT the message_history.
    The chat history is retrieved from the existing AI cache (vault-encrypted messages).
    
    Args:
        cache_service: CacheService instance
        directus_service: DirectusService instance
        encryption_service: EncryptionService instance
        user_id: User ID
        chat_id: Chat ID
        device_fingerprint_hash: Device fingerprint hash
        is_rejection: True if user rejected all categories
    """
    # Load the pending request context (minimal - no message_history)
    pending_context = await cache_service.get_pending_app_settings_memories_request(chat_id)
    
    if not pending_context:
        logger.warning(f"No pending app settings/memories request found for chat {chat_id} - cannot continue processing")
        return
    
    original_task_id = pending_context.get("task_id", "unknown")
    message_id = pending_context.get("message_id")
    user_id_hash = pending_context.get("user_id_hash", "")
    mate_id = pending_context.get("mate_id")
    active_focus_id = pending_context.get("active_focus_id")
    chat_has_title = pending_context.get("chat_has_title", False)
    is_incognito = pending_context.get("is_incognito", False)
    # Get the requested keys from the pending context
    # These will be passed as app_settings_memories_metadata so preprocessing knows what's available
    requested_keys = pending_context.get("requested_keys", [])
    
    logger.info(
        f"Loaded pending context for chat {chat_id}: original_task_id={original_task_id}, "
        f"message_id={message_id}, is_rejection={is_rejection}, requested_keys={requested_keys}"
    )
    
    # Retrieve vault-encrypted messages from AI cache
    # The chat should be cached since it's a recent chat that triggered the request
    cached_messages_str_list = await cache_service.get_ai_messages_history(user_id, chat_id)
    
    if not cached_messages_str_list:
        logger.error(f"Failed to retrieve cached messages for chat {chat_id} - cannot continue processing")
        # Delete the pending context to avoid stale data
        await cache_service.delete_pending_app_settings_memories_request(chat_id)
        return
    
    # Get user's vault key for decryption
    user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not user_vault_key_id:
        logger.debug(f"vault_key_id not in cache for user {user_id}, fetching from Directus")
        try:
            user_profile_result = await directus_service.get_user_profile(user_id)
            if user_profile_result and user_profile_result[0]:
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
        except Exception as e_profile:
            logger.error(f"Error fetching user profile for decryption: {e_profile}", exc_info=True)
    
    if not user_vault_key_id:
        logger.error(f"Cannot decrypt messages without vault_key_id for user {user_id}")
        await cache_service.delete_pending_app_settings_memories_request(chat_id)
        return
    
    # Convert cached messages to the format expected by AskSkillRequest
    # Messages are stored newest first (LPUSH), so reverse for chronological order
    message_history: List[Dict[str, Any]] = []
    for msg_str in reversed(cached_messages_str_list):
        try:
            msg_cache_data = json.loads(msg_str)
            role = msg_cache_data.get("role", "")
            
            # Only include user and assistant messages (not system messages)
            if role not in ("user", "assistant"):
                continue
            
            # Decrypt the content using vault key
            encrypted_content = msg_cache_data.get("encrypted_content")
            if not encrypted_content:
                logger.debug(f"Cached message missing encrypted_content for chat {chat_id}, skipping")
                continue
            
            try:
                decrypted_content = await encryption_service.decrypt_with_user_key(
                    encrypted_content,
                    user_vault_key_id
                )
                if not decrypted_content:
                    logger.warning(f"Failed to decrypt message for chat {chat_id}, skipping")
                    continue
            except Exception as e_decrypt:
                logger.warning(f"Error decrypting message for chat {chat_id}: {e_decrypt}")
                continue
            
            message_history.append({
                "role": role,
                "content": decrypted_content,
                # created_at is required by AIHistoryMessage - get from cached message or use current time
                "created_at": msg_cache_data.get("created_at", int(datetime.now(timezone.utc).timestamp())),
                # Optional fields for full compatibility with AIHistoryMessage
                "sender_name": msg_cache_data.get("sender_name", role),
                "category": msg_cache_data.get("category"),
            })
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse cached message JSON for chat {chat_id}: {e}")
            continue
    
    if not message_history:
        logger.error(f"No user/assistant messages found in cached chat {chat_id} - cannot continue processing")
        await cache_service.delete_pending_app_settings_memories_request(chat_id)
        return
    
    logger.info(f"Retrieved and decrypted {len(message_history)} messages from AI cache for chat {chat_id}")
    
    # Delete the pending context (we're about to process it)
    await cache_service.delete_pending_app_settings_memories_request(chat_id)
    
    # Trigger a new ask_skill Celery task
    try:
        from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task
        
        # Build the request data dict
        # Convert requested_keys to app_settings_memories_metadata format
        # The keys are stored as "app_id:item_key" but the metadata format uses "app_id-item_key"
        app_settings_memories_metadata = []
        if requested_keys and not is_rejection:
            for key in requested_keys:
                # Keys are stored as "app_id:item_key", convert to "app_id-item_key" for metadata
                if ":" in key:
                    app_id, item_key = key.split(":", 1)
                    app_settings_memories_metadata.append(f"{app_id}-{item_key}")
                else:
                    app_settings_memories_metadata.append(key)
            logger.info(f"Passing {len(app_settings_memories_metadata)} app_settings_memories_metadata keys to continuation task: {app_settings_memories_metadata}")
        
        request_data_dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "message_history": message_history,
            "chat_has_title": chat_has_title,
            "is_incognito": is_incognito,
            "mate_id": mate_id,
            "active_focus_id": active_focus_id,
            # Pass the app_settings_memories_metadata so preprocessing knows what's available
            # This is CRITICAL: without this, preprocessing won't know to load the cached data
            "app_settings_memories_metadata": app_settings_memories_metadata if app_settings_memories_metadata else None,
            # Signal that this is a continuation after app settings/memories confirmation
            # This allows the task to skip storing another pending context if data
            # is still not in cache for some reason (avoids infinite loop)
            "is_app_settings_memories_continuation": True,
        }
        
        # Load the proper skill config from AI app's app.yml
        # This includes default_llms which is REQUIRED for preprocessing to work
        # The preprocessor accesses skill_config.default_llms.preprocessing_model
        skill_config_dict = _load_ask_skill_config_from_app_yml()
        
        if not skill_config_dict or "default_llms" not in skill_config_dict:
            logger.error(
                f"Failed to load ask skill config with default_llms from app.yml for chat {chat_id}. "
                "The continuation task may fail during preprocessing."
            )
        
        # Trigger the task with the original request parameters
        # The task will find app settings/memories in cache (if confirmed)
        # or process without them (if rejected)
        task = process_ai_skill_ask_task.apply_async(
            kwargs={
                "request_data_dict": request_data_dict,
                "skill_config_dict": skill_config_dict,
            },
            queue="app_ai",  # Route to the 'app_ai' queue
            exchange="app_ai",
            routing_key="app_ai"
        )
        
        action = "rejection" if is_rejection else "confirmation"
        logger.info(
            f"Triggered continuation task {task.id} for chat {chat_id} after app settings/memories {action} "
            f"(original task: {original_task_id})"
        )
        
    except Exception as e:
        logger.error(f"Failed to trigger continuation task for chat {chat_id}: {e}", exc_info=True)

