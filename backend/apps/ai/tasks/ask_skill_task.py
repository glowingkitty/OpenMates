# backend/apps/ai/tasks/ask_skill_task.py
# Celery task for the AI App's "ask" skill.
#
# IMPORTANT CONTEXT:
# The tasks defined in this file are executed by the 'task-worker' Docker service.
# This worker service has the broader 'backend' codebase (including 'backend/core'
# and 'backend/apps') mounted, allowing it to import modules like
# 'backend.core.api.app.tasks.celery_config'.
# The 'celery_app' imported here is the central Celery application instance
# that the 'task-worker' is configured to use. This is how tasks defined here
# are registered with and executed by that worker.

import logging
import asyncio
import json
import time
from typing import Dict, Any, List, Optional, AsyncIterator
from pydantic import ValidationError
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from celery.states import REVOKED as TASK_STATE_REVOKED # Module-level import

# Import Celery app instance
from backend.core.api.app.tasks.celery_config import app as celery_app

# Import services to be instantiated directly in the task
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService # Assuming this is the correct path
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_schemas.app_metadata_schemas import AppYAML
from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
from backend.apps.ai.processing.preprocessor import handle_preprocessing, PreprocessingResult
# Removed: from backend.apps.ai.processing.main_processor import handle_main_processing
# Import the stream consumer
from .stream_consumer import _consume_main_processing_stream


logger = logging.getLogger(__name__)

