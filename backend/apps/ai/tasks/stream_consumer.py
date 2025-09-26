# backend/apps/ai/tasks/stream_consumer.py
# Handles the consumption of the main processing stream for AI tasks.

import logging
import json
import time
import httpx
from typing import Dict, Any, List, Optional, AsyncIterator, Union

from celery.exceptions import SoftTimeLimitExceeded
from celery.states import REVOKED as TASK_STATE_REVOKED

from backend.core.api.app.tasks import celery_config
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.translations import TranslationService

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.shared.python_schemas.app_metadata_schemas import AppYAML
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.processing.main_processor import handle_main_processing, INTERNAL_API_BASE_URL, INTERNAL_API_SHARED_TOKEN
from backend.apps.ai.utils.llm_utils import log_main_llm_stream_aggregated_output
from backend.shared.python_utils.billing_utils import calculate_total_credits, calculate_real_and_charged_costs
from backend.apps.ai.llm_providers.mistral_client import MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata
from backend.apps.ai.llm_providers.anthropic_client import AnthropicUsageMetadata
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata

logger = logging.getLogger(__name__)

# Type alias for usage metadata
UsageMetadata = Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]

def _create_redis_payload(
    task_id: str,
    request_data: AskSkillRequest,
    content: str,
    sequence: int,
    is_final: bool = False,
    interrupted_soft: bool = False,
    interrupted_revoke: bool = False
) -> Dict[str, Any]:
    """Create standardized Redis payload for streaming chunks."""
    payload = {
        "type": "ai_message_chunk",
        "task_id": task_id,
        "chat_id": request_data.chat_id,
        "user_id_uuid": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "message_id": task_id,
        "user_message_id": request_data.message_id,
        "full_content_so_far": content,
        "sequence": sequence,
        "is_final_chunk": is_final
    }
    
    if is_final:
        payload.update({
            "interrupted_by_soft_limit": interrupted_soft,
            "interrupted_by_revocation": interrupted_revoke
        })
    
    return payload

async def _publish_to_redis(
    cache_service: Optional[CacheService],
    channel: str,
    payload: Dict[str, Any],
    log_prefix: str,
    action_description: str
) -> None:
    """Publish payload to Redis with error handling."""
    if not cache_service:
        return
        
    try:
        await cache_service.publish_event(channel, payload)
        logger.info(f"{log_prefix} {action_description}")
    except Exception as e:
        logger.error(f"{log_prefix} Failed to {action_description.lower()}: {e}", exc_info=True)

async def _charge_credits(
    task_id: str,
    request_data: AskSkillRequest,
    credits: int,
    usage_details: Dict[str, Any],
    log_prefix: str
) -> None:
    """Handle credit charging with error handling."""
    if credits <= 0:
        return
        
    charge_payload = {
        "user_id": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "credits": credits,
        "skill_id": "ask",
        "app_id": "ai",
        "usage_details": usage_details
    }
    
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    
    try:
        async with httpx.AsyncClient() as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            logger.info(f"{log_prefix} Charging {credits} credits. Payload: {charge_payload}")
            response = await client.post(url, json=charge_payload, headers=headers)
            response.raise_for_status()
            logger.info(f"{log_prefix} Successfully charged {credits} credits. Response: {response.json()}")
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits: {e}", exc_info=True)
        raise


async def _update_chat_metadata(
    request_data: AskSkillRequest,
    category: str,
    timestamp: int,
    directus_service: DirectusService,
    cache_service: Optional[CacheService],
    task_id: str,
    log_prefix: str
) -> None:
    """Update chat metadata and publish events."""
    chat_metadata = await directus_service.chat.get_chat_metadata(request_data.chat_id)
    if not chat_metadata:
        logger.error(f"{log_prefix} Failed to fetch chat metadata for {request_data.chat_id}.")
        return
        
    new_messages_version = chat_metadata.get("messages_version", 0) + 1
    fields_to_update = {
        "messages_version": new_messages_version,
        "last_edited_overall_timestamp": timestamp,
        "last_message_timestamp": timestamp,
        "last_mate_category": category
    }
    
    success = await directus_service.chat.update_chat_fields_in_directus(
        request_data.chat_id, fields_to_update
    )
    
    if not success:
        logger.error(f"{log_prefix} Failed to update chat metadata for {request_data.chat_id}.")
        return
        
    logger.info(f"{log_prefix} Updated chat metadata: version {new_messages_version}, timestamp {timestamp}.")
    
    # Save to cache and publish events
    if cache_service:
        await _save_to_cache_and_publish(
            request_data, task_id, category, timestamp,
            new_messages_version, cache_service, log_prefix
        )

