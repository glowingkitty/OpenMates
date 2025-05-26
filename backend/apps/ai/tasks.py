# backend/apps/ai/tasks.py
# Celery tasks for the AI App.

import logging
import asyncio
import json # Added for Redis payload serialization
import time # For timestamps
from typing import Dict, Any, List, Optional, AsyncIterator
from pydantic import ValidationError
from celery.exceptions import Ignore, SoftTimeLimitExceeded

# Import the FastAPI app instance to access its state, including services
try:
    from backend.core.api.main import app as fastapi_app
except ImportError:
    fastapi_app = None 
    logging.getLogger(__name__).error("Failed to import fastapi_app from backend.core.api.main. Services will not be available for Celery task.")

# Import EncryptionService & CacheService
try:
    from backend.core.api.app.services.encryption import EncryptionService
except ImportError:
    EncryptionService = None
    logging.getLogger(__name__).error("Failed to import EncryptionService. Message encryption will not be available.")

try:
    from backend.core.api.app.services.cache import CacheService
except ImportError:
    CacheService = None 
    logging.getLogger(__name__).error("Failed to import CacheService. Credit check and Redis ops might fail.")


from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest # Import from shared schema
from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig # Keep this if AskSkillDefaultConfig is local to ask_skill.py
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
from backend.apps.base_app import AppYAML
from backend.apps.ai.processing.preprocessor import handle_preprocessing, PreprocessingResult
from backend.apps.ai.processing.main_processor import handle_main_processing

logger = logging.getLogger(__name__)

