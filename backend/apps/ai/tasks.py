# backend/apps/ai/tasks.py
# Celery tasks for the AI App.
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
from backend.apps.ai.processing.main_processor import handle_main_processing

logger = logging.getLogger(__name__)

# Cache key for discovered apps metadata
DISCOVERED_APPS_METADATA_CACHE_KEY = "discovered_apps_metadata_v1"


async def _consume_main_processing_stream(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_result: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: Optional[DirectusService],
    encryption_service: Optional[EncryptionService],
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    cache_service: Optional[CacheService],
    celery_task_instance: Any # Celery task instance
) -> str:
    """
    Consumes the async stream from handle_main_processing, aggregates the response,
    and publishes chunks to Redis Pub/Sub.
    Sets interruption flags on celery_task_instance.
    """
    final_response_chunks = []
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _consume_main_processing_stream:"
    logger.info(f"{log_prefix} Starting to consume stream from main_processor.")

    # Initialize interruption flags on the task instance if they don't exist
    # These flags are set on the Celery task instance passed from the main task
    if not hasattr(celery_task_instance, 'custom_revocation_flag'):
        celery_task_instance.custom_revocation_flag = False
    if not hasattr(celery_task_instance, 'interrupted_by_soft_limit_in_consumer'):
        celery_task_instance.interrupted_by_soft_limit_in_consumer = False

    if celery_task_instance and celery_task_instance.is_revoked():
        logger.warning(f"{log_prefix} Task was revoked before starting main processing stream.")
        celery_task_instance.custom_revocation_flag = True
        return ""

    main_processing_stream: AsyncIterator[str] = handle_main_processing(
        task_id=task_id,
        request_data=request_data,
        preprocessing_results=preprocessing_result,
        base_instructions=base_instructions,
        directus_service=directus_service,
        user_vault_key_id=user_vault_key_id,
        all_mates_configs=all_mates_configs,
        discovered_apps_metadata=discovered_apps_metadata
    )

    stream_chunk_count = 0
    redis_channel_name = f"chat_stream::{request_data.chat_id}"

    try:
        async for chunk in main_processing_stream:
            if celery_task_instance and celery_task_instance.is_revoked():
                logger.warning(f"{log_prefix} Task revoked during main processing stream. Processing partial response.")
                celery_task_instance.custom_revocation_flag = True
                break

            final_response_chunks.append(chunk)
            stream_chunk_count += 1

            if cache_service:
                try:
                    current_full_content_so_far = "".join(final_response_chunks)
                    payload = {
                        "type": "ai_message_chunk",
                        "task_id": task_id,
                        "chat_id": request_data.chat_id,
                        "message_id": task_id,
                        "user_message_id": request_data.message_id,
                        "full_content_so_far": current_full_content_so_far,
                        "sequence": stream_chunk_count,
                        "is_final_chunk": False
                    }
                    json_payload = json.dumps(payload)
                    await cache_service.publish(redis_channel_name, json_payload)
                    if stream_chunk_count % 5 == 0 or len(current_full_content_so_far) % 1000 < len(chunk):
                        logger.info(f"{log_prefix} Published accumulated message (seq: {stream_chunk_count}) to Redis '{redis_channel_name}'. Total length: {len(current_full_content_so_far)}")
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to publish accumulated message (seq: {stream_chunk_count}) to Redis: {e}", exc_info=True)
            elif stream_chunk_count == 1:
                     logger.warning(f"{log_prefix} Cache service not available. Skipping Redis publish for chunks.")
    except SoftTimeLimitExceeded:
        logger.warning(f"{log_prefix} Soft time limit exceeded during main processing stream. Processing partial response.")
        celery_task_instance.interrupted_by_soft_limit_in_consumer = True
    except Exception as e:
        logger.error(f"{log_prefix} Exception during main processing stream consumption: {e}", exc_info=True)
        if celery_task_instance and celery_task_instance.is_revoked():
            celery_task_instance.custom_revocation_flag = True

    aggregated_response = "".join(final_response_chunks)
    log_msg_suffix = f"Total chunks: {stream_chunk_count}. Aggregated response length: {len(aggregated_response)}."

    if celery_task_instance.custom_revocation_flag:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY REVOCATION). {log_msg_suffix}")
    elif celery_task_instance.interrupted_by_soft_limit_in_consumer:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY SOFT LIMIT). {log_msg_suffix}")
    else:
        logger.info(f"{log_prefix} Finished consuming stream (COMPLETED). {log_msg_suffix}")

    if cache_service:
        try:
            final_payload = {
                "type": "ai_message_chunk",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "message_id": task_id,
                "user_message_id": request_data.message_id,
                "full_content_so_far": None,
                "sequence": stream_chunk_count + 1,
                "is_final_chunk": True,
                "interrupted_by_soft_limit": celery_task_instance.interrupted_by_soft_limit_in_consumer,
                "interrupted_by_revocation": celery_task_instance.custom_revocation_flag
            }
            json_final_payload = json.dumps(final_payload)
            await cache_service.publish(redis_channel_name, json_final_payload)
            logger.info(f"{log_prefix} Published final marker (seq: {stream_chunk_count + 1}, interrupted_soft: {celery_task_instance.interrupted_by_soft_limit_in_consumer}, interrupted_revoke: {celery_task_instance.custom_revocation_flag}) to Redis channel '{redis_channel_name}'.")
        except Exception as e:
            logger.error(f"{log_prefix} Failed to publish final marker to Redis: {e}", exc_info=True)

    if directus_service and encryption_service and aggregated_response:
        logger.info(f"{log_prefix} Attempting to persist final AI message to Directus for chat {request_data.chat_id}.")
        try:
            tiptap_payload = {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": aggregated_response}]}]
            }
            encrypted_ai_response = await encryption_service.encrypt_with_chat_key(
                key_id=request_data.chat_id,
                plaintext=json.dumps(tiptap_payload)
            )

            if not encrypted_ai_response:
                logger.error(f"{log_prefix} Failed to encrypt AI response for chat {request_data.chat_id}.")
            else:
                current_timestamp = int(time.time())
                message_payload_to_directus = {
                    "client_message_id": task_id,
                    "chat_id": request_data.chat_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "sender_name": preprocessing_result.selected_mate_id or "ai",
                    "encrypted_content": encrypted_ai_response,
                    "created_at": current_timestamp,
                }

                created_message_directus = await directus_service.chat.create_message_in_directus(message_payload_to_directus)
                if created_message_directus:
                    logger.info(f"{log_prefix} Successfully persisted AI message to Directus for chat {request_data.chat_id}. Directus Msg ID: {created_message_directus.get('id')}")

                    chat_metadata = await directus_service.chat.get_chat_metadata(request_data.chat_id)
                    if chat_metadata:
                        new_messages_version = chat_metadata.get("messages_version", 0) + 1
                        fields_to_update = {
                            "messages_version": new_messages_version,
                            "last_edited_overall_timestamp": current_timestamp,
                            "last_message_timestamp": current_timestamp
                        }

                        updated_chat_metadata_success = await directus_service.chat.update_chat_fields_in_directus(
                            request_data.chat_id,
                            fields_to_update
                        )
                        if updated_chat_metadata_success:
                            logger.info(f"{log_prefix} Successfully updated chat metadata for {request_data.chat_id}: messages_version to {new_messages_version}, timestamps to {current_timestamp}.")

                            if cache_service:
                                persisted_event_payload = {
                                    "type": "ai_message_persisted",
                                    "event_for_client": "chat_message_added",
                                    "chat_id": request_data.chat_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "message": {
                                        "message_id": task_id,
                                        "sender_name": preprocessing_result.selected_mate_id or "ai",
                                        "content": tiptap_payload,
                                        "timestamp": current_timestamp,
                                        "status": "synced",
                                    },
                                    "versions": {"messages_v": new_messages_version},
                                    "last_edited_overall_timestamp": current_timestamp
                                }
                                persisted_redis_channel = f"ai_message_persisted::{request_data.user_id_hash}"
                                try:
                                    await cache_service.publish(persisted_redis_channel, json.dumps(persisted_event_payload))
                                    logger.info(f"{log_prefix} Published 'ai_message_persisted' event to Redis channel '{persisted_redis_channel}' for chat {request_data.chat_id}.")
                                except Exception as e_redis_pub:
                                    logger.error(f"{log_prefix} Failed to publish 'ai_message_persisted' to Redis for chat {request_data.chat_id}: {e_redis_pub}", exc_info=True)
                            else:
                                logger.warning(f"{log_prefix} Cache service not available. Skipping 'ai_message_persisted' Redis publish for chat {request_data.chat_id}.")
                        else:
                            logger.error(f"{log_prefix} Failed to update chat metadata for {request_data.chat_id} after saving AI message.")
                    else:
                        logger.error(f"{log_prefix} Failed to fetch chat metadata for {request_data.chat_id} to update version and timestamp.")
                else:
                    logger.error(f"{log_prefix} Failed to persist AI message to Directus for chat {request_data.chat_id}.")
        except Exception as e:
            logger.error(f"{log_prefix} Error during AI message persistence or chat metadata update for chat {request_data.chat_id}: {e}", exc_info=True)
    elif not aggregated_response and not celery_task_instance.custom_revocation_flag and not celery_task_instance.interrupted_by_soft_limit_in_consumer :
        logger.warning(f"{log_prefix} Aggregated AI response is empty (and not due to interruption). Skipping persistence to Directus for chat {request_data.chat_id}.")

    return aggregated_response


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
        directus_service_instance = DirectusService(
            secrets_manager=secrets_manager, 
            cache_service=cache_service_instance
        ) # Adjust constructor as per actual DirectusService
        logger.info(f"[Task ID: {task_id}] DirectusService initialized.")
        
        encryption_service_instance = EncryptionService(
            secrets_manager=secrets_manager, 
            cache_service=cache_service_instance
        ) # Adjust constructor as per actual EncryptionService
        logger.info(f"[Task ID: {task_id}] EncryptionService initialized.")

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
            discovered_apps_metadata_json = await cache_service_instance.get(DISCOVERED_APPS_METADATA_CACHE_KEY)
            if discovered_apps_metadata_json:
                try:
                    raw_metadata = json.loads(discovered_apps_metadata_json)
                    discovered_apps_metadata = {
                        app_id: AppYAML(**meta_dict)
                        for app_id, meta_dict in raw_metadata.items()
                    }
                    logger.info(f"[Task ID: {task_id}] Successfully loaded and parsed discovered_apps_metadata from cache.")
                except json.JSONDecodeError as jde:
                    logger.error(f"[Task ID: {task_id}] Failed to parse discovered_apps_metadata from cache (JSONDecodeError): {jde}", exc_info=True)
                except ValidationError as ve:
                    logger.error(f"[Task ID: {task_id}] Failed to validate discovered_apps_metadata from cache (Pydantic ValidationError): {ve}", exc_info=True)
                except Exception as e_parse:
                    logger.error(f"[Task ID: {task_id}] Unexpected error parsing discovered_apps_metadata from cache: {e_parse}", exc_info=True)
            else:
                logger.warning(f"[Task ID: {task_id}] {DISCOVERED_APPS_METADATA_CACHE_KEY} not found in cache. Proceeding with empty discovered_apps_metadata.")
        else:
            logger.error(f"[Task ID: {task_id}] CacheService instance not available for loading discovered_apps_metadata.")
    except Exception as e_cache_get:
        logger.error(f"[Task ID: {task_id}] Error loading discovered_apps_metadata from cache: {e_cache_get}", exc_info=True)


    # --- Fetch user-specific data ---
    user_app_memories_metadata: Dict[str, List[str]] = {}
    user_vault_key_id: Optional[str] = None
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
            
            user_details = await directus_service_instance.get_user_fields_direct(
                user_id_hash=request_data.user_id_hash, fields=["vault_key_id"]
            )
            if user_details and user_details.get("vault_key_id"):
                user_vault_key_id = user_details["vault_key_id"]
        except Exception as e:
            logger.error(f"[Task ID: {task_id}] Error during Directus ops for memories/vault_key: {e}", exc_info=True)
    elif not directus_service_instance:
        logger.warning(f"[Task ID: {task_id}] DirectusService not available. Cannot fetch user app memories or vault key.")


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
            user_app_data_metadata=user_app_memories_metadata,
            cache_service=cache_service_instance
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
                                await cache_service_instance.publish(error_redis_channel, json.dumps(error_event_payload))
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
            celery_task_instance=celery_task_instance # Pass the Celery task instance
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
