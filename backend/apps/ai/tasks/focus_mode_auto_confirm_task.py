# backend/apps/ai/tasks/focus_mode_auto_confirm_task.py
#
# Celery task that auto-confirms focus mode activation after a countdown delay.
#
# Architecture:
# When the AI calls activate_focus_mode, main_processor stores a pending context
# in Redis and schedules this task with countdown=6s (2s buffer over the 4s client
# countdown). If the user doesn't reject within that time, this task:
#   1. Atomically gets and deletes the pending context (GETDEL)
#   2. Activates focus mode (cache + Directus)
#   3. Pushes a focus_mode_activated event to the client via Redis pub/sub
#   4. Fires a new ask_skill Celery task with focus prompt injected
#
# If the user rejected first, the GETDEL returns None and we no-op.

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# Countdown delay in seconds — 2s buffer over the 4s client countdown
FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN = 6


def _load_ask_skill_config_from_app_yml() -> Dict[str, Any]:
    """
    Load the 'ask' skill's configuration from the AI app's app.yml.
    
    This includes the default_llms, preprocessing_thresholds, and always_include_skills
    that are needed for the continuation task to function correctly.
    
    Returns:
        Dictionary containing the skill_config for the 'ask' skill, or an empty dict
        with a warning if loading fails.
    """
    # Find the AI app's directory relative to this file
    # This task is at: backend/apps/ai/tasks/
    # AI app.yml is at: backend/apps/ai/app.yml
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    app_yml_path = os.path.join(os.path.dirname(current_file_dir), "app.yml")
    
    if not os.path.exists(app_yml_path):
        logger.error(f"[FOCUS_MODE] AI app.yml not found at {app_yml_path} - using empty skill config")
        return {}
    
    try:
        with open(app_yml_path, 'r', encoding='utf-8') as f:
            app_config = yaml.safe_load(f)
        
        if not app_config:
            logger.error(f"[FOCUS_MODE] AI app.yml is empty or malformed at {app_yml_path}")
            return {}
        
        skills = app_config.get("skills", [])
        for skill in skills:
            if skill.get("id", "").strip() == "ask":
                skill_config = skill.get("skill_config", {})
                if skill_config:
                    logger.debug(f"[FOCUS_MODE] Loaded ask skill config from app.yml: {list(skill_config.keys())}")
                    return skill_config
                else:
                    logger.warning("[FOCUS_MODE] Ask skill found in app.yml but has no skill_config")
                    return {}
        
        logger.warning(f"[FOCUS_MODE] Ask skill not found in AI app.yml at {app_yml_path}")
        return {}
        
    except Exception as e:
        logger.error(f"[FOCUS_MODE] Error loading ask skill config from {app_yml_path}: {e}", exc_info=True)
        return {}