async def _save_to_cache_and_publish(
    request_data: AskSkillRequest,
    task_id: str,
    category: str,
    timestamp: int,
    messages_version: int,
    cache_service: CacheService,
    log_prefix: str
) -> None:
    """Save message to cache and publish persistence event."""
    try:
        from backend.core.api.app.schemas.chat import MessageInCache
        
        # For cache: Use server-side encryption for performance (last 3 chats)
        # This is different from Directus storage which must be zero-knowledge
        # Cache is temporary and server can decrypt for AI processing context
        
        # Store pure markdown content in cache (server-side encrypted)
        # NEVER store Tiptap JSON on server - only markdown!
        ai_message_for_cache = MessageInCache(
            id=task_id,
            chat_id=request_data.chat_id,
            role="assistant",
            category=category,
            sender_name=None,
            content=content,  # Store pure markdown content in cache
            created_at=timestamp,
            status="delivered"
        )
        
        await cache_service.save_chat_message_and_update_versions(
            user_id=request_data.user_id,
            chat_id=request_data.chat_id,
            message_data=ai_message_for_cache,
            last_mate_category=category
        )
        
        logger.info(f"{log_prefix} Saved message to cache for chat {request_data.chat_id}.")
        
        # Publish persistence event
        persisted_event_payload = {
            "type": "ai_message_persisted",
            "event_for_client": "chat_message_added",
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "message": {
                "message_id": task_id,
                "chat_id": request_data.chat_id,
                "role": "assistant",
                "category": category,
                "content": tiptap_payload,
                "created_at": timestamp,
                "status": "synced",
            },
            "versions": {"messages_v": messages_version},
            "last_edited_overall_timestamp": timestamp
        }
        
        persisted_channel = f"ai_message_persisted::{request_data.user_id_hash}"
        await _publish_to_redis(
            cache_service, persisted_channel, persisted_event_payload,
            log_prefix, f"Published 'ai_message_persisted' event to channel '{persisted_channel}'"
        )
        
    except Exception as e:
        logger.error(f"{log_prefix} Error saving to cache or publishing: {e}", exc_info=True)

async def _handle_normal_billing(
    usage: UsageMetadata,
    preprocessing_result: PreprocessingResult,
    request_data: AskSkillRequest,
    task_id: str,
    log_prefix: str
) -> None:
    """Handle billing for normal processing flow."""
    # Extract token counts and provider name based on usage type
    if isinstance(usage, MistralUsage):
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        provider_name = "mistral"
    elif isinstance(usage, GoogleUsageMetadata):
        input_tokens = usage.prompt_token_count
        output_tokens = usage.candidates_token_count
        provider_name = "google"
    elif isinstance(usage, AnthropicUsageMetadata):
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        provider_name = "anthropic"
    elif isinstance(usage, OpenAIUsageMetadata):
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        # Determine billing provider from the selected model id prefix (e.g., "alibaba/...", "openai/...")
        try:
            selected_full_model = preprocessing_result.selected_main_llm_model_id or "openai/unknown"
            provider_name = selected_full_model.split("/", 1)[0]
        except Exception:
            provider_name = "openai"
    else:
        logger.error(f"{log_prefix} Unknown usage type: {type(usage)}. Billing cannot proceed.")
        raise RuntimeError(f"Unknown usage metadata type: {type(usage)}")

    if not celery_config.config_manager:
        logger.critical(f"{log_prefix} ConfigManager not initialized. Billing cannot proceed.")
        raise RuntimeError("Billing configuration is not available. Task cannot be completed.")

    logger.info(f"{log_prefix} Determined provider_name for billing: {provider_name}")

    # Get pricing configuration
    pricing_config = celery_config.config_manager.get_provider_config(provider_name)
    if not pricing_config:
        logger.critical(f"{log_prefix} Could not load pricing_config for provider '{provider_name}'. Billing cannot proceed.")
        raise RuntimeError(f"Pricing configuration for provider '{provider_name}' is not available.")

    # Preserve full model suffix after provider prefix (supports nested ids like "alibaba/qwen3-...")
    full_selected_model_id = preprocessing_result.selected_main_llm_model_id
    model_id_suffix = full_selected_model_id.split('/', 1)[1] if '/' in full_selected_model_id else full_selected_model_id
    logger.info(f"{log_prefix} Extracted model_id_suffix for pricing lookup: {model_id_suffix}")

    model_pricing_details = celery_config.config_manager.get_model_pricing(provider_name, model_id_suffix)
    if not model_pricing_details:
        logger.critical(f"{log_prefix} Could not find model_pricing_details for '{model_id_suffix}' with provider '{provider_name}'. Billing cannot proceed.")
        raise RuntimeError(f"Pricing details for model '{model_id_suffix}' are not available.")

    # Calculate costs and credits
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

    # Prepare usage details for billing
    usage_details = {
        **costs,
        "model_used": preprocessing_result.selected_main_llm_model_id,
        "chat_id": request_data.chat_id,
        "message_id": request_data.message_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens
    }

    await _charge_credits(task_id, request_data, credits_charged, usage_details, log_prefix)

