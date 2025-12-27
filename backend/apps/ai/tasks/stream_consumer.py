# backend/apps/ai/tasks/stream_consumer.py
# Handles the consumption of the main processing stream for AI tasks.

import logging
import time
import httpx
import asyncio
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
from backend.apps.ai.processing.url_validator import validate_urls_in_paragraph, extract_urls_from_markdown

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
    interrupted_revoke: bool = False,
    model_name: Optional[str] = None,
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

    if model_name:
        payload["model_name"] = model_name
    
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
    content_markdown: str,
    content_tiptap: Any,
    directus_service: DirectusService,
    cache_service: Optional[CacheService],
    encryption_service: EncryptionService,
    user_vault_key_id: str,
    task_id: str,
    log_prefix: str,
    model_name: Optional[str] = None
) -> None:
    """Update chat metadata and save assistant response to cache.
    
    Args:
        request_data: The AI skill request data
        category: The mate category for this response
        timestamp: Unix timestamp for message creation
        content_markdown: The response content as markdown (to be encrypted for cache)
        content_tiptap: The response content as TipTap JSON (for client event)
        directus_service: Directus service instance
        cache_service: Optional cache service instance
        encryption_service: Encryption service for server-side encryption
        user_vault_key_id: User's vault key ID for encryption
        task_id: The AI task ID (also the message ID for the assistant's response)
        log_prefix: Logging prefix for this task
        model_name: The AI model name used for the response
    """
    chat_metadata = await directus_service.chat.get_chat_metadata(request_data.chat_id)
    if not chat_metadata:
        logger.error(f"{log_prefix} Failed to fetch chat metadata for {request_data.chat_id}.")
        return
        
    current_messages_v = chat_metadata.get("messages_v", 0)
    new_messages_version = current_messages_v + 1
    
    # MESSAGES_V_TRACKING: Log the version change for AI response
    # This helps debug race conditions where messages_v gets incremented multiple times
    logger.info(
        f"{log_prefix} [MESSAGES_V_TRACKING] AI_RESPONSE: "
        f"chat_id={request_data.chat_id}, "
        f"current_directus_v={current_messages_v}, "
        f"new_directus_v={new_messages_version}, "
        f"source=stream_consumer._update_chat_metadata_and_save_response"
    )
    
    fields_to_update = {
        "messages_v": new_messages_version,
        "last_edited_overall_timestamp": timestamp,
        "last_message_timestamp": timestamp,
        "last_mate_category": category,
        "updated_at": int(time.time())
    }
    
    # CRITICAL: Always use optimistic locking or at least ensure we don't downgrade
    # Directus doesn't support "update if >" natively via simple API, but we can do our best
    # by using the value we just read.
    success = await directus_service.chat.update_chat_fields_in_directus(
        request_data.chat_id, fields_to_update
    )
    
    if not success:
        logger.error(f"{log_prefix} Failed to update chat metadata for {request_data.chat_id}.")
        return
        
    logger.info(f"{log_prefix} Updated chat metadata: version {new_messages_version} (was {current_messages_v}), timestamp {timestamp}.")
    
    # Save assistant response to cache and publish events
    # This ensures follow-up messages include assistant responses in the history
    if cache_service:
        await _save_to_cache_and_publish(
            request_data, task_id, category, timestamp,
            new_messages_version, cache_service, 
            encryption_service, user_vault_key_id,
            content_markdown, log_prefix,
            model_name=model_name
        )

async def _save_to_cache_and_publish(
    request_data: AskSkillRequest,
    task_id: str,
    category: str,
    timestamp: int,
    messages_version: int,
    cache_service: CacheService,
    encryption_service: EncryptionService,
    user_vault_key_id: str,
    content_markdown: str,
    log_prefix: str,
    model_name: Optional[str] = None
) -> None:
    """Save message to cache and publish persistence event.
    
    Args:
        request_data: The AI skill request data
        task_id: The AI task ID (also the message ID for the assistant's response)
        category: The mate category for this response
        timestamp: Unix timestamp for message creation
        messages_version: The new messages version number
        cache_service: Cache service instance
        encryption_service: Encryption service for server-side encryption
        user_vault_key_id: User's vault key ID for encryption
        content_markdown: The response content as markdown (to be encrypted for cache)
        log_prefix: Logging prefix for this task
        model_name: The AI model name used for the response
    """
    try:
        from backend.core.api.app.schemas.chat import MessageInCache
        
        # SERVER-SIDE ENCRYPTION: Encrypt AI response content with encryption_key_user_server (Vault)
        # This allows server to cache and access for AI while maintaining security
        try:
            encrypted_content_for_cache, _ = await encryption_service.encrypt_with_user_key(
                content_markdown, 
                user_vault_key_id
            )
            logger.debug(f"{log_prefix} Encrypted AI response content for cache using user vault key: {user_vault_key_id}")
        except Exception as e_encrypt:
            logger.error(f"{log_prefix} Failed to encrypt AI response content for cache: {e_encrypt}", exc_info=True)
            # Don't cache if encryption fails
            return
        
        # Store encrypted markdown content in cache (server-side encrypted with encryption_key_user_server)
        ai_message_for_cache = MessageInCache(
            id=task_id,
            chat_id=request_data.chat_id,
            role="assistant",
            category=category,
            sender_name=None,  # Assistant doesn't have a sender_name
            encrypted_content=encrypted_content_for_cache,  # Server-side encrypted content
            created_at=timestamp,
            status="synced",
            model_name=model_name  # Ensure model_name is in cache object if schema supports it
        )
        
        await cache_service.save_chat_message_and_update_versions(
            user_id=request_data.user_id,
            chat_id=request_data.chat_id,
            message_data=ai_message_for_cache
        )
        
        logger.info(f"{log_prefix} Saved assistant message to cache for chat {request_data.chat_id}.")
        
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
                "content": content_markdown,  # Send markdown content to client
                "created_at": timestamp,
                "status": "synced",
                "model_name": model_name  # CRITICAL: Send model_name to client for encryption/storage
            },
            "versions": {"messages_v": messages_version},
            "last_edited_overall_timestamp": timestamp
        }
        
        persisted_channel = f"ai_message_persisted::{request_data.user_id_hash}"
        logger.info(f"{log_prefix} Publishing 'ai_message_persisted' event with status: {persisted_event_payload['message']['status']}")
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
    encryption_service: Optional[EncryptionService] = None,
    user_vault_key_id: Optional[str] = None
) -> tuple[str, bool, bool]:
    """Generate fake stream for harmful content with predefined response."""
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _generate_fake_stream_for_harmful_content:"
    logger.info(f"{log_prefix} Generating fake stream for harmful content.")

    # For harmful content, we don't show a model name as it's a predefined response
    model_name = None
    
    # Check for revocation
    if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
        logger.warning(f"{log_prefix} Task was revoked before starting fake stream.")
        return "", True, False
    
    redis_channel = f"chat_stream::{request_data.chat_id}"
    
    # Publish content chunk
    content_payload = _create_redis_payload(task_id, request_data, predefined_response, 1, model_name=model_name)
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
    final_payload = _create_redis_payload(task_id, request_data, predefined_response, 2, is_final=True, model_name=model_name)
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
    
    # Save assistant response to cache for follow-up message context
    # Even harmful content responses should be cached so follow-ups have context
    # CRITICAL: This is non-blocking - if metadata update fails, the error message should still reach the user
    if directus_service and cache_service and predefined_response:
        category = "general_knowledge"  # Default category for harmful content responses
        timestamp = int(time.time())
        content_tiptap = predefined_response  # Send as markdown

        try:
            await _update_chat_metadata(
                request_data=request_data,
                category=category,
                timestamp=timestamp,
                content_markdown=predefined_response,
                content_tiptap=content_tiptap,
                directus_service=directus_service,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                task_id=task_id,
                log_prefix=log_prefix
            )
            logger.info(f"{log_prefix} Harmful content response saved to cache for future follow-up context.")
        except Exception as e:
            # IMPORTANT: Don't let metadata failures prevent error messages from reaching the user
            # The error message has already been published to Redis (lines 393-410) and should reach the client
            logger.error(f"{log_prefix} Failed to save harmful content response to cache/metadata (non-critical): {e}", exc_info=True)
            logger.warning(f"{log_prefix} Harmful content message was still published to client successfully via Redis stream")
    
    logger.info(f"{log_prefix} Fake stream generation completed. Response length: {len(predefined_response)}.")
    return predefined_response, False, False