async def _async_focus_mode_auto_confirm(
    chat_id: str,
    task_id: str
) -> None:
    """
    Async implementation of the focus mode auto-confirm logic.
    
    Steps:
    1. Atomically get+delete the pending focus activation context from Redis
    2. If context exists (user didn't reject):
       a. Activate focus mode in cache and Directus
       b. Push focus_mode_activated event to client via Redis pub/sub
       c. Rebuild message history from AI cache
       d. Fire a new ask_skill Celery task with focus prompt injected
    3. If context is None (user rejected first): no-op
    """
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.encryption_service import EncryptionService
    
    log_prefix = f"[FocusModeAutoConfirm][Task: {task_id[:8]}][Chat: {chat_id[:8]}]"
    
    cache_service = CacheService()
    
    # Step 1: Atomically get and delete the pending context
    # If the user rejected first, this returns None (race-safe via GETDEL)
    pending_context = await cache_service.get_and_delete_pending_focus_activation(chat_id)
    
    if not pending_context:
        logger.info(f"{log_prefix} No pending focus activation found — user likely rejected. No-op.")
        return
    
    focus_id = pending_context.get("focus_id")
    user_id = pending_context.get("user_id")
    user_id_hash = pending_context.get("user_id_hash", "")
    message_id = pending_context.get("message_id")
    mate_id = pending_context.get("mate_id")
    chat_has_title = pending_context.get("chat_has_title", False)
    is_incognito = pending_context.get("is_incognito", False)
    original_task_id = pending_context.get("task_id", "unknown")
    
    logger.info(
        f"{log_prefix} Auto-confirming focus mode '{focus_id}' for chat {chat_id} "
        f"(original task: {original_task_id})"
    )
    
    # Step 2a: Activate focus mode in cache and Directus
    encryption_service = EncryptionService()
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    
    encrypted_focus_id = None
    try:
        encrypted_focus_id = encryption_service.encrypt(focus_id)
        await cache_service.update_chat_active_focus_id(
            user_id=user_id,
            chat_id=chat_id,
            encrypted_focus_id=encrypted_focus_id
        )
        logger.info(f"{log_prefix} Activated focus mode in cache")
        
        # Persist to Directus via Celery task
        from backend.core.api.app.tasks.celery_config import app as celery_app_instance
        celery_app_instance.send_task(
            'app.tasks.persistence_tasks.persist_chat_active_focus_id',
            kwargs={
                "chat_id": chat_id,
                "encrypted_active_focus_id": encrypted_focus_id
            },
            queue='persistence'
        )
        logger.info(f"{log_prefix} Dispatched persistence task for focus_id")
    except Exception as e:
        logger.error(f"{log_prefix} Error activating focus mode in cache/Directus: {e}", exc_info=True)
        # Continue anyway — the continuation task can still work with active_focus_id set
    
    # Step 2b: Push focus_mode_activated event to client via Redis pub/sub
    # The WebSocket listener in websockets.py picks this up from the user_cache_events channel
    # and forwards it to the connected client
    try:
        redis_client = await cache_service.client
        if redis_client:
            channel = f"user_cache_events:{user_id}"
            event_payload = {
                "event_type": "focus_mode_activated",
                "payload": {
                    "chat_id": chat_id,
                    "focus_id": focus_id,
                    "encrypted_active_focus_id": encrypted_focus_id,
                }
            }
            await redis_client.publish(channel, json.dumps(event_payload))
            logger.info(f"{log_prefix} Published focus_mode_activated event to {channel}")
    except Exception as e:
        logger.error(f"{log_prefix} Error publishing focus_mode_activated event: {e}", exc_info=True)
    
    # Step 2c: Rebuild message history from AI cache
    # The chat should be cached since it's a recent chat that triggered the activation
    cached_messages_str_list = await cache_service.get_ai_messages_history(user_id, chat_id)
    
    if not cached_messages_str_list:
        logger.error(f"{log_prefix} Failed to retrieve cached messages for chat {chat_id} — cannot continue processing")
        return
    
    # Get user's vault key for decryption
    user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not user_vault_key_id:
        logger.debug(f"{log_prefix} vault_key_id not in cache, fetching from Directus")
        try:
            user_profile_result = await directus_service.get_user_profile(user_id)
            if user_profile_result and user_profile_result[0]:
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
        except Exception as e:
            logger.error(f"{log_prefix} Error fetching user profile: {e}", exc_info=True)
    
    if not user_vault_key_id:
        logger.error(f"{log_prefix} Cannot decrypt messages without vault_key_id")
        return
    
    # Decrypt cached messages
    message_history: List[Dict[str, Any]] = []
    for msg_str in reversed(cached_messages_str_list):
        try:
            msg_cache_data = json.loads(msg_str)
            role = msg_cache_data.get("role", "")
            
            if role not in ("user", "assistant"):
                continue
            
            encrypted_content = msg_cache_data.get("encrypted_content")
            if not encrypted_content:
                continue
            
            try:
                decrypted_content = await encryption_service.decrypt_with_user_key(
                    encrypted_content,
                    user_vault_key_id
                )
                if not decrypted_content:
                    continue
            except Exception:
                continue
            
            message_history.append({
                "role": role,
                "content": decrypted_content,
                "created_at": msg_cache_data.get("created_at", int(datetime.now(timezone.utc).timestamp())),
                "sender_name": msg_cache_data.get("sender_name", role),
                "category": msg_cache_data.get("category"),
            })
        except json.JSONDecodeError:
            continue
    
    if not message_history:
        logger.error(f"{log_prefix} No messages found in cached chat {chat_id}")
        return
    
    logger.info(f"{log_prefix} Retrieved and decrypted {len(message_history)} messages from AI cache")
    
    # Step 2d: Fire a new ask_skill Celery task with focus mode active
    try:
        from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task
        
        skill_config_dict = _load_ask_skill_config_from_app_yml()
        
        if not skill_config_dict or "default_llms" not in skill_config_dict:
            logger.error(f"{log_prefix} Failed to load ask skill config — continuation may fail")
        
        request_data_dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "message_history": message_history,
            "chat_has_title": chat_has_title,
            "is_incognito": is_incognito,
            "mate_id": mate_id,
            "active_focus_id": focus_id,  # Focus mode is NOW active for this continuation
            # Signal that this is a continuation after focus mode activation
            # The task should NOT re-persist the user message (it's already persisted)
            "is_focus_mode_continuation": True,
        }
        
        task = process_ai_skill_ask_task.apply_async(
            kwargs={
                "request_data_dict": request_data_dict,
                "skill_config_dict": skill_config_dict,
            },
            queue="app_ai",
            exchange="app_ai",
            routing_key="app_ai"
        )
        
        logger.info(
            f"{log_prefix} Fired continuation task {task.id} with focus mode '{focus_id}' active "
            f"(original task: {original_task_id})"
        )
    except Exception as e:
        logger.error(f"{log_prefix} Failed to fire continuation task: {e}", exc_info=True)


@app.task(
    name="apps.ai.tasks.focus_mode_auto_confirm",
    bind=True,
    max_retries=0,  # No retries — if it fails, user can trigger again on next message
    soft_time_limit=60,
    time_limit=90,
)
def focus_mode_auto_confirm_task(self, chat_id: str):
    """
    Celery task that auto-confirms focus mode activation after the countdown.
    
    Scheduled with countdown=6 seconds from main_processor when the AI calls
    activate_focus_mode. If the user rejects before this fires, the pending
    context will already be consumed (GETDEL) and this task no-ops.
    
    Args:
        chat_id: The chat ID to auto-confirm focus mode for
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN'
    log_prefix = f"[FocusModeAutoConfirm][Task: {task_id[:8]}]"
    
    logger.info(f"{log_prefix} Auto-confirm task fired for chat {chat_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_focus_mode_auto_confirm(chat_id, task_id))
    except Exception as e:
        logger.error(f"{log_prefix} Error in auto-confirm task: {e}", exc_info=True)
        raise
    finally:
        if loop:
            loop.close()
