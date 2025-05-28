# backend/apps/ai/tasks/stream_consumer.py
# Handles the consumption of the main processing stream for AI tasks.

import logging
import json
import time
from typing import Dict, Any, List, Optional, AsyncIterator

from celery.exceptions import SoftTimeLimitExceeded

# Import services and schemas (adjust paths if necessary based on actual locations)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

from backend.apps.ai.skills.ask_skill import AskSkillRequest # For type hinting request_data
from backend.apps.ai.processing.preprocessor import PreprocessingResult # For type hinting preprocessing_result
from backend.shared.python_schemas.app_metadata_schemas import AppYAML # For type hinting discovered_apps_metadata
from backend.apps.ai.utils.mate_utils import MateConfig # For type hinting all_mates_configs
from backend.apps.ai.processing.main_processor import handle_main_processing # The stream source

logger = logging.getLogger(__name__)

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
    celery_task_instance: Any, # Celery task instance
    secrets_manager: Optional[SecretsManager] = None # Added SecretsManager
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
        discovered_apps_metadata=discovered_apps_metadata,
        secrets_manager=secrets_manager # Pass SecretsManager
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
                    if stream_chunk_count % 5 == 0 or len(current_full_content_so_far) % 1000 < len(chunk): # Log less frequently
                        logger.info(f"{log_prefix} Published accumulated message (seq: {stream_chunk_count}) to Redis '{redis_channel_name}'. Total length: {len(current_full_content_so_far)}")
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to publish accumulated message (seq: {stream_chunk_count}) to Redis: {e}", exc_info=True)
            elif stream_chunk_count == 1: # Log warning only once if cache is unavailable
                     logger.warning(f"{log_prefix} Cache service not available. Skipping Redis publish for chunks.")
    except SoftTimeLimitExceeded:
        logger.warning(f"{log_prefix} Soft time limit exceeded during main processing stream. Processing partial response.")
        celery_task_instance.interrupted_by_soft_limit_in_consumer = True
    except Exception as e:
        logger.error(f"{log_prefix} Exception during main processing stream consumption: {e}", exc_info=True)
        if celery_task_instance and celery_task_instance.is_revoked(): # Check if revoked after an unexpected error
            celery_task_instance.custom_revocation_flag = True

    aggregated_response = "".join(final_response_chunks)
    log_msg_suffix = f"Total chunks: {stream_chunk_count}. Aggregated response length: {len(aggregated_response)}."

    if celery_task_instance.custom_revocation_flag:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY REVOCATION). {log_msg_suffix}")
    elif celery_task_instance.interrupted_by_soft_limit_in_consumer:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY SOFT LIMIT). {log_msg_suffix}")
    else:
        logger.info(f"{log_prefix} Finished consuming stream (COMPLETED). {log_msg_suffix}")

    # Publish final marker to Redis
    if cache_service:
        try:
            final_payload = {
                "type": "ai_message_chunk",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "message_id": task_id, # This is the AI's message ID, same as task_id
                "user_message_id": request_data.message_id, # The user's message ID that triggered this AI response
                "full_content_so_far": None, # No need to send full content in final marker
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

    # Persist final AI message to Directus
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
                    "client_message_id": task_id, # AI message ID is the task_id
                    "chat_id": request_data.chat_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "sender_name": preprocessing_result.selected_mate_id or "ai",
                    "encrypted_content": encrypted_ai_response,
                    "created_at": current_timestamp,
                    # "status": "synced", # Assuming Directus handles this or it's set by default
                }
                
                created_message_directus = await directus_service.chat.create_message_in_directus(message_payload_to_directus)
                if created_message_directus:
                    logger.info(f"{log_prefix} Successfully persisted AI message to Directus for chat {request_data.chat_id}. Directus Msg ID: {created_message_directus.get('id')}")

                    # Update chat metadata (versions, timestamps)
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

                            # Publish 'ai_message_persisted' event to Redis for client notification
                            if cache_service:
                                persisted_event_payload = {
                                    "type": "ai_message_persisted", # Internal event type
                                    "event_for_client": "chat_message_added", # Client-facing event name
                                    "chat_id": request_data.chat_id,
                                    "user_id_hash": request_data.user_id_hash, # For targeted client updates
                                    "message": { # The message object as the client expects it
                                        "message_id": task_id, # AI message ID
                                        "sender_name": preprocessing_result.selected_mate_id or "ai",
                                        "content": tiptap_payload, # Unencrypted content for the client
                                        "timestamp": current_timestamp,
                                        "status": "synced", # Or whatever status is appropriate
                                    },
                                    "versions": {"messages_v": new_messages_version},
                                    "last_edited_overall_timestamp": current_timestamp
                                }
                                persisted_redis_channel = f"ai_message_persisted::{request_data.user_id_hash}" # User-specific channel
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