async def _consume_main_processing_stream(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_result: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: Optional[Any], 
    encryption_service: Optional[EncryptionService], 
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    cache_service: Optional[CacheService], 
    celery_task_instance 
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

                    chat_metadata = await directus_service.chat.get_chat_metadata(directus_service, request_data.chat_id)
                    if chat_metadata:
                        new_messages_version = chat_metadata.get("messages_version", 0) + 1
                        fields_to_update = {
                            "messages_version": new_messages_version,
                            "last_edited_overall_timestamp": current_timestamp,
                            "last_message_timestamp": current_timestamp
                        }
                        
                        updated_chat_metadata_success = await directus_service.chat.update_chat_fields_in_directus(
                            directus_service,
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


@celery_app.task(bind=True, name="ai.process_skill_ask", soft_time_limit=300, time_limit=360)
def process_ai_skill_ask_task(self, request_data_dict: dict, skill_config_dict: dict):
    task_id = self.request.id
    logger.info(f"[Task ID: {task_id}] Received ai.process_skill_ask task. Request: {request_data_dict}, Skill Config: {skill_config_dict}")

    # Initialize custom flags for interruption status propagation
    self.custom_revocation_flag = False 
    self.interrupted_by_soft_limit_in_consumer = False

    try:
        request_data = AskSkillRequest(**request_data_dict)
        skill_config = AskSkillDefaultConfig(**skill_config_dict)
    except ValidationError as e:
        logger.error(f"[Task ID: {task_id}] Validation error for input data: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': 'ValidationError', 'exc_message': str(e.errors())})
        raise Ignore()

    base_instructions = load_base_instructions()
    if not base_instructions:
        logger.error(f"[Task ID: {task_id}] Failed to load base_instructions.yml. Aborting task.")
        self.update_state(state='FAILURE', meta={'exc_type': 'FileNotFoundError', 'exc_message': 'base_instructions.yml not found or empty.'})
        raise Ignore()

    all_mates_configs: List[MateConfig] = load_mates_config()
    if not all_mates_configs:
        logger.critical(f"[Task ID: {task_id}] Failed to load mates_config.yml or it was empty. Aborting task.")
        self.update_state(state='FAILURE', meta={'exc_type': 'FileNotFoundError', 'exc_message': 'mates.yml not found, empty, or invalid.'})
        raise Ignore()

    user_app_memories_metadata: Dict[str, List[str]] = {}
    user_vault_key_id: Optional[str] = None
    directus_service_instance = None
    cache_service_instance = None
    encryption_service_instance = None
    discovered_apps_metadata: Dict[str, AppYAML] = {}

    if fastapi_app:
        if hasattr(fastapi_app.state, 'directus_service') and request_data.user_id_hash:
            directus_service_instance = fastapi_app.state.directus_service
            if directus_service_instance:
                try:
                    # Fetch metadata (app_id, item_key) for all settings/memories for the user
                    raw_items_metadata: List[Dict[str, Any]] = asyncio.run(
                        directus_service_instance.app_settings_and_memories.get_user_app_data_metadata(request_data.user_id_hash)
                    )
                    for item_meta in raw_items_metadata:
                        app_id_key = item_meta.get("app_id")
                        item_key_val = item_meta.get("item_key")
                        if app_id_key and item_key_val:
                            if app_id_key not in user_app_memories_metadata: # Keep variable name for now, or rename to user_app_data_metadata
                                user_app_memories_metadata[app_id_key] = []
                            if item_key_val not in user_app_memories_metadata[app_id_key]:
                                user_app_memories_metadata[app_id_key].append(item_key_val)
                    
                    user_details = asyncio.run(
                        directus_service_instance.get_user_fields_direct(
                            user_id_hash=request_data.user_id_hash, fields=["vault_key_id"]
                        )
                    )
                    if user_details and user_details.get("vault_key_id"):
                        user_vault_key_id = user_details["vault_key_id"]
                except Exception as e: # Catch broad exception for Directus ops
                    logger.error(f"[Task ID: {task_id}] Error during Directus ops for memories/vault_key: {e}", exc_info=True)
        
        if CacheService and hasattr(fastapi_app.state, 'cache_service'):
            cache_service_instance = fastapi_app.state.cache_service
        
        if EncryptionService and hasattr(fastapi_app.state, 'encryption_service'):
            encryption_service_instance = fastapi_app.state.encryption_service
        
        if hasattr(fastapi_app.state, 'discovered_apps_metadata'):
            discovered_apps_metadata = fastapi_app.state.discovered_apps_metadata
    else:
        logger.warning(f"[Task ID: {task_id}] fastapi_app instance not available. Services will be unavailable.")

    # --- Step 1: Preprocessing ---
    logger.info(f"[Task ID: {task_id}] Starting preprocessing step...")
    self.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'started'})
    
    try:
        if not cache_service_instance:
            logger.error(f"[Task ID: {task_id}] CacheService instance is not available. Cannot proceed with preprocessing credit check.")
            self.update_state(state='FAILURE', meta={'exc_type': 'ServiceUnavailable', 'exc_message': 'CacheService not available for preprocessing.'})
            raise Ignore() # Critical failure

        preprocessing_result: PreprocessingResult = asyncio.run(handle_preprocessing(
            request_data=request_data,
            skill_config=skill_config,
            base_instructions=base_instructions,
            user_app_data_metadata=user_app_memories_metadata, # Pass the fetched metadata
            cache_service=cache_service_instance
        ))
        logger.info(f"[Task ID: {task_id}] Preprocessing completed. Result: {preprocessing_result.model_dump_json(indent=2)}")
        self.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'completed', 'result': preprocessing_result.model_dump()})

        if not preprocessing_result.can_proceed:
            logger.warning(f"[Task ID: {task_id}] Preprocessing determined request cannot proceed. Reason: {preprocessing_result.rejection_reason}. Message: {preprocessing_result.error_message}")
            
            if directus_service_instance and encryption_service_instance and cache_service_instance and preprocessing_result.error_message:
                try:
                    logger.info(f"[Task ID: {task_id}] Persisting preprocessing error message to Directus and notifying client.")
                    error_tiptap_payload = {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": preprocessing_result.error_message}]}]
                    }
                    encrypted_error_content = asyncio.run(encryption_service_instance.encrypt_with_chat_key(
                        key_id=request_data.chat_id,
                        plaintext=json.dumps(error_tiptap_payload)
                    ))

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
                        created_error_msg_directus = asyncio.run(
                            directus_service_instance.chat.create_message_in_directus(error_message_directus_payload)
                        )

                        if created_error_msg_directus:
                            chat_metadata = asyncio.run(directus_service_instance.chat.get_chat_metadata(directus_service_instance, request_data.chat_id))
                            if chat_metadata:
                                new_messages_version = chat_metadata.get("messages_version", 0) + 1
                                fields_to_update = {
                                    "messages_version": new_messages_version,
                                    "last_edited_overall_timestamp": current_timestamp,
                                    "last_message_timestamp": current_timestamp
                                }
                                asyncio.run(directus_service_instance.chat.update_chat_fields_in_directus(
                                    directus_service_instance, request_data.chat_id, fields_to_update
                                ))
                                
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
                                asyncio.run(cache_service_instance.publish(error_redis_channel, json.dumps(error_event_payload)))
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
            self.update_state(state='FAILURE', meta=rejection_details)
            return {"task_id": task_id, **rejection_details}
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': str(type(e).__name__), 'exc_message': str(e), 'step': 'preprocessing'})
        raise Ignore()

    # --- Step 2: Main Processing (with streaming) ---
    logger.info(f"[Task ID: {task_id}] Starting main processing step (streaming)...")
    self.update_state(state='PROGRESS', meta={'step': 'main_processing', 'status': 'started_streaming'})
    
    aggregated_final_response: str = ""
    try:
        aggregated_final_response = asyncio.run(_consume_main_processing_stream(
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
            celery_task_instance=self
        ))
        logger.info(f"[Task ID: {task_id}] Main processing stream consumed.")
        summary_response = aggregated_final_response[:500] + "..." if len(aggregated_final_response) > 500 else aggregated_final_response
        self.update_state(state='PROGRESS', meta={'step': 'main_processing', 'status': 'completed_streaming', 'output_summary': summary_response})

    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded during task execution (around _consume_main_processing_stream).")
        self.interrupted_by_soft_limit_in_consumer = True 
    except Exception as e:
        if self.is_revoked():
            logger.warning(f"[Task ID: {task_id}] Task revoked during or after main processing stream execution.")
            self.custom_revocation_flag = True
        else:
            logger.error(f"[Task ID: {task_id}] Error during main processing stream execution: {e}", exc_info=True)
            self.update_state(state='FAILURE', meta={'exc_type': str(type(e).__name__), 'exc_message': str(e), 'step': 'main_processing_stream_execution'})
            raise Ignore()

    final_status_message = "completed"
    log_final_status = "successfully"

    if self.interrupted_by_soft_limit_in_consumer:
        final_status_message = "completed_partially_soft_limit"
        log_final_status = "partially completed (interrupted by soft time limit)"
    elif self.custom_revocation_flag or self.is_revoked(): 
        final_status_message = "completed_partially_revoked"
        log_final_status = "partially completed (interrupted by revocation)"

    logger.info(f"[Task ID: {task_id}] AI skill ask task processing finished {log_final_status}.")
    
    final_summary_response = aggregated_final_response[:500] + "..." if len(aggregated_final_response) > 500 else aggregated_final_response
    
    success_meta = {
        'status_message': final_status_message,
        'preprocessing_summary': preprocessing_result.model_dump(),
        'main_processing_output_summary': final_summary_response,
        'interrupted_by_soft_time_limit': self.interrupted_by_soft_limit_in_consumer,
        'interrupted_by_revocation': self.custom_revocation_flag or self.is_revoked()
    }
    self.update_state(state='SUCCESS', meta=success_meta)
    return {
        "task_id": task_id,
        "status": final_status_message,
        "preprocessing_summary": preprocessing_result.model_dump(),
        "main_processing_output": aggregated_final_response,
        "interrupted_by_soft_time_limit": self.interrupted_by_soft_limit_in_consumer,
        "interrupted_by_revocation": self.custom_revocation_flag or self.is_revoked()
    }