async def _generate_fake_stream_for_harmful_content(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_result: PreprocessingResult,
    predefined_response: str,
    cache_service: Optional[CacheService],
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None
) -> tuple[str, bool, bool]:
    """Generate fake stream for harmful content with predefined response."""
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _generate_fake_stream_for_harmful_content:"
    logger.info(f"{log_prefix} Generating fake stream for harmful content.")
    
    # Check for revocation
    if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
        logger.warning(f"{log_prefix} Task was revoked before starting fake stream.")
        return "", True, False
    
    redis_channel = f"chat_stream::{request_data.chat_id}"
    
    # Publish content chunk
    content_payload = _create_redis_payload(task_id, request_data, predefined_response, 1)
    await _publish_to_redis(
        cache_service, redis_channel, content_payload, log_prefix,
        f"Published content chunk to '{redis_channel}'. Length: {len(predefined_response)}"
    )
    
    # Log aggregated output
    try:
        log_main_llm_stream_aggregated_output(task_id, predefined_response, error_message=None)
    except Exception as e:
        logger.error(f"{log_prefix} Failed to log fake stream output: {e}", exc_info=True)
    
    # Publish final marker
    final_payload = _create_redis_payload(task_id, request_data, predefined_response, 2, is_final=True)
    await _publish_to_redis(
        cache_service, redis_channel, final_payload, log_prefix,
        f"Published final marker to '{redis_channel}'"
    )
    
    # Handle billing for harmful content
    usage_details = {
        "real_cost_usd": 0.001,
        "charged_cost_usd": 0.001,
        "margin_usd": 0,
        "model_used": "harmful_content_filter",
        "chat_id": request_data.chat_id,
        "message_id": request_data.message_id,
        "input_tokens": 0,
        "output_tokens": len(predefined_response.split()),
        "rejection_reason": preprocessing_result.rejection_reason
    }
    
    try:
        await _charge_credits(task_id, request_data, 1, usage_details, log_prefix)
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits for harmful content: {e}", exc_info=True)
        # Continue with response even if billing fails
    
    # Note: In zero-knowledge architecture, server does not persist AI responses
    # Client must encrypt AI response and send back to server for storage
    logger.info(f"{log_prefix} Skipping AI message persistence for zero-knowledge architecture.")
    
    logger.info(f"{log_prefix} Fake stream generation completed. Response length: {len(predefined_response)}.")
    return predefined_response, False, False

