# backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_rejected_handler.py
#
# Handles WebSocket requests to reject a focus mode during the countdown.
# 
# When the user clicks the focus mode embed or presses ESC during the 4-second
# countdown, the client sends a "focus_mode_rejected" message. This handler:
#   1. Atomically gets and deletes the pending focus activation context (GETDEL)
#   2. If context exists (auto-confirm hasn't fired yet):
#      - Fires a new Celery task WITHOUT focus prompt (plain continuation)
#   3. If context is None (auto-confirm already ran):
#      - Falls back to deactivating the already-active focus mode
#   4. Sends acknowledgment to client
#
# System messages for rejection are persisted by the client via chat_system_message_added.

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


def _load_ask_skill_config_from_app_yml() -> Dict[str, Any]:
    """
    Load the 'ask' skill's configuration from the AI app's app.yml.
    
    Returns:
        Dictionary containing the skill_config for the 'ask' skill, or empty dict on failure.
    """
    # This handler is at: backend/core/api/app/routes/handlers/websocket_handlers/
    # AI app.yml is at: backend/apps/ai/app.yml
    # Path: websocket_handlers(1) → handlers(2) → routes(3) → app(4) → api(5) → core(6) → backend(7)
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file_dir)))))))
    app_yml_path = os.path.join(backend_dir, "apps", "ai", "app.yml")
    
    if not os.path.exists(app_yml_path):
        logger.error(f"[FOCUS_MODE] AI app.yml not found at {app_yml_path}")
        return {}
    
    try:
        with open(app_yml_path, 'r', encoding='utf-8') as f:
            app_config = yaml.safe_load(f)
        
        if not app_config:
            return {}
        
        skills = app_config.get("skills", [])
        for skill in skills:
            if skill.get("id", "").strip() == "ask":
                return skill.get("skill_config", {})
        
        return {}
    except Exception as e:
        logger.error(f"[FOCUS_MODE] Error loading skill config: {e}", exc_info=True)
        return {}


async def _trigger_continuation_without_focus(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    pending_context: Dict[str, Any],
    log_prefix: str,
) -> None:
    """
    Fire a new ask_skill Celery task that continues processing WITHOUT focus mode.
    
    This is the rejection path: the user rejected focus mode during the countdown,
    so we re-process the message without injecting focus instructions.
    
    Args:
        cache_service: CacheService instance
        directus_service: DirectusService instance
        encryption_service: EncryptionService instance
        pending_context: The consumed pending activation context
        log_prefix: Log prefix for consistent logging
    """
    chat_id = pending_context.get("chat_id")
    user_id = pending_context.get("user_id")
    user_id_hash = pending_context.get("user_id_hash", "")
    message_id = pending_context.get("message_id")
    mate_id = pending_context.get("mate_id")
    chat_has_title = pending_context.get("chat_has_title", False)
    is_incognito = pending_context.get("is_incognito", False)
    original_task_id = pending_context.get("task_id", "unknown")
    
    logger.info(f"{log_prefix} Triggering continuation without focus mode (original task: {original_task_id})")
    
    # Retrieve cached messages from AI cache
    cached_messages_str_list = await cache_service.get_ai_messages_history(user_id, chat_id)
    
    if not cached_messages_str_list:
        logger.error(f"{log_prefix} Failed to retrieve cached messages for chat {chat_id}")
        return
    
    # Get user's vault key for decryption
    user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not user_vault_key_id:
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
    
    logger.info(f"{log_prefix} Retrieved and decrypted {len(message_history)} messages")
    
    # Fire a new ask_skill Celery task WITHOUT focus mode
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
            "active_focus_id": None,  # Explicitly NO focus mode
            # Signal that this is a continuation after focus mode rejection
            "is_focus_mode_continuation": True,
            # Reuse the original task_id as the AI message_id so the continuation
            # response is appended to the same message bubble that contains the
            # focus mode activation embed, instead of creating a separate bubble.
            "continuation_message_id": original_task_id,
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
        
        logger.info(f"{log_prefix} Fired continuation task {task.id} WITHOUT focus mode")
    except Exception as e:
        logger.error(f"{log_prefix} Failed to fire continuation task: {e}", exc_info=True)


async def handle_focus_mode_rejected(
    websocket: WebSocket,
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
):
    """
    Handle user rejection of focus mode during the countdown.

    Atomically consumes the pending activation context. If it exists,
    fires a continuation task without focus mode. If it's already been
    consumed by the auto-confirm task, falls back to the standard
    deactivation path.

    Payload:
    {
        "chat_id": "uuid-of-the-chat",
        "focus_id": "jobs-career_insights"
    }
    """
    chat_id = payload.get("chat_id")
    focus_id = payload.get("focus_id", "unknown")
    log_prefix = f"[FocusModeRejected][User: {user_id[:6]}][Device: {device_fingerprint_hash[:6]}]"

    if not chat_id:
        logger.warning(f"{log_prefix} 'chat_id' not provided in focus_mode_rejected payload")
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {
                    "message": "chat_id is required to reject focus mode.",
                    "details": "missing_chat_id"
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"{log_prefix} User rejected focus mode '{focus_id}' for chat {chat_id}")

    try:
        if not cache_service:
            cache_service = CacheService()
        if not directus_service:
            directus_service = DirectusService()
            await directus_service.ensure_auth_token()
        if not encryption_service:
            encryption_service = EncryptionService()

        # Atomically get and delete the pending context
        # If auto-confirm already consumed it, this returns None
        pending_context = await cache_service.get_and_delete_pending_focus_activation(chat_id)

        if pending_context:
            # Happy path: we got the context before auto-confirm
            # Fire a continuation task WITHOUT focus mode
            logger.info(f"{log_prefix} Consumed pending context — firing continuation without focus mode")
            await _trigger_continuation_without_focus(
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service,
                pending_context=pending_context,
                log_prefix=log_prefix,
            )
        else:
            # Auto-confirm already consumed it — focus mode is already active
            # Fall back to the standard deactivation path
            logger.info(f"{log_prefix} Pending context already consumed — falling back to deactivation")
            
            # Clear focus mode from cache
            await cache_service.update_chat_active_focus_id(
                user_id=user_id,
                chat_id=chat_id,
                encrypted_focus_id=None
            )
            
            # Clear in Directus via Celery task
            try:
                from backend.core.api.app.tasks.celery_config import app as celery_app_instance
                celery_app_instance.send_task(
                    'app.tasks.persistence_tasks.persist_chat_active_focus_id',
                    kwargs={
                        "chat_id": chat_id,
                        "encrypted_active_focus_id": None
                    },
                    queue='persistence'
                )
            except Exception as celery_error:
                logger.error(f"{log_prefix} Error dispatching deactivation task: {celery_error}", exc_info=True)

        # Acknowledge the rejection to the client
        await manager.send_personal_message(
            message={
                "type": "focus_mode_rejected_ack",
                "payload": {
                    "chat_id": chat_id,
                    "focus_id": focus_id,
                    "status": "rejected",
                    # Let the client know if we caught it before auto-confirm
                    "caught_before_activation": pending_context is not None,
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )

    except Exception as e:
        logger.error(f"{log_prefix} Error handling focus mode rejection: {e}", exc_info=True)
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {
                    "message": "Failed to reject focus mode.",
                    "details": str(e)
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
