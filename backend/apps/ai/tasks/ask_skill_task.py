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
    celery_task_instance: Any, # Celery task instance
    task_id: str,
    request_data: AskSkillRequest,
    skill_config: AskSkillDefaultConfig
):
    """
    Asynchronous core logic for processing the AI skill ask task.
    Initializes services and performs the main processing steps.
    """
    logger.info(f"[Task ID: {task_id}] Async task execution started.")

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
        # Ensure client is ready if specific CacheService methods don't await it internally
        # For CacheServiceBase, methods using `await self.client` handle this.
        await cache_service_instance.client # Explicitly wait for connection to be ready
        logger.info(f"[Task ID: {task_id}] CacheService initialized.")
        
        # Assuming DirectusService and EncryptionService constructors are synchronous
        # or handle their own async initialization if needed.
        # Pass secrets_manager and cache_service as needed.
        # encryption_service_instance needs to be initialized before DirectusService
        # as DirectusService might depend on it.
        encryption_service_instance = EncryptionService(
            cache_service=cache_service_instance
        ) # Adjust constructor as per actual EncryptionService
        logger.info(f"[Task ID: {task_id}] EncryptionService initialized.")

        directus_service_instance = DirectusService(
            cache_service=cache_service_instance,
            encryption_service=encryption_service_instance 
        ) # Adjust constructor as per actual DirectusService
        logger.info(f"[Task ID: {task_id}] DirectusService initialized.")

    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Failed to initialize services: {e}", exc_info=True)
        celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'ServiceInitializationError', 'exc_message': str(e)})
        # This exception will be caught by the synchronous wrapper, which should then raise Ignore()
        raise RuntimeError(f"Service initialization failed: {e}")


    # --- Load configurations ---
    base_instructions = load_base_instructions()
    if not base_instructions:
        logger.error(f"[Task ID: {task_id}] Failed to load base_instructions.yml. Aborting task.")
        celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'FileNotFoundError', 'exc_message': 'base_instructions.yml not found or empty.'})
        raise RuntimeError("base_instructions.yml not found or empty.")

    all_mates_configs: List[MateConfig] = load_mates_config()
    if not all_mates_configs:
        logger.critical(f"[Task ID: {task_id}] Failed to load mates_config.yml or it was empty. Aborting task.")
        celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'FileNotFoundError', 'exc_message': 'mates.yml not found, empty, or invalid.'})
        raise RuntimeError("mates.yml not found, empty, or invalid.")

    # --- Load discovered_apps_metadata from cache ---
    discovered_apps_metadata: Dict[str, AppYAML] = {}
    try:
        if cache_service_instance:
            # Use the new CacheService method
            cached_metadata = await cache_service_instance.get_discovered_apps_metadata()
            if cached_metadata:
                discovered_apps_metadata = cached_metadata
                logger.info(f"[Task ID: {task_id}] Successfully loaded discovered_apps_metadata from cache via CacheService method.")
            else:
                # get_discovered_apps_metadata logs if not found or on error, so just a warning here.
                logger.warning(f"[Task ID: {task_id}] discovered_apps_metadata not found in cache or failed to load. Proceeding with empty metadata.")
        else:
            logger.error(f"[Task ID: {task_id}] CacheService instance not available for loading discovered_apps_metadata.")
    except Exception as e_cache_get:
        # This catches errors from the call to get_discovered_apps_metadata itself, though it should handle its own.
        logger.error(f"[Task ID: {task_id}] Error calling get_discovered_apps_metadata: {e_cache_get}", exc_info=True)

    # --- Fetch user_vault_key_id from cache and user_app_memories_metadata from Directus ---
    user_vault_key_id: Optional[str] = None
    if cache_service_instance and request_data.user_id: # Use actual user_id for cache lookup
        cached_user_data = await cache_service_instance.get_user_by_id(request_data.user_id)
        if not cached_user_data:
            logger.error(f"[Task ID: {task_id}] Failed to retrieve cached user data for user_id: {request_data.user_id}. Aborting task.")
            celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'UserDataNotFoundError', 'exc_message': 'User data not found in cache.'})
            raise RuntimeError("User data not found in cache.")

        user_vault_key_id = cached_user_data.get("vault_key_id")
        if not user_vault_key_id:
            logger.error(f"[Task ID: {task_id}] vault_key_id not found in cached user data for user_id: {request_data.user_id}. Aborting task.")
            celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'VaultKeyNotFoundError', 'exc_message': 'User vault key ID not found in cache.'})
            raise RuntimeError("User vault key ID not found in cache.")
        logger.info(f"[Task ID: {task_id}] Successfully retrieved user_vault_key_id from cache using user_id: {request_data.user_id}.")
    elif not cache_service_instance:
        logger.error(f"[Task ID: {task_id}] CacheService instance not available. Cannot fetch user_vault_key_id. Aborting task.")
        celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'ServiceUnavailable', 'exc_message': 'CacheService not available.'})
        raise RuntimeError("CacheService not available.")
    elif not request_data.user_id: # Check for user_id now
        logger.error(f"[Task ID: {task_id}] user_id is missing in request_data. Cannot fetch user_vault_key_id. Aborting task.")
        celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'InputValidationError', 'exc_message': 'user_id is missing.'})
        raise RuntimeError("user_id is missing.")

    user_app_memories_metadata: Dict[str, List[str]] = {}
    # Use user_id_hash for fetching app_settings_and_memories metadata from Directus
    if directus_service_instance and request_data.user_id_hash:
        try:
            # This fetches the list of available memory *keys* for the user, using user_id_hash.
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
            # Not raising an error here, as preprocessing might still proceed without this metadata.
    elif not directus_service_instance:
        logger.warning(f"[Task ID: {task_id}] DirectusService not available. Cannot fetch user app memories metadata.")

    # --- Step 1: Preprocessing ---
    logger.info(f"[Task ID: {task_id}] Starting preprocessing step...")
    celery_task_instance.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'started'})
    
    preprocessing_result: Optional[PreprocessingResult] = None
    try:
        if not cache_service_instance:
            logger.error(f"[Task ID: {task_id}] CacheService instance is not available. Cannot proceed with preprocessing credit check.")
            celery_task_instance.update_state(state='FAILURE', meta={'exc_type': 'ServiceUnavailable', 'exc_message': 'CacheService not available for preprocessing.'})
            raise RuntimeError("CacheService not available for preprocessing.")

        preprocessing_result = await handle_preprocessing(
            request_data=request_data,
            skill_config=skill_config,
            base_instructions=base_instructions,
            cache_service=cache_service_instance,
            secrets_manager=secrets_manager, # Pass SecretsManager
            user_app_settings_and_memories_metadata=user_app_memories_metadata
        )
        logger.info(f"[Task ID: {task_id}] Preprocessing completed. Result: {preprocessing_result.model_dump_json(indent=2)}")
        celery_task_instance.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'completed', 'result': preprocessing_result.model_dump()})

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
                        error_message_directus_payload = {
                            "client_message_id": f"error_{task_id}",
                            "chat_id": request_data.chat_id,
                            "hashed_user_id": request_data.user_id_hash,
                            "sender_name": "system_error",
                            "encrypted_content": encrypted_error_content,
                            "created_at": current_timestamp,
                        }
                        created_error_msg_directus = await directus_service_instance.chat.create_message_in_directus(error_message_directus_payload)

                        if created_error_msg_directus:
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
                                        "message_id": f"error_{task_id}",
                                        "sender_name": "system_error",
                                        "content": error_tiptap_payload,
                                        "timestamp": current_timestamp,
                                        "status": "synced",
                                    },
                                    "versions": {"messages_v": new_messages_version},
                                    "last_edited_overall_timestamp": current_timestamp
                                }
                                error_redis_channel = f"ai_message_persisted::{request_data.user_id_hash}"
                                await cache_service_instance.publish_event(error_redis_channel, json.dumps(error_event_payload))
                        else:
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
            # This will be returned and the sync wrapper will update state and return
            return {"task_id": task_id, **rejection_details, "_celery_task_state": "FAILURE"} 
    except Exception as e: # Catch exceptions from preprocessing itself
        logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
        # This exception will be caught by the synchronous wrapper
        raise RuntimeError(f"Preprocessing failed: {e}")


    # --- Step 2: Main Processing (with streaming) ---
    logger.info(f"[Task ID: {task_id}] Starting main processing step (streaming)...")
    celery_task_instance.update_state(state='PROGRESS', meta={'step': 'main_processing', 'status': 'started_streaming'})
    
    aggregated_final_response: str = ""
    try:
        aggregated_final_response = await _consume_main_processing_stream(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result, # Must be valid if we reached here
            base_instructions=base_instructions,
            directus_service=directus_service_instance,
            encryption_service=encryption_service_instance,
            user_vault_key_id=user_vault_key_id,
            all_mates_configs=all_mates_configs,
            discovered_apps_metadata=discovered_apps_metadata,
            cache_service=cache_service_instance,
            celery_task_instance=celery_task_instance, # Pass the Celery task instance
            secrets_manager=secrets_manager # Pass SecretsManager
        )
        logger.info(f"[Task ID: {task_id}] Main processing stream consumed.")
        summary_response = aggregated_final_response[:500] + "..." if len(aggregated_final_response) > 500 else aggregated_final_response
        celery_task_instance.update_state(state='PROGRESS', meta={'step': 'main_processing', 'status': 'completed_streaming', 'output_summary': summary_response})

    except SoftTimeLimitExceeded: # This might be caught by Celery's mechanism before _consume_main_processing_stream sets the flag
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded during task execution (around _consume_main_processing_stream call).")
        celery_task_instance.interrupted_by_soft_limit_in_consumer = True # Ensure flag is set
        # Exception will be re-raised or handled by Celery's soft time limit
        raise
    except Exception as e:
        if celery_task_instance.is_revoked():
            logger.warning(f"[Task ID: {task_id}] Task revoked during or after main processing stream execution.")
            celery_task_instance.custom_revocation_flag = True
        else:
            logger.error(f"[Task ID: {task_id}] Error during main processing stream execution: {e}", exc_info=True)
            # This exception will be caught by the synchronous wrapper
            raise RuntimeError(f"Main processing stream execution failed: {e}")

    # Determine final status based on flags set by _consume_main_processing_stream or here
    final_status_message = "completed"
    log_final_status = "successfully"

    if celery_task_instance.interrupted_by_soft_limit_in_consumer:
        final_status_message = "completed_partially_soft_limit"
        log_final_status = "partially completed (interrupted by soft time limit)"
    elif celery_task_instance.custom_revocation_flag or celery_task_instance.is_revoked():
        final_status_message = "completed_partially_revoked"
        log_final_status = "partially completed (interrupted by revocation)"

    logger.info(f"[Task ID: {task_id}] AI skill ask task processing finished {log_final_status}.")
    
    return {
        "task_id": task_id,
        "status": final_status_message,
        "preprocessing_summary": preprocessing_result.model_dump() if preprocessing_result else {},
        "main_processing_output": aggregated_final_response,
        "interrupted_by_soft_time_limit": celery_task_instance.interrupted_by_soft_limit_in_consumer,
        "interrupted_by_revocation": celery_task_instance.custom_revocation_flag or celery_task_instance.is_revoked(),
        "_celery_task_state": "SUCCESS" # Indicate success to the sync wrapper
    }


