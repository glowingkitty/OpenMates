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
from typing import Any, Dict

import yaml

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# Countdown delay in seconds — 1s buffer over the 4s client countdown
FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN = 5


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
    task_id: str,
    request_id: str | None = None,
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
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    from backend.shared.python_utils.focus_continuation_history import (
        FocusContinuationHistoryError, current_focus_source_turn, publish_current_focus_continuation_failure,
        rebuild_focus_continuation_history, source_user_message_id,
    )
    
    log_prefix = f"[FocusModeAutoConfirm][Task: {task_id[:8]}][Chat: {chat_id[:8]}]"
    
    cache_service = CacheService()
    
    # Step 1: Atomically get and delete the pending context
    # If the user rejected first, this returns None (race-safe via GETDEL)
    pending_context = await cache_service.get_and_delete_pending_focus_activation(
        chat_id, embed_id=request_id, require_completed_countdown=True,
    )
    
    if not pending_context:
        logger.info(f"{log_prefix} No pending focus activation found — user likely rejected. No-op.")
        return
    
    from backend.shared.python_utils.recent_work_summary_client import restore_private_context_payload
    pending_context = await restore_private_context_payload(pending_context)

    focus_id = pending_context.get("focus_id")
    user_id = pending_context.get("user_id")
    user_id_hash = pending_context.get("user_id_hash", "")
    try:
        message_id = source_user_message_id(pending_context)
    except FocusContinuationHistoryError:
        logger.warning(f"{log_prefix} Pending Focus source turn is missing")
        return
    mate_id = pending_context.get("mate_id")
    chat_has_title = pending_context.get("chat_has_title", False)
    is_incognito = pending_context.get("is_incognito", False)
    original_task_id = pending_context.get("task_id", "unknown")
    
    logger.info(
        f"{log_prefix} Auto-confirming focus mode '{focus_id}' for chat {chat_id} "
        f"(original task: {original_task_id})"
    )
    
    # Step 2a: Notify the client that focus mode was activated
    # The client will encrypt the focus_id with the chat key (E2E) and send it back
    # for persistence. The server cannot encrypt with the chat key.
    encryption_service = EncryptionService()
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()

    # Private specialist acceptance revalidates current Project authority and the
    # saved item revision. The pending client snapshot is transient; no private
    # ciphertext is decrypted by the server to recover missing instructions.
    if isinstance(focus_id, str) and focus_id.startswith("project-focus:"):
        from backend.core.api.app.services.project_write_authorization_service import (
            ProjectWriteAuthorizationError, ProjectWriteAuthorizationService,
        )
        document = next((value for value in pending_context.get("project_focus_documents", [])
                         if isinstance(value, dict) and value.get("item_id") == focus_id.split(":")[-1]), None)
        try:
            latest = await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id))
            if latest != source_user_message_id(pending_context) or not document:
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
            await ProjectWriteAuthorizationService(directus_service, cache_service).validate_specialist_context(
                user_id=user_id, chat_id=chat_id, focus_id=focus_id,
                instruction=document.get("document"), item_revision=document.get("revision"),
                require_accepted=False,
            )
        except ProjectWriteAuthorizationError:
            logger.info(f"{log_prefix} Private Focus proposal no longer authorized")
            from backend.core.api.app.routes.handlers.websocket_handlers.focus_mode_rejected_handler import _trigger_continuation_without_focus
            await _trigger_continuation_without_focus(cache_service, directus_service, encryption_service, pending_context, log_prefix)
            return

    # Fetch user's vault key — needed for decryption in step 2c
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
        logger.error(f"{log_prefix} Cannot decrypt without vault_key_id")
        await publish_current_focus_continuation_failure(cache_service, pending_context)
        return
    
    # Step 2c: Rebuild through the exact user turn, excluding later provisional
    # assistant output without ever replaying a prior or superseded user message.
    try:
        message_history = await rebuild_focus_continuation_history(
            cache_service=cache_service, encryption_service=encryption_service,
            pending_context=pending_context, user_vault_key_id=user_vault_key_id,
        )
    except FocusContinuationHistoryError as exc:
        logger.warning(f"{log_prefix} Focus continuation history unavailable: {exc.code}")
        await publish_current_focus_continuation_failure(cache_service, pending_context)
        return

    if not await current_focus_source_turn(cache_service, pending_context):
        logger.info(f"{log_prefix} Focus source turn changed before acceptance")
        return
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
    await ProjectWriteAuthorizationService(directus_service, cache_service).accept_specialist_focus(
        user_id=user_id, chat_id=chat_id, focus_id=focus_id, request_id=pending_context.get("embed_id"),
    )

    # A specialist adds its instructions to the already authorized Project base.
    # It never grants additional Project permissions.
    from backend.apps.ai.processing.focus_phases import invalidate_phase_runtime
    await invalidate_phase_runtime(await cache_service.client, owner_id=user_id,
                                   chat_id=chat_id, focus_id=focus_id)

    # The client encrypts the accepted ID with its chat key for persistence.
    try:
        redis_client = await cache_service.client
        if redis_client:
            channel = f"user_cache_events:{user_id}"
            await redis_client.publish(channel, json.dumps({
                "event_type": "focus_mode_activated",
                "payload": {"chat_id": chat_id, "focus_id": focus_id},
            }))
            logger.info(f"{log_prefix} Published focus_mode_activated event to {channel}")
    except Exception as e:
        logger.error(f"{log_prefix} Error publishing focus_mode_activated event: {e}", exc_info=True)
    
    role_sequence = [str(message.get("role", "?")) for message in message_history]
    logger.info(
        f"{log_prefix} Retrieved and decrypted {len(message_history)} messages from AI cache "
        f"for continuation; role_sequence={role_sequence}"
    )
    
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
            "agentic_context_ref": pending_context.get("agentic_context_ref"),
            "agentic_context_request_id": pending_context.get("agentic_context_request_id"),
            "agentic_context_turn_id": pending_context.get("agentic_context_turn_id"),
            "active_focus_id": focus_id,  # Focus mode is NOW active for this continuation
            **{key: pending_context.get(key, []) for key in (
                "accepted_plan_context", "project_focus_documents", "project_focus_catalog", "custom_rule_documents",
                "project_context_documents", "related_task_candidates", "project_focus_candidates",
            )},
            "recovery_inference_task_id": pending_context.get("recovery_inference_task_id"),
            "recovery_preflight_id": pending_context.get("recovery_preflight_id"),
            "recovery_turn_id": pending_context.get("recovery_turn_id"),
            "recovery_public_key": pending_context.get("recovery_public_key"),
            "chat_key_version": pending_context.get("chat_key_version"),
            "parent_id": pending_context.get("parent_id"),
            "is_sub_chat": bool(pending_context.get("is_sub_chat")),
            "orchestration_id": pending_context.get("orchestration_id"),
            "root_chat_id": pending_context.get("root_chat_id"),
            "root_turn_id": pending_context.get("root_turn_id"),
            "sub_chat_depth": pending_context.get("sub_chat_depth", 0),
            "orchestration_dispatch_token": pending_context.get("orchestration_dispatch_token"),
            "orchestration_descendant_limit": pending_context.get("orchestration_descendant_limit", 3),
            "orchestration_credit_limit": pending_context.get("orchestration_credit_limit", 2_000),
            "orchestration_approved": bool(pending_context.get("orchestration_approved")),
            "budget_limit": pending_context.get("budget_limit"),
            "budget_spent": pending_context.get("budget_spent", 0),
            "team_id": pending_context.get("team_id"),
            "team_id_hash": pending_context.get("team_id_hash"),
            "team_workspace_type": pending_context.get("team_workspace_type", "chat"),
            "team_object_id_hash": pending_context.get("team_object_id_hash"),
            # Signal that this is a continuation after focus mode activation.
            # The task should NOT re-persist the user message (it's already persisted).
            # This continuation creates a SEPARATE assistant message (new task_id = new message_id).
            # The client renders both messages but visually merges them into one bubble.
            "is_focus_mode_continuation": True,
        }
        
        from backend.shared.python_utils.recent_work_summary_client import seal_private_context_payload
        request_data_dict = await seal_private_context_payload(
            request_data_dict, request_id=pending_context.get("embed_id", ""),
        )
        if not await current_focus_source_turn(cache_service, pending_context):
            logger.info(f"{log_prefix} Focus source turn changed before continuation dispatch")
            return
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
        await publish_current_focus_continuation_failure(cache_service, pending_context)


@app.task(
    name="apps.ai.tasks.focus_mode_auto_confirm",
    bind=True,
    max_retries=0,  # No retries — if it fails, user can trigger again on next message
    soft_time_limit=60,
    time_limit=90,
)
def focus_mode_auto_confirm_task(self, chat_id: str, request_id: str | None = None):
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
        loop.run_until_complete(_async_focus_mode_auto_confirm(chat_id, task_id, request_id))
    except Exception as e:
        logger.error(f"{log_prefix} Error in auto-confirm task: {e}", exc_info=True)
        raise
    finally:
        if loop:
            loop.close()