async def _generate_fake_stream_for_simple_message(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_result: PreprocessingResult,
    message_text: str,
    cache_service: Optional[CacheService],
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
    user_vault_key_id: Optional[str] = None
) -> tuple[str, bool, bool]:
    """Generate a simple fake stream for non-processing cases (e.g., insufficient credits)."""
    log_prefix = f"[Task ID: {task_id}, ChatID: {request_data.chat_id}] _generate_fake_stream_for_simple_message:"
    logger.info(f"{log_prefix} Generating simple fake stream.")

    # For simple messages (errors/insufficient credits), we don't show a model name
    model_name = None
    
    # Check for revocation
    if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
        logger.warning(f"{log_prefix} Task was revoked before starting fake stream.")
        return "", True, False

    redis_channel = f"chat_stream::{request_data.chat_id}"

    # Publish content chunk
    content_payload = _create_redis_payload(task_id, request_data, message_text, 1, model_name=model_name)
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
    final_payload = _create_redis_payload(task_id, request_data, message_text, 2, is_final=True, model_name=model_name)
    await _publish_to_redis(
        cache_service, redis_channel, final_payload, log_prefix,
        f"Published final marker to '{redis_channel}'"
    )

    # Save assistant response to cache for follow-up message context
    # Even simple messages (like insufficient credits) should be cached
    # CRITICAL: This is non-blocking - if metadata update fails, the error message should still reach the user
    if directus_service and cache_service and message_text:
        category = "general_knowledge"  # Default category for simple messages
        timestamp = int(time.time())
        content_tiptap = message_text  # Send as markdown

        try:
            await _update_chat_metadata(
                request_data=request_data,
                category=category,
                timestamp=timestamp,
                content_markdown=message_text,
                content_tiptap=content_tiptap,
                directus_service=directus_service,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                task_id=task_id,
                log_prefix=log_prefix,
                model_name=None  # Model name not applicable for simple/error messages
            )
            logger.info(f"{log_prefix} Simple message response saved to cache for future follow-up context.")
        except Exception as e:
            # IMPORTANT: Don't let metadata failures prevent error messages from reaching the user
            # The error message has already been published to Redis (lines 481-498) and should reach the client
            logger.error(f"{log_prefix} Failed to save simple message to cache/metadata (non-critical): {e}", exc_info=True)
            logger.warning(f"{log_prefix} Error message was still published to client successfully via Redis stream")

    logger.info(f"{log_prefix} Simple fake stream generation completed. Response length: {len(message_text)}.")
    return message_text, False, False