async def _generate_fake_stream_for_simple_message(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_result: PreprocessingResult,
    message_text: str,
    cache_service: Optional[CacheService],
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None
) -> tuple[str, bool, bool]:
    """Generate a simple fake stream for non-processing cases (e.g., insufficient credits)."""
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _generate_fake_stream_for_simple_message:"
    logger.info(f"{log_prefix} Generating simple fake stream.")

    # Check for revocation
    if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
        logger.warning(f"{log_prefix} Task was revoked before starting fake stream.")
        return "", True, False

    redis_channel = f"chat_stream::{request_data.chat_id}"

    # Publish content chunk
    content_payload = _create_redis_payload(task_id, request_data, message_text, 1)
    await _publish_to_redis(
        cache_service, redis_channel, content_payload, log_prefix,
        f"Published content chunk to '{redis_channel}'. Length: {len(message_text)}"
    )

    # Log aggregated output
    try:
        log_main_llm_stream_aggregated_output(task_id, message_text, error_message=None)
    except Exception as e:
        logger.error(f"{log_prefix} Failed to log fake stream output: {e}", exc_info=True)

    # Publish final marker
    final_payload = _create_redis_payload(task_id, request_data, message_text, 2, is_final=True)
    await _publish_to_redis(
        cache_service, redis_channel, final_payload, log_prefix,
        f"Published final marker to '{redis_channel}'"
    )

    # Note: In zero-knowledge architecture, server does not persist AI responses
    # Client must encrypt AI response and send back to server for storage
    logger.info(f"{log_prefix} Skipping AI message persistence for zero-knowledge architecture.")

    logger.info(f"{log_prefix} Simple fake stream generation completed. Response length: {len(message_text)}.")
    return message_text, False, False

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

    # Check if this is a harmful content case that should be handled with a predefined response
    if not preprocessing_result.can_proceed and preprocessing_result.rejection_reason in ["harmful_or_illegal_detected", "misuse_detected"]:
        logger.info(f"{log_prefix} Detected harmful content case. Generating fake stream with predefined response.")
        
        # Get predefined response from translations
        translation_service = TranslationService()
        language = "en"  # Default to English, could be made dynamic based on user preferences
        
        if preprocessing_result.rejection_reason == "harmful_or_illegal_detected":
            predefined_response = translation_service.get_nested_translation("predefined_responses.harmful_or_illegal_detected.text", language, {})
        else:  # misuse_detected
            predefined_response = translation_service.get_nested_translation("predefined_responses.misuse_detected.text", language, {})
        
        if not predefined_response:
            predefined_response = "I can't help with that request."
        
        # Generate fake stream chunks to simulate normal streaming behavior
        return await _generate_fake_stream_for_harmful_content(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            predefined_response=predefined_response,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service
        )
    
    # Handle insufficient credits with a predefined message (no billing)
    if not preprocessing_result.can_proceed and preprocessing_result.rejection_reason == "insufficient_credits":
        logger.info(f"{log_prefix} Detected insufficient credits case. Generating simple fake stream.")
        message_text = preprocessing_result.error_message or "You don't have enough credits to run this request. Please add credits and try again."
        return await _generate_fake_stream_for_simple_message(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            message_text=message_text,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service
        )

    # Normal processing flow for other non-harmful content
    main_processing_stream: AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = handle_main_processing(
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
    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None
    redis_channel_name = f"chat_stream::{request_data.chat_id}"

    try:
        async for chunk in main_processing_stream:
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                continue
            if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
                logger.warning(f"{log_prefix} Task revoked during main processing stream. Processing partial response.")
                was_revoked_during_stream = True
                break

            final_response_chunks.append(chunk)
            stream_chunk_count += 1

            if cache_service:
                current_full_content = "".join(final_response_chunks)
                payload = _create_redis_payload(task_id, request_data, current_full_content, stream_chunk_count)
                
                # Log less frequently to reduce noise
                should_log = stream_chunk_count % 5 == 0 or len(current_full_content) % 1000 < len(chunk)
                log_message = f"Published chunk (seq: {stream_chunk_count}) to '{redis_channel_name}'. Length: {len(current_full_content)}" if should_log else ""
                
                await _publish_to_redis(
                    cache_service, redis_channel_name, payload, log_prefix, log_message
                )
            elif stream_chunk_count == 1:
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
    final_payload = _create_redis_payload(
        task_id, request_data, aggregated_response, stream_chunk_count + 1,
        is_final=True, interrupted_soft=was_soft_limited_during_stream,
        interrupted_revoke=was_revoked_during_stream
    )
    await _publish_to_redis(
        cache_service, redis_channel_name, final_payload, log_prefix,
        f"Published final marker (seq: {stream_chunk_count + 1}, interrupted_soft: {was_soft_limited_during_stream}, interrupted_revoke: {was_revoked_during_stream}) to '{redis_channel_name}'"
    )

    # Handle billing for normal processing
    if usage:
        await _handle_normal_billing(
            usage, preprocessing_result, request_data, task_id, log_prefix
        )

    # Persist final AI message to Directus
    if directus_service and encryption_service and aggregated_response:
        # Use actual category from preprocessing, fallback to general_knowledge
        category = preprocessing_result.category or "general_knowledge"
        if not preprocessing_result.category:
            logger.warning(f"{log_prefix} Preprocessing result category is None. Using 'general_knowledge'.")
            
        # Note: In zero-knowledge architecture, server does not persist AI responses
        # Client must encrypt AI response and send back to server for storage
        logger.info(f"{log_prefix} Skipping AI message persistence for zero-knowledge architecture.")
    elif not aggregated_response and not was_revoked_during_stream and not was_soft_limited_during_stream:
        logger.warning(f"{log_prefix} Aggregated AI response is empty (and not due to interruption). Skipping persistence.")
            
    return aggregated_response, was_revoked_during_stream, was_soft_limited_during_stream