@celery_app.task(bind=True, name="apps.ai.tasks.skill_ask", soft_time_limit=300, time_limit=360)
def process_ai_skill_ask_task(self, request_data_dict: dict, skill_config_dict: dict):
    task_id = self.request.id
    logger.info(f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task. Request: {request_data_dict}, Skill Config: {skill_config_dict}")

    # Initialize custom flags for interruption status propagation
    # These will be accessed and modified by the async helper functions
    self.custom_revocation_flag = False
    self.interrupted_by_soft_limit_in_consumer = False

    try:
        request_data = AskSkillRequest(**request_data_dict)
        skill_config = AskSkillDefaultConfig(**skill_config_dict)
    except ValidationError as e:
        logger.error(f"[Task ID: {task_id}] Validation error for input data: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': 'ValidationError', 'exc_message': str(e.errors())})
        raise Ignore() # Celery will ignore this task, not retry

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    task_result = None
    try:
        task_result = loop.run_until_complete(
            _async_process_ai_skill_ask_task(self, task_id, request_data, skill_config)
        )
        
        # Handle results that indicate failure within the async logic
        if isinstance(task_result, dict) and task_result.get("_celery_task_state") == "FAILURE":
            failure_meta = {k: v for k, v in task_result.items() if k != "_celery_task_state"}
            # Ensure exc_type and exc_message are present for Celery's backend processing
            # Use 'reason' from task_result for exc_type and 'message' for exc_message.
            # Provide fallbacks if these keys are unexpectedly missing.
            failure_meta['exc_type'] = str(task_result.get('reason', 'PreprocessingLogicError'))
            failure_meta['exc_message'] = str(task_result.get('message', 'Preprocessing determined request cannot proceed and failed to provide a specific message.'))
            self.update_state(state='FAILURE', meta=failure_meta)
            # Return the result dict as Celery task result, even on logical failure
            return task_result
        
        # If successful, update state and return
        success_meta = {
            'status_message': task_result.get('status'),
            'preprocessing_summary': task_result.get('preprocessing_summary'),
            'main_processing_output_summary': (task_result.get('main_processing_output')[:500] + "...") if task_result.get('main_processing_output') and len(task_result.get('main_processing_output')) > 500 else task_result.get('main_processing_output'),
            'interrupted_by_soft_time_limit': task_result.get('interrupted_by_soft_time_limit'),
            'interrupted_by_revocation': task_result.get('interrupted_by_revocation')
        }
        self.update_state(state='SUCCESS', meta=success_meta)
        return task_result

    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded in synchronous task wrapper.")
        # The flag should have been set by _consume_main_processing_stream or _async_process_ai_skill_ask_task
        # Update state to reflect partial completion due to soft limit
        self.update_state(state='FAILURE', meta={
            'exc_type': 'SoftTimeLimitExceeded', 
            'exc_message': 'Task exceeded soft time limit.',
            'status_message': 'completed_partially_soft_limit',
            'interrupted_by_soft_time_limit': True,
            'interrupted_by_revocation': self.custom_revocation_flag or self.is_revoked()
        })
        # Celery handles SoftTimeLimitExceeded by raising it, task might be retried or marked as failed.
        # We've updated the state; re-raising is standard.
        raise
    except RuntimeError as e: # Catch specific RuntimeErrors from async helper for logical failures
        logger.error(f"[Task ID: {task_id}] Runtime error from async task execution: {e}", exc_info=True)
        # State should have been updated within _async_process_ai_skill_ask_task before raising
        # If not, update here based on the error.
        # Example: self.update_state(state='FAILURE', meta={'exc_type': 'RuntimeError', 'exc_message': str(e)})
        # This ensures the task is marked as failed in Celery.
        # Raising Ignore() prevents retries for these defined logical failures.
        raise Ignore()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception in synchronous task wrapper: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': str(type(e).__name__), 'exc_message': str(e)})
        # For truly unexpected errors, re-raising might lead to retries depending on Celery config.
        # If no retry is desired, raise Ignore().
        raise Ignore() # Or re-raise e if retries are acceptable for unknown errors
    finally:
        loop.close()
        logger.info(f"[Task ID: {task_id}] Async event loop closed.")
