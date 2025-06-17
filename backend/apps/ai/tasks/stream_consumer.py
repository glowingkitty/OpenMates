# backend/apps/ai/tasks/stream_consumer.py
# Handles the consumption of the main processing stream for AI tasks.

import logging
import json
import time
import httpx
import os
from typing import Dict, Any, List, Optional, AsyncIterator, Union

from celery.exceptions import SoftTimeLimitExceeded
from celery.states import REVOKED as TASK_STATE_REVOKED # Module-level import

# Import services and schemas (adjust paths if necessary based on actual locations)
from backend.core.api.app.tasks import celery_config
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

from backend.apps.ai.skills.ask_skill import AskSkillRequest # For type hinting request_data
from backend.apps.ai.processing.preprocessor import PreprocessingResult # For type hinting preprocessing_result
from backend.shared.python_schemas.app_metadata_schemas import AppYAML # For type hinting discovered_apps_metadata
from backend.apps.ai.utils.mate_utils import MateConfig # For type hinting all_mates_configs
from backend.apps.ai.processing.main_processor import handle_main_processing, INTERNAL_API_BASE_URL, INTERNAL_API_SHARED_TOKEN # The stream source
from backend.apps.ai.utils.llm_utils import log_main_llm_stream_aggregated_output # Import the new logging function
from backend.shared.python_utils.billing_utils import calculate_total_credits, calculate_real_and_charged_costs
from backend.apps.ai.llm_providers.mistral_client import MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata

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
    secrets_manager: Optional[SecretsManager] = None, # Added SecretsManager
) -> tuple[str, bool, bool]:
    """
    Consumes the async stream from handle_main_processing, aggregates the response,
    and publishes chunks to Redis Pub/Sub.
    Returns aggregated response, and boolean flags for revocation and soft limit.
    """
    final_response_chunks = []
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _consume_main_processing_stream:"
    logger.info(f"{log_prefix} Starting to consume stream from main_processor.")

    # Local flags for interruption status
    was_revoked_during_stream = False
    was_soft_limited_during_stream = False

    # Check for revocation before starting
    # Use AsyncResult to check task status
    if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
        logger.warning(f"{log_prefix} Task was revoked before starting main processing stream.")
        was_revoked_during_stream = True
        return "", was_revoked_during_stream, was_soft_limited_during_stream

    main_processing_stream: AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata]] = handle_main_processing(
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
    usage: Optional[Union[MistralUsage, GoogleUsageMetadata]] = None
    redis_channel_name = f"chat_stream::{request_data.chat_id}"

    try:
        async for chunk in main_processing_stream:
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata)):
                usage = chunk
                continue
            if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
                logger.warning(f"{log_prefix} Task revoked during main processing stream. Processing partial response.")
                was_revoked_during_stream = True
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
                        "user_id_uuid": request_data.user_id, # ADDING USER UUID
                        "user_id_hash": request_data.user_id_hash, # Keep hash for potential other uses
                        "message_id": task_id,
                        "user_message_id": request_data.message_id,
                        "full_content_so_far": current_full_content_so_far,
                        "sequence": stream_chunk_count,
                        "is_final_chunk": False
                    }
                    # REMOVED: json_payload = json.dumps(payload)
                    await cache_service.publish_event(redis_channel_name, payload) # PASS DICT DIRECTLY
                    if stream_chunk_count % 5 == 0 or len(current_full_content_so_far) % 1000 < len(chunk): # Log less frequently
                        logger.info(f"{log_prefix} Published accumulated message (seq: {stream_chunk_count}) to Redis '{redis_channel_name}'. Total length: {len(current_full_content_so_far)}")
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to publish accumulated message (seq: {stream_chunk_count}) to Redis: {e}", exc_info=True)
            elif stream_chunk_count == 1: # Log warning only once if cache is unavailable
                     logger.warning(f"{log_prefix} Cache service not available. Skipping Redis publish for chunks.")
    except SoftTimeLimitExceeded:
        logger.warning(f"{log_prefix} Soft time limit exceeded during main processing stream. Processing partial response.")
        was_soft_limited_during_stream = True
    except Exception as e:
        logger.error(f"{log_prefix} Exception during main processing stream consumption: {e}", exc_info=True)
        # Check if revoked after an unexpected error
        if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
            was_revoked_during_stream = True

    aggregated_response = "".join(final_response_chunks)
    log_msg_suffix = f"Total chunks: {stream_chunk_count}. Aggregated response length: {len(aggregated_response)}."
    stream_error_message_for_log: Optional[str] = None

    if was_revoked_during_stream:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY REVOCATION). {log_msg_suffix}")
        stream_error_message_for_log = "Stream consumption interrupted by task revocation."
    elif was_soft_limited_during_stream:
        logger.info(f"{log_prefix} Finished consuming stream (INTERRUPTED BY SOFT LIMIT). {log_msg_suffix}")
        stream_error_message_for_log = "Stream consumption interrupted by soft time limit."
    else:
        logger.info(f"{log_prefix} Finished consuming stream (COMPLETED). {log_msg_suffix}")

    # Log the aggregated output (or error) using the utility from llm_utils
    try:
        log_main_llm_stream_aggregated_output(task_id, aggregated_response, error_message=stream_error_message_for_log)
    except Exception as e_log_output:
        logger.error(f"{log_prefix} Failed to log main LLM stream aggregated output: {e_log_output}", exc_info=True)

    # Publish final marker to Redis
    if cache_service:
        try:
            final_payload = {
                "type": "ai_message_chunk",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id, # ADDING USER UUID
                "user_id_hash": request_data.user_id_hash, # Keep hash
                "message_id": task_id, # This is the AI's message ID, same as task_id
                "user_message_id": request_data.message_id, # The user's message ID that triggered this AI response
                "full_content_so_far": None, # No need to send full content in final marker
                "sequence": stream_chunk_count + 1,
                "is_final_chunk": True,
                "interrupted_by_soft_limit": was_soft_limited_during_stream,
                "interrupted_by_revocation": was_revoked_during_stream
            }
            # REMOVED: json_final_payload = json.dumps(final_payload)
            await cache_service.publish_event(redis_channel_name, final_payload) # PASS DICT DIRECTLY
            logger.info(f"{log_prefix} Published final marker (seq: {stream_chunk_count + 1}, interrupted_soft: {was_soft_limited_during_stream}, interrupted_revoke: {was_revoked_during_stream}) to Redis channel '{redis_channel_name}'.")
        except Exception as e:
            logger.error(f"{log_prefix} Failed to publish final marker to Redis: {e}", exc_info=True)

    # --- Billing Logic ---
    if usage:
        input_tokens = usage.prompt_tokens if isinstance(usage, MistralUsage) else usage.prompt_token_count
        output_tokens = usage.completion_tokens if isinstance(usage, MistralUsage) else usage.candidates_token_count

        if not celery_config.config_manager:
            logger.critical(f"{log_prefix} ConfigManager not initialized. Billing cannot proceed.")
            raise RuntimeError("Billing configuration is not available. Task cannot be completed.")

        provider_name = "mistral" if "mistral" in preprocessing_result.selected_main_llm_model_id else "google"
        logger.info(f"{log_prefix} Determined provider_name for billing: {provider_name}")

        pricing_config = celery_config.config_manager.get_provider_config(provider_name)
        if not pricing_config:
            logger.critical(f"{log_prefix} Could not load pricing_config for provider '{provider_name}'. Billing cannot proceed.")
            raise RuntimeError(f"Pricing configuration for provider '{provider_name}' is not available.")

        model_id_suffix = preprocessing_result.selected_main_llm_model_id.split('/')[-1]
        logger.info(f"{log_prefix} Extracted model_id_suffix for pricing lookup: {model_id_suffix}")

        model_pricing_details = celery_config.config_manager.get_model_pricing(provider_name, model_id_suffix)
        if not model_pricing_details:
            logger.critical(f"{log_prefix} Could not find model_pricing_details for '{model_id_suffix}' with provider '{provider_name}'. Billing cannot proceed.")
            raise RuntimeError(f"Pricing details for model '{model_id_suffix}' are not available.")

        credits_charged = calculate_total_credits(
            pricing_config=model_pricing_details,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
        
        costs = calculate_real_and_charged_costs(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_pricing_details=model_pricing_details,
            total_credits_charged=credits_charged,
            pricing_config=pricing_config
        )

        logger.info(f"{log_prefix} Billing calculation: "
                    f"Input Tokens: {input_tokens}, Output Tokens: {output_tokens}, "
                    f"Credits Charged: {credits_charged}, Real Cost: ${costs['real_cost_usd']:.6f}, "
                    f"Charged Cost: ${costs['charged_cost_usd']:.6f}, Margin: ${costs['margin_usd']:.6f}")

        if credits_charged > 0:
            try:
                app_id, skill_id_in_app = "ai", "ask"
                
                charge_payload = {
                    "user_id": request_data.user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "credits": credits_charged,
                    "skill_id": skill_id_in_app,
                    "app_id": app_id,
                    "usage_details": {
                        **costs,
                        "model_used": preprocessing_result.selected_main_llm_model_id,
                        "chat_id": request_data.chat_id,
                        "message_id": request_data.message_id,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens
                    }
                }

                headers = {"Content-Type": "application/json"}
                if INTERNAL_API_SHARED_TOKEN:
                    headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
                
                async with httpx.AsyncClient() as client:
                    url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
                    logger.info(f"{log_prefix} Attempting to charge credits. URL: {url}, Payload: {charge_payload}")
                    response = await client.post(url, json=charge_payload, headers=headers)
                    response.raise_for_status()
                    logger.info(f"{log_prefix} Successfully charged {credits_charged} credits to user {request_data.user_id}. Response: {response.json()}")

            except httpx.RequestError as e:
                logger.error(f"{log_prefix} HTTP Request Error while charging credits for user {request_data.user_id}: {e}", exc_info=True)
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"{log_prefix} HTTP Status Error while charging credits for user {request_data.user_id}: {e.response.status_code} - {e.response.text}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"{log_prefix} An unexpected error occurred while charging credits for user {request_data.user_id}: {e}", exc_info=True)
                raise

    # Persist final AI message to Directus
    # Only persist if there's a response AND the stream wasn't significantly interrupted
    # (e.g. if revoked at the very start, aggregated_response might be empty)
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
                ai_role = "assistant"
                
                # CORRECTED LOGIC FOR ai_category
                ai_category = preprocessing_result.category # Use the actual category from preprocessing
                if not ai_category: # Fallback if category is somehow None
                    logger.warning(f"{log_prefix} Preprocessing result category is None. Falling back to 'general_knowledge'.")
                    ai_category = "general_knowledge"
                
                # sender_name is no longer used.

                message_payload_to_directus = {
                    "client_message_id": task_id, 
                    "chat_id": request_data.chat_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "role": ai_role,
                    "category": ai_category,
                    "encrypted_content": encrypted_ai_response,
                    "created_at": current_timestamp,
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
                            "last_message_timestamp": current_timestamp,
                            "last_mate_category": preprocessing_result.category
                        }
                        
                        updated_chat_metadata_success = await directus_service.chat.update_chat_fields_in_directus(
                            request_data.chat_id,
                            fields_to_update
                        )
                        if updated_chat_metadata_success:
                            logger.info(f"{log_prefix} Successfully updated chat metadata for {request_data.chat_id}: messages_version to {new_messages_version}, timestamps to {current_timestamp}.")

                            # Also save the AI message to the cache
                            if cache_service:
                                from backend.core.api.app.schemas.chat import MessageInCache
                                ai_message_for_cache = MessageInCache(
                                    id=task_id,
                                    chat_id=request_data.chat_id,
                                    role=ai_role,
                                    category=ai_category,
                                    sender_name=None, # sender_name is deprecated
                                    content=tiptap_payload,
                                    created_at=current_timestamp,
                                    status="delivered"
                                )
                                await cache_service.save_chat_message_and_update_versions(
                                    user_id=request_data.user_id,
                                    chat_id=request_data.chat_id,
                                    message_data=ai_message_for_cache,
                                    last_mate_category=ai_category
                                )
                                logger.info(f"{log_prefix} Saved AI message to cache for chat {request_data.chat_id}.")

                            # Publish 'ai_message_persisted' event to Redis for client notification
                            if cache_service:
                                persisted_event_payload = {
                                    "type": "ai_message_persisted",
                                    "event_for_client": "chat_message_added",
                                    "chat_id": request_data.chat_id,
                                    "user_id_uuid": request_data.user_id, 
                                    "user_id_hash": request_data.user_id_hash,
                                    "message": {
                                        "message_id": task_id,
                                        "role": ai_role,
                                        "category": ai_category, # Ensure corrected value is used
                                        # "sender_name": ai_sender_name, # REMOVED
                                        "content": tiptap_payload,
                                        "timestamp": current_timestamp,
                                        "status": "synced",
                                    },
                                    "versions": {"messages_v": new_messages_version},
                                    "last_edited_overall_timestamp": current_timestamp
                                }
                                persisted_redis_channel = f"ai_message_persisted::{request_data.user_id_hash}" # User-specific channel
                                try:
                                    # REMOVED: json.dumps() around persisted_event_payload
                                    await cache_service.publish_event(persisted_redis_channel, persisted_event_payload) # PASS DICT DIRECTLY
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
    elif not aggregated_response and not was_revoked_during_stream and not was_soft_limited_during_stream : # Check local flags
        logger.warning(f"{log_prefix} Aggregated AI response is empty (and not due to interruption). Skipping persistence to Directus for chat {request_data.chat_id}.")
            
    return aggregated_response, was_revoked_during_stream, was_soft_limited_during_stream