async def _async_process_ai_skill_ask_task(
    # celery_task_instance: Any, # Celery task instance - REMOVED
    task_id: str, # task_id is still needed
    request_data: AskSkillRequest,
    skill_config: AskSkillDefaultConfig
    # celery_app_ref will be used via import
):
    """
    Asynchronous core logic for processing the AI skill ask task.
    Initializes services and performs the main processing steps.
    Returns a dictionary with processing results and status flags.
    """
    logger.info(f"[Task ID: {task_id}] Async task execution started.")

    # Local flags for interruption, to be returned
    task_was_revoked = False
    task_was_soft_limited = False

    # --- Initialize services ---
    secrets_manager = None
    cache_service_instance = None
    directus_service_instance = None
    encryption_service_instance = None

    try:
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        logger.info(f"[Task ID: {task_id}] SecretsManager initialized.")

        cache_service_instance = CacheService()
        await cache_service_instance.client 
        logger.info(f"[Task ID: {task_id}] CacheService initialized.")
        
        encryption_service_instance = EncryptionService(
            cache_service=cache_service_instance
        )
        logger.info(f"[Task ID: {task_id}] EncryptionService initialized.")

        directus_service_instance = DirectusService(
            cache_service=cache_service_instance,
            encryption_service=encryption_service_instance 
        )
        logger.info(f"[Task ID: {task_id}] DirectusService initialized.")

    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Failed to initialize services: {e}", exc_info=True)
        # The synchronous wrapper will handle updating Celery state.
        # We raise RuntimeError to signal failure to the sync wrapper.
        # The sync wrapper will call self.update_state.
        raise RuntimeError(f"Service initialization failed: {e}")


    # --- Load configurations ---
    base_instructions = load_base_instructions()
    if not base_instructions:
        logger.error(f"[Task ID: {task_id}] Failed to load base_instructions.yml. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("base_instructions.yml not found or empty.")

    all_mates_configs: List[MateConfig] = load_mates_config()
    if not all_mates_configs:
        logger.critical(f"[Task ID: {task_id}] Failed to load mates_config.yml or it was empty. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("mates.yml not found, empty, or invalid.")

    # --- Load discovered_apps_metadata from cache ---
    discovered_apps_metadata: Dict[str, AppYAML] = {}
    try:
        if cache_service_instance:
            cached_metadata = await cache_service_instance.get_discovered_apps_metadata()
            if cached_metadata:
                discovered_apps_metadata = cached_metadata
                logger.info(f"[Task ID: {task_id}] Successfully loaded discovered_apps_metadata from cache via CacheService method.")
            else:
                logger.warning(f"[Task ID: {task_id}] discovered_apps_metadata not found in cache or failed to load. Proceeding with empty metadata.")
        else:
            logger.error(f"[Task ID: {task_id}] CacheService instance not available for loading discovered_apps_metadata.")
    except Exception as e_cache_get:
        logger.error(f"[Task ID: {task_id}] Error calling get_discovered_apps_metadata: {e_cache_get}", exc_info=True)

    # --- Fetch user_vault_key_id from cache and user_app_memories_metadata from Directus ---
    user_vault_key_id: Optional[str] = None
    if cache_service_instance and request_data.user_id:
        cached_user_data = await cache_service_instance.get_user_by_id(request_data.user_id)
        if not cached_user_data:
            logger.error(f"[Task ID: {task_id}] Failed to retrieve cached user data for user_id: {request_data.user_id}. Aborting task.")
            raise RuntimeError("User data not found in cache.")

        user_vault_key_id = cached_user_data.get("vault_key_id")
        if not user_vault_key_id:
            logger.error(f"[Task ID: {task_id}] vault_key_id not found in cached user data for user_id: {request_data.user_id}. Aborting task.")
            raise RuntimeError("User vault key ID not found in cache.")
        logger.info(f"[Task ID: {task_id}] Successfully retrieved user_vault_key_id from cache using user_id: {request_data.user_id}.")
    elif not cache_service_instance:
        logger.error(f"[Task ID: {task_id}] CacheService instance not available. Cannot fetch user_vault_key_id. Aborting task.")
        raise RuntimeError("CacheService not available.")
    elif not request_data.user_id:
        logger.error(f"[Task ID: {task_id}] user_id is missing in request_data. Cannot fetch user_vault_key_id. Aborting task.")
        raise RuntimeError("user_id is missing.")

    user_app_memories_metadata: Dict[str, List[str]] = {}
    if directus_service_instance and request_data.user_id_hash:
        try:
            raw_items_metadata: List[Dict[str, Any]] = await directus_service_instance.app_settings_and_memories.get_user_app_data_metadata(request_data.user_id_hash)
            for item_meta in raw_items_metadata:
                app_id_key = item_meta.get("app_id")
                item_key_val = item_meta.get("item_key")
                if app_id_key and item_key_val:
                    if app_id_key not in user_app_memories_metadata:
                        user_app_memories_metadata[app_id_key] = []
                    if item_key_val not in user_app_memories_metadata[app_id_key]:
                        user_app_memories_metadata[app_id_key].append(item_key_val)
            logger.info(f"[Task ID: {task_id}] Successfully fetched user_app_memories_metadata (keys) from Directus.")
        except Exception as e:
            logger.error(f"[Task ID: {task_id}] Error during Directus ops for fetching user_app_memories_metadata: {e}", exc_info=True)
    elif not directus_service_instance:
        logger.warning(f"[Task ID: {task_id}] DirectusService not available. Cannot fetch user app memories metadata.")

    # --- Step 1: Preprocessing ---
    # The synchronous wrapper (process_ai_skill_ask_task) will call self.update_state for PROGRESS.
    logger.info(f"[Task ID: {task_id}] Starting preprocessing step...")
    
    preprocessing_result: Optional[PreprocessingResult] = None
    try:
        if not cache_service_instance:
            logger.error(f"[Task ID: {task_id}] CacheService instance is not available. Cannot proceed with preprocessing credit check.")
            raise RuntimeError("CacheService not available for preprocessing.")

        preprocessing_result = await handle_preprocessing(
            request_data=request_data,
            skill_config=skill_config,
            base_instructions=base_instructions,
            cache_service=cache_service_instance,
            secrets_manager=secrets_manager,
            user_app_settings_and_memories_metadata=user_app_memories_metadata
        )
        
        if not preprocessing_result.can_proceed:
            logger.warning(f"[Task ID: {task_id}] Preprocessing determined request cannot proceed. Reason: {preprocessing_result.rejection_reason}. Message: {preprocessing_result.error_message}")
            
            if directus_service_instance and encryption_service_instance and cache_service_instance and preprocessing_result.error_message:
                try:
                    logger.info(f"[Task ID: {task_id}] Persisting preprocessing error message to Directus and notifying client.")
                    error_tiptap_payload = {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": preprocessing_result.error_message}]}]
                    }
                    encrypted_error_content = await encryption_service_instance.encrypt_with_chat_key(
                        key_id=request_data.chat_id,
                        plaintext=json.dumps(error_tiptap_payload)
                    )
                    if encrypted_error_content:
                        current_timestamp = int(time.time())
                        # ... (rest of error persistence logic remains similar) ...
                        error_message_directus_payload = {
                            "client_message_id": f"error_{task_id}",
                            "chat_id": request_data.chat_id,
                            "hashed_user_id": request_data.user_id_hash,
                            "sender_name": "system_error",
                            "encrypted_content": encrypted_error_content,
                            "created_at": current_timestamp,
                        }
                        created_error_msg_directus = await directus_service_instance.chat.create_message_in_directus(error_message_directus_payload)
                        if created_error_msg_directus and cache_service_instance: # Ensure cache_service is available
                            chat_metadata = await directus_service_instance.chat.get_chat_metadata(request_data.chat_id)
                            if chat_metadata:
                                new_messages_version = chat_metadata.get("messages_version", 0) + 1
                                fields_to_update = {
                                    "messages_version": new_messages_version,
                                    "last_edited_overall_timestamp": current_timestamp,
                                    "last_message_timestamp": current_timestamp
                                }
                                await directus_service_instance.chat.update_chat_fields_in_directus(
                                    request_data.chat_id, fields_to_update
                                )
                                error_event_payload = {
                                    "type": "ai_message_persisted",
                                    "event_for_client": "chat_message_added",
                                    "chat_id": request_data.chat_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "message": {
                                        "message_id": f"error_{task_id}", "sender_name": "system_error",
                                        "content": error_tiptap_payload, "timestamp": current_timestamp, "status": "synced",
                                    },
                                    "versions": {"messages_v": new_messages_version},
                                    "last_edited_overall_timestamp": current_timestamp
                                }
                                error_redis_channel = f"ai_message_persisted::{request_data.user_id_hash}"
                                await cache_service_instance.publish_event(error_redis_channel, json.dumps(error_event_payload))
                        elif not created_error_msg_directus:
                             logger.error(f"[Task ID: {task_id}] Failed to persist error message to Directus for chat {request_data.chat_id}.")
                    else:
                        logger.error(f"[Task ID: {task_id}] Failed to encrypt error message for chat {request_data.chat_id}.")
                except Exception as e_persist:
                    logger.error(f"[Task ID: {task_id}] Error persisting/notifying preprocessing error: {e_persist}", exc_info=True)
            
            rejection_details = {
                "status": "rejected", 
                "reason": preprocessing_result.rejection_reason, 
                "message": preprocessing_result.error_message,
                "details": preprocessing_result.model_dump(exclude_none=True)
            }
            return {"task_id": task_id, **rejection_details, "_celery_task_state": "FAILURE", 
                    "interrupted_by_soft_time_limit": task_was_soft_limited, 
                    "interrupted_by_revocation": task_was_revoked} # Include flags
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
        raise RuntimeError(f"Preprocessing failed: {e}")

    # --- Step 2: Main Processing (with streaming) ---
    # Sync wrapper handles Celery state update for progress
    logger.info(f"[Task ID: {task_id}] Starting main processing step (streaming)...")
    
    aggregated_final_response: str = ""
    revoked_in_consumer = False
    soft_limited_in_consumer = False

    try:
        aggregated_final_response, revoked_in_consumer, soft_limited_in_consumer = await _consume_main_processing_stream(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            base_instructions=base_instructions,
            directus_service=directus_service_instance,
            encryption_service=encryption_service_instance,
            user_vault_key_id=user_vault_key_id,
            all_mates_configs=all_mates_configs,
            discovered_apps_metadata=discovered_apps_metadata,
            cache_service=cache_service_instance,
            # celery_task_instance is removed
            secrets_manager=secrets_manager
        )
        logger.info(f"[Task ID: {task_id}] Main processing stream consumed.")
        # Sync wrapper handles Celery state update for progress
        task_was_revoked = revoked_in_consumer # Update overall flag
        task_was_soft_limited = soft_limited_in_consumer # Update overall flag

    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded during task execution (around _consume_main_processing_stream call).")
        task_was_soft_limited = True # Set overall flag
        raise # Re-raise for sync wrapper to handle Celery state
    except Exception as e:
        # Check for revocation if an unexpected error occurs
        # Use .state == 'REVOKED' for checking revocation status
        if celery_app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
            logger.warning(f"[Task ID: {task_id}] Task revoked during or after main processing stream execution.")
            task_was_revoked = True # Set overall flag
        else:
            logger.error(f"[Task ID: {task_id}] Error during main processing stream execution: {e}", exc_info=True)
        raise RuntimeError(f"Main processing stream execution failed: {e}") # Re-raise for sync wrapper

    # Determine final status based on local flags
    final_status_message = "completed"
    log_final_status = "successfully"

    if task_was_soft_limited: # Use local flag
        final_status_message = "completed_partially_soft_limit"
        log_final_status = "partially completed (interrupted by soft time limit)"
    # Check task_was_revoked AFTER soft_limited, as revocation might occur during soft limit handling
    if task_was_revoked: # Use local flag (also check if AsyncResult says so, though flag should capture it)
        final_status_message = "completed_partially_revoked"
        log_final_status = "partially completed (interrupted by revocation)"
    
    logger.info(f"[Task ID: {task_id}] AI skill ask task processing finished {log_final_status}.")
    
    return {
        "task_id": task_id,
        "status": final_status_message,
        "preprocessing_summary": preprocessing_result.model_dump() if preprocessing_result else {},
        "main_processing_output": aggregated_final_response,
        "interrupted_by_soft_time_limit": task_was_soft_limited, # Return determined flag
        "interrupted_by_revocation": task_was_revoked, # Return determined flag
        "_celery_task_state": "SUCCESS"
    }


@celery_app.task(bind=True, name="apps.ai.tasks.skill_ask", soft_time_limit=300, time_limit=360)
def process_ai_skill_ask_task(self, request_data_dict: dict, skill_config_dict: dict):
    task_id = self.request.id
    logger.info(f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task. Request: {request_data_dict}, Skill Config: {skill_config_dict}")

    # Custom flags on 'self' are no longer initialized here,
    # their status will be derived from the async helper's return value.

    try:
        request_data = AskSkillRequest(**request_data_dict)
        skill_config = AskSkillDefaultConfig(**skill_config_dict)
    except ValidationError as e:
        logger.error(f"[Task ID: {task_id}] Validation error for input data: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': 'ValidationError', 'exc_message': str(e.errors())})
        raise Ignore()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    task_result_dict: Optional[Dict[str, Any]] = None
    try:
        # Update progress before calling async helper
        self.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'started'})

        task_result_dict = loop.run_until_complete(
            _async_process_ai_skill_ask_task(task_id, request_data, skill_config) # 'self' is not passed
        )
        
        # Update progress after preprocessing if successful and before main processing (if applicable)
        # The async helper now returns more detailed status, so we use that.
        if task_result_dict and task_result_dict.get("preprocessing_summary"):
             self.update_state(state='PROGRESS', meta={
                 'step': 'preprocessing', 'status': 'completed', 
                 'result': task_result_dict.get("preprocessing_summary")
            })
        
        if task_result_dict and task_result_dict.get("main_processing_output") is not None: # Check if main processing happened
            self.update_state(state='PROGRESS', meta={
                'step': 'main_processing', 'status': 'started_streaming' 
                # Note: 'completed_streaming' status update would happen based on task_result_dict.status
            })


        # Handle results that indicate logical failure within the async logic
        if isinstance(task_result_dict, dict) and task_result_dict.get("_celery_task_state") == "FAILURE":
            failure_meta = {k: v for k, v in task_result_dict.items() if k not in ["_celery_task_state", "task_id"]}
            failure_meta['exc_type'] = str(task_result_dict.get('reason', 'AsyncLogicError'))
            failure_meta['exc_message'] = str(task_result_dict.get('message', 'Async task indicated failure.'))
            # Add interruption flags from async result to the meta
            failure_meta['interrupted_by_soft_time_limit'] = task_result_dict.get('interrupted_by_soft_time_limit', False)
            failure_meta['interrupted_by_revocation'] = task_result_dict.get('interrupted_by_revocation', False)
            self.update_state(state='FAILURE', meta=failure_meta)
            return task_result_dict
        
        # If successful or partially successful (due to interruption)
        if isinstance(task_result_dict, dict):
            success_meta = {
                'status_message': task_result_dict.get('status'),
                'preprocessing_summary': task_result_dict.get('preprocessing_summary'),
                'main_processing_output_summary': (task_result_dict.get('main_processing_output')[:500] + "...") if task_result_dict.get('main_processing_output') and len(task_result_dict.get('main_processing_output')) > 500 else task_result_dict.get('main_processing_output'),
                'interrupted_by_soft_time_limit': task_result_dict.get('interrupted_by_soft_time_limit'),
                'interrupted_by_revocation': task_result_dict.get('interrupted_by_revocation')
            }
            # If task was interrupted, it's technically a failure for Celery unless handled as a custom success state.
            # For now, let's align with Celery's expectation: SUCCESS means fully completed.
            # Partial completions due to limits/revocation are often marked as FAILURE with details.
            current_celery_state = 'SUCCESS'
            if task_result_dict.get('interrupted_by_soft_time_limit') or task_result_dict.get('interrupted_by_revocation'):
                 # Or a custom state if your system handles it, e.g., 'PARTIAL_SUCCESS'
                 # For standard Celery, this might still be 'FAILURE' to prevent retries if not desired.
                 # Let's assume for now that "completed_partially_..." means the task did what it could.
                 # If these should be hard failures, change current_celery_state to 'FAILURE'.
                 pass # Keep as SUCCESS but with interruption flags in meta.

            self.update_state(state=current_celery_state, meta=success_meta)
            return task_result_dict
        else: # Should not happen if _async_process_ai_skill_ask_task always returns a dict
            logger.error(f"[Task ID: {task_id}] Async helper returned unexpected type: {type(task_result_dict)}")
            self.update_state(state='FAILURE', meta={'exc_type': 'InternalError', 'exc_message': 'Async helper returned non-dict result.'})
            raise Ignore()


    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded in synchronous task wrapper.")
        self.update_state(state='FAILURE', meta={
            'exc_type': 'SoftTimeLimitExceeded', 
            'exc_message': 'Task exceeded soft time limit in sync wrapper.',
            'status_message': 'completed_partially_soft_limit_wrapper', # Distinguish from async limit
            'interrupted_by_soft_time_limit': True, # This limit was in the sync part
            'interrupted_by_revocation': self.request.id and celery_app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED # Check current status of self
        })
        raise
    except RuntimeError as e: 
        logger.error(f"[Task ID: {task_id}] Runtime error from async task execution: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={
            'exc_type': 'RuntimeErrorFromAsync', 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False, # Assuming not a soft limit unless explicitly caught as such
            'interrupted_by_revocation': self.request.id and celery_app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        })
        raise Ignore()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception in synchronous task wrapper: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={
            'exc_type': str(type(e).__name__), 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False,
            'interrupted_by_revocation': self.request.id and celery_app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
            })
        raise Ignore()
    finally:
        loop.close()
        logger.info(f"[Task ID: {task_id}] Async event loop closed.")