async def _validate_paragraph_urls(
    paragraph: str,
    task_id: str,
    broken_urls_collector: List[Dict[str, Any]],
    log_prefix: str
) -> None:
    """
    Background task to validate URLs in a paragraph.
    Collects broken URLs in the provided list (thread-safe append).
    This runs asynchronously and doesn't block streaming.
    
    Args:
        paragraph: The paragraph text to validate
        task_id: Task ID for logging
        broken_urls_collector: List to collect broken URLs (will be appended to)
        log_prefix: Log prefix for consistent logging
    """
    try:
        # Validate URLs in this paragraph
        validation_results = await validate_urls_in_paragraph(paragraph, task_id)
        
        # Filter broken URLs (4xx errors, not temporary)
        broken_urls = [
            r for r in validation_results 
            if not r.get('is_valid') and not r.get('is_temporary')
        ]
        
        if broken_urls:
            logger.info(
                f"{log_prefix} Found {len(broken_urls)} broken URL(s) in paragraph"
            )
            # Append to collector (list append is thread-safe in Python)
            broken_urls_collector.extend(broken_urls)
        else:
            logger.debug(f"{log_prefix} All URLs valid in paragraph")
            
    except Exception as e:
        logger.error(
            f"{log_prefix} Error validating URLs in paragraph: {e}",
            exc_info=True
        )
        # Don't raise - this is a background task, errors shouldn't break the stream


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

    standardized_error_message = "The AI service encountered an error while processing your request. Please try again in a moment."

    # Local flags for interruption status
    was_revoked_during_stream = False
    was_soft_limited_during_stream = False
    stream_exception: Optional[BaseException] = None

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
            encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id
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
            encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id
        )

    # Handle LLM preprocessing failures (e.g., API errors, service unavailable)
    # When preprocessing fails, selected_main_llm_model_id is None, so we can't proceed with main processing
    if not preprocessing_result.can_proceed and preprocessing_result.rejection_reason == "internal_error_llm_preprocessing_failed":
        logger.info(f"{log_prefix} Detected LLM preprocessing failure. Generating error message stream.")
        # Use a user-friendly error message instead of exposing technical details
        # The technical error is logged but not shown to the user
        logger.warning(f"{log_prefix} Technical preprocessing error (not shown to user): {preprocessing_result.error_message}")
        message_text = "The AI service encountered an error while processing your request. Please try again in a moment."
        return await _generate_fake_stream_for_simple_message(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            message_text=message_text,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id
        )

    # Normal processing flow for other non-harmful content
    main_processing_stream: AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = handle_main_processing(
        task_id=task_id,
        request_data=request_data,
        preprocessing_results=preprocessing_result,
        base_instructions=base_instructions,
        directus_service=directus_service,
        encryption_service=encryption_service, # Pass EncryptionService
        user_vault_key_id=user_vault_key_id,
        all_mates_configs=all_mates_configs,
        discovered_apps_metadata=discovered_apps_metadata,
        secrets_manager=secrets_manager, # Pass SecretsManager
        cache_service=cache_service # Pass CacheService for skill status publishing
    )

    stream_chunk_count = 0
    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None
    redis_channel_name = f"chat_stream::{request_data.chat_id}"
    tool_calls_info: Optional[List[Dict[str, Any]]] = None  # Track tool calls for code block generation

    # Persist model identifier in stream payloads so clients can store it encrypted with the message.
    # Prefer the friendly model name from preprocessing, fallback to extracting from model_id, then safe default.
    stream_model_name: Optional[str] = None
    if preprocessing_result.selected_main_llm_model_name:
        stream_model_name = preprocessing_result.selected_main_llm_model_name
    else:
        # Fallback to extracting from model_id (for backward compatibility)
        selected_model_id = preprocessing_result.selected_main_llm_model_id or ""
        if isinstance(selected_model_id, str) and selected_model_id:
            stream_model_name = selected_model_id.split("/", 1)[1] if "/" in selected_model_id else selected_model_id
        else:
            # Final fallback: if no model name can be determined, don't show one
            stream_model_name = None
    
    # URL validation tracking: collect all validation tasks and broken URLs
    # These are used to validate URLs during streaming and correct the full response after completion
    url_validation_tasks: List[asyncio.Task] = []  # Track all background URL validation tasks
    all_broken_urls: List[Dict[str, Any]] = []  # Collect all broken URLs found across all paragraphs

    # Code block tracking: detect and convert code blocks to embeds in real-time
    in_code_block = False
    current_code_language = ""
    current_code_filename: Optional[str] = None
    current_code_content = ""
    current_code_embed_id: Optional[str] = None
    # New state: when LLM streams ``` and language separately, wait for next chunk
    waiting_for_code_language = False
    # pending_code_fence_chunk = ""  # Store the original ``` chunk to replay if needed (currently unused)

    try:
        async for chunk in main_processing_stream:
            # Check for tool calls info marker (special dict at end of stream)
            if isinstance(chunk, dict) and "__tool_calls_info__" in chunk:
                tool_calls_info = chunk["__tool_calls_info__"]
                logger.debug(f"{log_prefix} Received tool calls info: {len(tool_calls_info) if tool_calls_info else 0} tool call(s)")
                continue
            
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                continue
            
            # Check for revocation BEFORE processing the chunk
            if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
                logger.warning(f"{log_prefix} Task revoked during main processing stream. Including current chunk and finalizing partial response.")
                was_revoked_during_stream = True
                # Include the current chunk before breaking - don't discard it
                # This ensures we return the partial response and bill for all generated tokens
                if isinstance(chunk, str):
                    final_response_chunks.append(chunk)
                    stream_chunk_count += 1
                    
                    # Publish the final chunk with revocation marker IMMEDIATELY
                    if cache_service:
                        current_full_content = "".join(final_response_chunks)
                        payload = _create_redis_payload(
                            task_id, request_data, current_full_content, stream_chunk_count,
                            is_final=True, interrupted_revoke=True, model_name=stream_model_name
                        )
                        await _publish_to_redis(
                            cache_service, redis_channel_name, payload, log_prefix,
                            f"Published final chunk (seq: {stream_chunk_count}) with revocation marker to '{redis_channel_name}'. Length: {len(current_full_content)}"
                        )
                break

            # Process string chunks (text or code blocks) - publish IMMEDIATELY
            if isinstance(chunk, str):
                # CRITICAL: Sanitize error messages before adding to response
                # Replace any [ERROR: ...] messages with the translation key for generic error message
                # This ensures users never see technical error details
                if chunk.strip().startswith("[ERROR"):
                    logger.warning(f"{log_prefix} Detected error message in stream chunk: {chunk[:200]}... Replacing with generic error message.")
                    chunk = "chat.an_error_occured.text"
                
                # Code block detection and embed creation
                # Detect code block opening: ```language or ```language:filename
                # IMPORTANT: Skip JSON blocks that contain embed references - these are already processed embeds!
                should_process_as_code_block = False
                if not in_code_block and chunk.strip().startswith("```"):
                    # Extract language and filename from opening fence
                    # Format: ```language or ```language:filename
                    lines = chunk.split('\n')
                    fence_line = lines[0].strip()
                    fence_content = fence_line[3:].strip()  # Remove ```
                    
                    # SKIP: JSON blocks that are embed references (already processed by skills)
                    # These contain {"type": "...", "embed_id": "..."} or {"type": "...", "embed_ids": [...]}
                    # FIX: Handle indented code blocks by stripping whitespace before checking
                    is_embed_reference = False
                    if fence_content.lower() in ('json', 'json_embed'):
                        # Check if this is an embed reference JSON block
                        remaining_content = '\n'.join(lines[1:]) if len(lines) > 1 else ''
                        # FIX: Strip whitespace from content to handle indented JSON blocks
                        # This allows detection of embed references even when indented (e.g., "     ```json")
                        stripped_content = remaining_content.strip()
                        # Look for embed reference patterns in stripped content
                        is_embed_reference = (
                            '"embed_id"' in stripped_content or 
                            '"embed_ids"' in stripped_content or
                            'embed_id' in stripped_content
                        )
                        if is_embed_reference:
                            logger.debug(f"{log_prefix} Skipping JSON embed reference block (not a code block to convert, indented={remaining_content != stripped_content})")
                            # Don't process as code block - let it pass through as-is
                    
                    # Only process as code block if it's NOT an embed reference
                    if not is_embed_reference:
                        should_process_as_code_block = True
                
                # Process code block if detected and not an embed reference
                if should_process_as_code_block:
                    # Re-extract lines for processing (already extracted above but safer to re-extract)
                    lines = chunk.split('\n')
                    fence_line = lines[0].strip()
                    fence_content = fence_line[3:].strip()  # Remove ```
                    
                    # DEBUG: Log the raw chunk and extracted values for code block debugging
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Raw chunk (first 500 chars): {repr(chunk[:500])}")
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Lines count: {len(lines)}")
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] fence_line: {repr(fence_line)}")
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] fence_content (after removing ```): {repr(fence_content)}")
                    
                    if ':' in fence_content:
                        # Has filename: language:filename
                        parts = fence_content.split(':', 1)
                        current_code_language = parts[0].strip()
                        current_code_filename = parts[1].strip() if len(parts) > 1 else None
                    else:
                        # Just language or empty
                        current_code_language = fence_content
                        current_code_filename = None
                    
                    # FIX: If language/filename not in fence line, check first content line
                    # LLMs sometimes put "python:hello_world.py" in content instead of fence
                    # Track if we extracted from first line so we can remove it from code content
                    extracted_from_first_line = False
                    if (not current_code_language or not current_code_filename) and len(lines) > 1:
                        first_content_line = lines[1].strip()
                        # Check if first line matches language:filename pattern (e.g., "python:hello_world.py")
                        if ':' in first_content_line and not first_content_line.startswith('#'):
                            # Pattern: language:filename (e.g., "python:hello_world.py")
                            # Extract potential language:filename from first content line
                            import re
                            # Match pattern like "python:hello_world.py" or "javascript:index.js"
                            lang_file_pattern = r'^([a-zA-Z0-9_+\-#.]+):([^\s:]+)$'
                            match = re.match(lang_file_pattern, first_content_line)
                            if match:
                                potential_lang = match.group(1)
                                potential_filename = match.group(2)
                                # Only use if we don't already have language or filename
                                if not current_code_language:
                                    current_code_language = potential_lang
                                    extracted_from_first_line = True
                                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Extracted language from first content line: {repr(current_code_language)}")
                                if not current_code_filename:
                                    current_code_filename = potential_filename
                                    extracted_from_first_line = True
                                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Extracted filename from first content line: {repr(current_code_filename)}")
                    
                    # DEBUG: Log extracted language and filename
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Final extracted language: {repr(current_code_language)}")
                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Final extracted filename: {repr(current_code_filename)}")
                    
                    # Check if this chunk contains both opening and closing fence (complete code block)
                    # Look for closing fence in remaining lines (after the opening fence line)
                    found_closing = False
                    closing_line_idx = -1
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == '```':
                            found_closing = True
                            closing_line_idx = i
                            break
                    
                    if found_closing:
                        # Complete code block in single chunk - extract content and finalize immediately
                        # Extract content between opening and closing fences
                        content_lines = lines[1:closing_line_idx]  # Lines between fences
                        # FIX: Remove language:filename line from content if we extracted it
                        if extracted_from_first_line and content_lines:
                            first_line_stripped = content_lines[0].strip()
                            # Check if first line matches the pattern we extracted from
                            if ':' in first_line_stripped and not first_line_stripped.startswith('#'):
                                import re
                                lang_file_pattern = r'^([a-zA-Z0-9_+\-#.]+):([^\s:]+)$'
                                if re.match(lang_file_pattern, first_line_stripped):
                                    # Remove the first line as it was just metadata, not actual code
                                    content_lines = content_lines[1:]
                                    logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Removed language:filename line from code content")
                        code_content = '\n'.join(content_lines)
                        
                        # DEBUG: Log extracted code content
                        logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Complete code block detected, closing_line_idx: {closing_line_idx}")
                        logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] content_lines: {repr(content_lines[:5])}{'...' if len(content_lines) > 5 else ''}")
                        logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] code_content (first 200 chars): {repr(code_content[:200])}")
                        
                        # Create embed and finalize immediately
                        if directus_service and encryption_service and user_vault_key_id:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(cache_service, directus_service, encryption_service)
                                
                                # Create code embed placeholder
                                embed_data = await embed_service.create_code_embed_placeholder(
                                    language=current_code_language,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    filename=current_code_filename,
                                    log_prefix=log_prefix
                                )
                                
                                if embed_data:
                                    current_code_embed_id = embed_data["embed_id"]
                                    
                                    # Update with full content and finalize
                                    await embed_service.update_code_embed_content(
                                        embed_id=current_code_embed_id,
                                        code_content=code_content,
                                        chat_id=request_data.chat_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        status="finished",
                                        log_prefix=log_prefix
                                    )
                                    
                                    # Replace code block with embed reference in chunk
                                    embed_reference_code = f"```json\n{embed_data['embed_reference']}\n```\n\n"
                                    chunk = embed_reference_code
                                    logger.info(f"{log_prefix} Created and finalized code embed {current_code_embed_id} for complete code block")
                                    
                                    # Reset state
                                    in_code_block = False
                                    current_code_language = ""
                                    current_code_filename = None
                                    current_code_content = ""
                                    current_code_embed_id = None
                            except Exception as e:
                                logger.error(f"{log_prefix} Error creating code embed for complete block: {e}", exc_info=True)
                                # Continue with original chunk if embed creation fails
                    else:
                        # Opening fence but no closing fence in this chunk - start code block tracking
                        in_code_block = True
                        current_code_content = ""
                        current_code_embed_id = None
                        
                        # CRITICAL FIX: If fence has no language (e.g., just ```), wait for next chunk
                        # LLMs often stream ``` and language as separate tokens
                        if not current_code_language and len(lines) == 1:
                            # Bare fence with no content - language might come in next chunk
                            waiting_for_code_language = True
                            # Save original chunk (currently unused but left for future potential use)
                            # pending_code_fence_chunk = chunk
                            chunk = ""  # Don't emit anything yet
                            logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Detected bare fence '```', waiting for potential language in next chunk")
                            continue  # Skip the rest of processing, wait for next chunk
                        
                        # Extract any content after opening fence in this chunk
                        if len(lines) > 1:
                            # There's content after the opening fence line
                            content_lines_after_fence = lines[1:]
                            # FIX: Remove language:filename line from content if we extracted it
                            if extracted_from_first_line and content_lines_after_fence:
                                first_line_stripped = content_lines_after_fence[0].strip()
                                # Check if first line matches the pattern we extracted from
                                if ':' in first_line_stripped and not first_line_stripped.startswith('#'):
                                    import re
                                    lang_file_pattern = r'^([a-zA-Z0-9_+\-#.]+):([^\s:]+)$'
                                    if re.match(lang_file_pattern, first_line_stripped):
                                        # Remove the first line as it was just metadata, not actual code
                                        content_lines_after_fence = content_lines_after_fence[1:]
                                        logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Removed language:filename line from code content (multi-chunk)")
                            current_code_content = '\n'.join(content_lines_after_fence)
                        
                        # Create code embed placeholder
                        if directus_service and encryption_service and user_vault_key_id:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(cache_service, directus_service, encryption_service)
                                
                                embed_data = await embed_service.create_code_embed_placeholder(
                                    language=current_code_language,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    filename=current_code_filename,
                                    log_prefix=log_prefix
                                )
                                
                                if embed_data:
                                    current_code_embed_id = embed_data["embed_id"]
                                    
                                    # If there's content after the opening fence, update embed immediately
                                    if current_code_content:
                                        await embed_service.update_code_embed_content(
                                            embed_id=current_code_embed_id,
                                            code_content=current_code_content,
                                            chat_id=request_data.chat_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            status="processing",
                                            log_prefix=log_prefix
                                        )
                                    
                                    # Replace opening fence with embed reference
                                    embed_reference_code = f"```json\n{embed_data['embed_reference']}\n```\n\n"
                                    chunk = embed_reference_code
                                    logger.info(f"{log_prefix} Created code embed placeholder {current_code_embed_id} (language: {current_code_language or 'none'})")
                            except Exception as e:
                                logger.error(f"{log_prefix} Error creating code embed placeholder: {e}", exc_info=True)
                                # Continue with original chunk if embed creation fails
                
                # Handle code block content accumulation and closing
                elif in_code_block:
                    # CRITICAL FIX: Check if we're waiting for language after a bare ``` fence
                    if waiting_for_code_language:
                        waiting_for_code_language = False  # Reset flag
                        
                        # Check if this chunk starts with what looks like a language identifier
                        # Language identifiers: single word, alphanumeric with optional -, _, +, #
                        first_line = chunk.split('\n')[0].strip() if chunk else ""
                        remaining_content = '\n'.join(chunk.split('\n')[1:]) if '\n' in chunk else ""
                        
                        # Language pattern: single word like "python", "javascript", "c++", "c#", etc.
                        import re
                        lang_pattern = r'^[a-zA-Z][a-zA-Z0-9_+#-]*$'
                        
                        if first_line and re.match(lang_pattern, first_line) and len(first_line) <= 20:
                            # This looks like a language identifier
                            if ':' in first_line:
                                # Has filename: language:filename
                                parts = first_line.split(':', 1)
                                current_code_language = parts[0].strip()
                                current_code_filename = parts[1].strip() if len(parts) > 1 else None
                            else:
                                current_code_language = first_line
                            
                            # Any remaining lines after the language are code content
                            current_code_content = remaining_content
                            logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] Extracted language from next chunk: {repr(current_code_language)}")
                        else:
                            # Not a language - treat entire chunk as code content
                            current_code_content = chunk
                            logger.info(f"{log_prefix} [CODE_BLOCK_DEBUG] No language found in chunk, treating as code: {repr(first_line[:50])}")
                        
                        # Now create the embed placeholder with the extracted (or empty) language
                        if directus_service and encryption_service and user_vault_key_id:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(cache_service, directus_service, encryption_service)
                                
                                embed_data = await embed_service.create_code_embed_placeholder(
                                    language=current_code_language,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    filename=current_code_filename,
                                    log_prefix=log_prefix
                                )
                                
                                if embed_data:
                                    current_code_embed_id = embed_data["embed_id"]
                                    
                                    # If there's content, update embed immediately
                                    if current_code_content:
                                        await embed_service.update_code_embed_content(
                                            embed_id=current_code_embed_id,
                                            code_content=current_code_content,
                                            chat_id=request_data.chat_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            status="processing",
                                            log_prefix=log_prefix
                                        )
                                    
                                    # Emit the embed reference now
                                    embed_reference_code = f"```json\n{embed_data['embed_reference']}\n```\n\n"
                                    chunk = embed_reference_code
                                    logger.info(f"{log_prefix} Created code embed placeholder {current_code_embed_id} (language: {current_code_language or 'none'}) after waiting for language")
                                else:
                                    chunk = ""  # Failed to create embed
                            except Exception as e:
                                logger.error(f"{log_prefix} Error creating code embed placeholder after waiting for language: {e}", exc_info=True)
                                chunk = ""
                        else:
                            chunk = ""  # No services available
                    # Check if this chunk contains closing fence
                    elif '```' in chunk:
                        # Extract content before closing fence
                        closing_fence_idx = chunk.find('```')
                        code_chunk_content = chunk[:closing_fence_idx]
                        current_code_content += code_chunk_content
                        
                        # Finalize code embed
                        if current_code_embed_id and directus_service and encryption_service and user_vault_key_id:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(cache_service, directus_service, encryption_service)
                                
                                await embed_service.update_code_embed_content(
                                    embed_id=current_code_embed_id,
                                    code_content=current_code_content,
                                    chat_id=request_data.chat_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    status="finished",
                                    log_prefix=log_prefix
                                )
                                
                                logger.info(f"{log_prefix} Finalized code embed {current_code_embed_id} with {len(current_code_content)} chars")
                            except Exception as e:
                                logger.error(f"{log_prefix} Error finalizing code embed: {e}", exc_info=True)
                        
                        # Reset state
                        in_code_block = False
                        current_code_language = ""
                        current_code_filename = None
                        current_code_content = ""
                        current_code_embed_id = None
                        
                        # Don't include closing fence in response (already replaced with embed reference)
                        chunk = ""  # Empty chunk - embed reference was already sent
                    else:
                        # Accumulate code content
                        current_code_content += chunk
                        
                        # Update embed on every newline (per-line streaming for better UX)
                        # This provides smooth line-by-line updates instead of arbitrary chunk-based updates
                        if current_code_embed_id and '\n' in chunk and directus_service and encryption_service and user_vault_key_id:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(cache_service, directus_service, encryption_service)
                                
                                await embed_service.update_code_embed_content(
                                    embed_id=current_code_embed_id,
                                    code_content=current_code_content,
                                    chat_id=request_data.chat_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    status="processing",
                                    log_prefix=log_prefix
                                )
                                
                                logger.debug(f"{log_prefix} Updated code embed {current_code_embed_id} (per-line update, {len(current_code_content)} chars, {current_code_content.count(chr(10))} lines)")
                            except Exception as e:
                                logger.error(f"{log_prefix} Error updating code embed: {e}", exc_info=True)
                        
                        # Don't include code content in response (embed reference was already sent)
                        chunk = ""  # Empty chunk - code content goes to embed, not message
                
                # Only add non-empty chunks to final response
                if chunk:
                    final_response_chunks.append(chunk)
                    stream_chunk_count += 1

                # CRITICAL: Publish chunk IMMEDIATELY without buffering
                # This ensures paragraph-by-paragraph streaming and embed placeholders show up right away
                if cache_service:
                    current_full_content = "".join(final_response_chunks)
                    payload = _create_redis_payload(
                        task_id, request_data, current_full_content, stream_chunk_count, model_name=stream_model_name
                    )
                    
                    # CRITICAL: Always log chunk publishing for debugging (but less verbose)
                    # This helps diagnose if chunks are being published correctly
                    is_code_block = chunk.strip().startswith("```")
                    chunk_preview = chunk[:50].replace("\n", "\\n") if len(chunk) > 50 else chunk.replace("\n", "\\n")
                    log_message = (
                        f"Published chunk (seq: {stream_chunk_count}, type={'code_block' if is_code_block else 'text'}, "
                        f"preview='{chunk_preview}...', total_length={len(current_full_content)}) to '{redis_channel_name}'"
                    )
                    
                    # CRITICAL: Use await to ensure publish completes before continuing
                    # This ensures chunks are sent in order and immediately
                    await _publish_to_redis(
                        cache_service, redis_channel_name, payload, log_prefix, log_message
                    )
                    
                    # URL Validation: Check if this paragraph contains URLs and validate them in background
                    # Skip code blocks (they might contain URLs that are just examples)
                    if not is_code_block:
                        # Check if chunk contains markdown links
                        urls_in_chunk = await extract_urls_from_markdown(chunk)
                        if urls_in_chunk:
                            # Start background task to validate URLs in this paragraph
                            # This runs asynchronously and doesn't block streaming
                            # Broken URLs will be collected and processed after streaming completes
                            validation_task = asyncio.create_task(
                                _validate_paragraph_urls(
                                    paragraph=chunk,
                                    task_id=task_id,
                                    broken_urls_collector=all_broken_urls,
                                    log_prefix=log_prefix
                                )
                            )
                            url_validation_tasks.append(validation_task)
                elif stream_chunk_count == 1:
                    logger.warning(f"{log_prefix} Cache service not available. Skipping Redis publish for chunks.")
            else:
                # Non-string chunk (shouldn't happen, but handle gracefully)
                logger.warning(f"{log_prefix} Received unexpected non-string chunk type: {type(chunk)}")
    except SoftTimeLimitExceeded:
        logger.warning(f"{log_prefix} Soft time limit exceeded during main processing stream. Processing partial response.")
        was_soft_limited_during_stream = True
    except Exception as e:
        logger.error(f"{log_prefix} Exception during main processing stream consumption: {e}", exc_info=True)
        stream_exception = e
        # Check if revoked after an unexpected error
        if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
            was_revoked_during_stream = True
    
    # Finalize any open code block if stream was interrupted
    if in_code_block and current_code_embed_id and directus_service and encryption_service and user_vault_key_id:
        try:
            from backend.core.api.app.services.embed_service import EmbedService
            embed_service = EmbedService(cache_service, directus_service, encryption_service)
            
            # Finalize with partial content (interrupted)
            await embed_service.update_code_embed_content(
                embed_id=current_code_embed_id,
                code_content=current_code_content,
                chat_id=request_data.chat_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=user_vault_key_id,
                status="finished",  # Mark as finished even if interrupted
                log_prefix=log_prefix
            )
            
            logger.info(f"{log_prefix} Finalized interrupted code embed {current_code_embed_id} with {len(current_code_content)} chars")
        except Exception as e:
            logger.error(f"{log_prefix} Error finalizing interrupted code embed: {e}", exc_info=True)

    aggregated_response = "".join(final_response_chunks)

    # Ensure we never complete with an empty assistant message on server-side failures.
    # This avoids clients sending an "ai_response_completed" payload without encrypted_content,
    # and ensures the user always sees a retryable error message when all providers fail.
    if (
        not aggregated_response
        and not was_revoked_during_stream
        and not was_soft_limited_during_stream
    ):
        if stream_exception:
            logger.error(
                f"{log_prefix} Stream failed before producing any content. "
                f"Returning standardized user-facing error message. Technical error: {stream_exception!r}"
            )
        else:
            logger.error(
                f"{log_prefix} Stream completed with empty content (no interruption). "
                "Returning standardized user-facing error message."
            )
        aggregated_response = standardized_error_message
        final_response_chunks = [aggregated_response]
        if stream_chunk_count == 0:
            # Mirror fake-stream behavior: one content chunk + one final marker.
            # Publish a synthetic first chunk so clients can render something immediately.
            if cache_service:
                synthetic_payload = _create_redis_payload(
                    task_id, request_data, aggregated_response, 1, is_final=False, model_name=stream_model_name
                )
                await _publish_to_redis(
                    cache_service,
                    redis_channel_name,
                    synthetic_payload,
                    log_prefix,
                    f"Published synthetic error chunk (seq: 1) to '{redis_channel_name}'",
                )
            stream_chunk_count = 1
    
    # IMPROVED LOGGING: Log the full streamed assistant message for debugging
    # This helps diagnose parsing issues, embed reference problems, and code block extraction
    logger.info(
        f"{log_prefix} [FULL_STREAMED_MESSAGE] "
        f"Total chunks: {stream_chunk_count}, "
        f"Total length: {len(aggregated_response)} chars, "
        f"Message preview (first 500 chars):\n{repr(aggregated_response[:500])}"
    )
    # Log full message in chunks if it's very long (to avoid log truncation)
    if len(aggregated_response) > 2000:
        # Split into chunks of 2000 chars for logging
        chunk_size = 2000
        for i in range(0, len(aggregated_response), chunk_size):
            chunk_num = (i // chunk_size) + 1
            total_chunks = (len(aggregated_response) + chunk_size - 1) // chunk_size
            chunk_content = aggregated_response[i:i + chunk_size]
            logger.info(
                f"{log_prefix} [FULL_STREAMED_MESSAGE] "
                f"Chunk {chunk_num}/{total_chunks} (chars {i}-{min(i + chunk_size, len(aggregated_response))}):\n{repr(chunk_content)}"
            )
    else:
        # Log full message if it's short enough
        logger.info(
            f"{log_prefix} [FULL_STREAMED_MESSAGE] Complete message:\n{repr(aggregated_response)}"
        )
    
    # Wait for all URL validation tasks to complete (non-blocking during streaming, but wait now)
    if url_validation_tasks:
        logger.info(
            f"{log_prefix} Waiting for {len(url_validation_tasks)} URL validation task(s) to complete..."
        )
        try:
            # Wait for all validation tasks to complete
            await asyncio.gather(*url_validation_tasks, return_exceptions=True)
            logger.info(
                f"{log_prefix} All URL validation tasks completed. Found {len(all_broken_urls)} broken URL(s) total."
            )
        except Exception as e:
            logger.error(
                f"{log_prefix} Error waiting for URL validation tasks: {e}",
                exc_info=True
            )
        
        # If broken URLs found, correct the entire response
        if all_broken_urls:
            logger.info(
                f"{log_prefix} Correcting full response with {len(all_broken_urls)} broken URL(s)..."
            )
            
            # Get the model ID used for main processing (from preprocessing result)
            main_model_id = preprocessing_result.selected_main_llm_model_id or "gpt-4o-mini"
            
            # Extract the last user message from message_history
            # AskSkillRequest doesn't have message_content, it has message_history (list of AIHistoryMessage)
            last_user_message = ""
            if request_data.message_history and len(request_data.message_history) > 0:
                # Find the last user message in history
                # Note: message_history contains AIHistoryMessage Pydantic models, not dicts
                for msg in reversed(request_data.message_history):
                    if msg.role == "user":
                        last_user_message = msg.content
                        break
            
            # Import here to avoid circular imports
            from backend.apps.ai.processing.url_corrector import correct_full_response_with_broken_urls
            
            corrected_response = await correct_full_response_with_broken_urls(
                original_response=aggregated_response,
                broken_urls=all_broken_urls,
                user_message=last_user_message,
                task_id=task_id,
                model_id=main_model_id,  # Use same model as main processing
                secrets_manager=secrets_manager
            )
            
            if corrected_response and corrected_response != aggregated_response:
                logger.info(
                    f"{log_prefix} Successfully corrected response. "
                    f"Original length: {len(aggregated_response)}, "
                    f"Corrected length: {len(corrected_response)}"
                )
                
                # Replace the aggregated response with corrected version
                aggregated_response = corrected_response
                
                # Update final_response_chunks to reflect correction (for cache saving)
                # Rebuild chunks from corrected response (simple approach: single chunk)
                final_response_chunks = [corrected_response]
                
                # Publish corrected response to client (user will see text update)
                correction_payload = _create_redis_payload(
                    task_id, request_data, corrected_response, stream_chunk_count + 2,
                    is_final=False,  # Not final, just a correction update
                    model_name=stream_model_name
                )
                await _publish_to_redis(
                    cache_service, redis_channel_name, correction_payload, log_prefix,
                    f"Published corrected response (seq: {stream_chunk_count + 2}) "
                    f"with {len(all_broken_urls)} broken URL(s) fixed. Length: {len(corrected_response)}"
                )
                
                logger.info(f"{log_prefix} Published corrected response to client")
            else:
                logger.warning(
                    f"{log_prefix} Correction failed or returned same content. "
                    f"Using original response."
                )
    
    # NOTE: Embed references are now streamed as chunks during skill execution
    # They appear in final_response_chunks and are already part of aggregated_response
    # No need to prepend - they're already in the stream at the correct position
    # This allows flexible placement by the LLM (though currently they appear after skill execution)
    if tool_calls_info and len(tool_calls_info) > 0:
        embed_count = sum(1 for tc in tool_calls_info if tc.get("embed_reference"))
        if embed_count > 0:
            logger.info(
                f"{log_prefix} {embed_count} embed reference(s) were streamed as chunks during skill execution"
            )
    
    # Prepend code block with tool calls info if any tool calls were made
    # This allows the frontend to display skill input/output and enables follow-up questions
    # NOTE: With the new Embeds Architecture, we NO LONGER prepend the TOON code block.
    # Tool results are displayed via Embeds (streamed as chunks during execution).
    # Prepending raw TOON data would cause it to be rendered as text/code block at the start of the message,
    # which is redundant and confusing for the user.
    # We still track tool_calls_info for logging and potential future use, but we don't inject it into the message content.
    if tool_calls_info and len(tool_calls_info) > 0:
        logger.info(
            f"{log_prefix} Skipped prepending TOON code block (Embeds Architecture active). "
            f"Tool results are handled via Embeds."
        )
    
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
        interrupted_revoke=was_revoked_during_stream,
        model_name=stream_model_name
    )
    await _publish_to_redis(
        cache_service, redis_channel_name, final_payload, log_prefix,
        f"Published final marker (seq: {stream_chunk_count + 1}, interrupted_soft: {was_soft_limited_during_stream}, interrupted_revoke: {was_revoked_during_stream}) to '{redis_channel_name}'"
    )

    # Handle billing for normal processing
    # When revoked or soft-limited, we still bill for all tokens generated (usage metadata contains all generated tokens)
    # This ensures we charge for the compute that was performed, even if the response was cut short by the user
    # However, we should NOT bill if the response contains server error messages (all providers failed)
    # User interruptions (revoked/soft limit) should still be billed as they consumed resources
    
    # Determine if this is a server error (all providers failed) vs user interruption
    # Check for both old "[ERROR:" format and new standardized error message format
    is_old_format_error = aggregated_response.strip().startswith("[ERROR:")
    is_new_format_error = aggregated_response.strip() == standardized_error_message
    is_error = is_old_format_error or is_new_format_error
    
    is_server_error = (
        is_error and 
        (is_old_format_error and ("All servers failed" in aggregated_response or "All provider" in aggregated_response or "HTTP error" in aggregated_response)) or
        is_new_format_error  # New standardized format always indicates server error
    )
    
    # Bill if:
    # 1. We have usage metadata AND
    # 2. Either the response is successful OR it was interrupted by user (revoked/soft limit) AND
    # 3. It's NOT a server error (all providers failed)
    should_bill = (
        usage is not None and 
        (not is_error or was_revoked_during_stream or was_soft_limited_during_stream) and
        not is_server_error
    )
    
    if should_bill:
        await _handle_normal_billing(
            usage, preprocessing_result, request_data, task_id, log_prefix
        )
    elif usage and is_server_error:
        logger.warning(f"{log_prefix} Skipping billing because all providers failed (server error). Usage metadata was present but will not be billed.")
    elif usage and is_error and not (was_revoked_during_stream or was_soft_limited_during_stream):
        logger.warning(f"{log_prefix} Skipping billing because response contains error messages and was not user-interrupted.")
    elif not usage:
        logger.info(f"{log_prefix} No usage metadata available. Skipping billing.")

    # Save assistant response to cache for follow-up message context
    # This is CRITICAL for the architecture where last 3 chats are cached in memory
    # Even partial responses (due to revocation/soft limit) should be saved for context
    # CRITICAL: Always save to AI cache, even if response is empty or interrupted
    # This ensures message history is complete for follow-up requests
    if directus_service and cache_service and encryption_service and user_vault_key_id:
        # Use actual category from preprocessing, fallback to general_knowledge
        category = preprocessing_result.category or "general_knowledge"
        if not preprocessing_result.category:
            logger.warning(f"{log_prefix} Preprocessing result category is None. Using 'general_knowledge'.")
        
        timestamp = int(time.time())
        
        # Convert markdown response to TipTap JSON for client event
        # For now, we'll send markdown as-is since the client handles markdown parsing
        # In future, we could convert to TipTap JSON here if needed
        content_tiptap = aggregated_response  # Send as markdown for now
        
        # CRITICAL: Save to cache even if response is empty or partial
        # This ensures the message exists in history (even if empty) for proper context
        # Empty responses can occur due to errors, interruptions, or harmful content filtering
        try:
            await _update_chat_metadata(
                request_data=request_data,
                category=category,
                timestamp=timestamp,
                content_markdown=aggregated_response,  # Store markdown in cache (may be empty)
                content_tiptap=content_tiptap,  # Send to client (markdown for now)
                directus_service=directus_service,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                task_id=task_id,
                log_prefix=log_prefix,
                model_name=stream_model_name
            )
            logger.info(
                f"{log_prefix} Assistant response saved to AI cache for future follow-up context. "
                f"Response length: {len(aggregated_response)}, "
                f"Interrupted: revoked={was_revoked_during_stream}, soft_limit={was_soft_limited_during_stream}"
            )
        except Exception as e_save:
            logger.error(
                f"{log_prefix} CRITICAL: Failed to save assistant response to AI cache: {e_save}. "
                f"Follow-up requests will NOT have this message in context!",
                exc_info=True
            )
    elif not aggregated_response and not was_revoked_during_stream and not was_soft_limited_during_stream:
        logger.warning(f"{log_prefix} Aggregated AI response is empty (and not due to interruption). Attempting to save anyway for context.")
        # Try to save even empty response if services are available
        if directus_service and cache_service and encryption_service and user_vault_key_id:
            try:
                category = preprocessing_result.category or "general_knowledge"
                timestamp = int(time.time())
                await _update_chat_metadata(
                    request_data=request_data,
                    category=category,
                    timestamp=timestamp,
                    content_markdown="",  # Empty response
                    content_tiptap="",
                    directus_service=directus_service,
                    cache_service=cache_service,
                    encryption_service=encryption_service,
                    user_vault_key_id=user_vault_key_id,
                    task_id=task_id,
                    log_prefix=log_prefix
                )
                logger.info(f"{log_prefix} Saved empty assistant response to AI cache for context.")
            except Exception as e_empty_save:
                logger.error(f"{log_prefix} Failed to save empty assistant response: {e_empty_save}", exc_info=True)
    elif not cache_service:
        logger.error(f"{log_prefix} CRITICAL: Cache service not available. Assistant response NOT saved to AI cache - follow-ups won't have context!")
    elif not encryption_service:
        logger.error(f"{log_prefix} CRITICAL: Encryption service not available. Assistant response NOT saved to AI cache - follow-ups won't have context!")
    elif not user_vault_key_id:
        logger.error(f"{log_prefix} CRITICAL: User vault key ID not available. Assistant response NOT saved to AI cache - follow-ups won't have context!")
            
    return aggregated_response, was_revoked_during_stream, was_soft_limited_during_stream
