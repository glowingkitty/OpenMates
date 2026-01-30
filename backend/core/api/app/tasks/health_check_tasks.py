# backend/core/api/app/tasks/health_check_tasks.py
# Periodic health check tasks for LLM providers and app services.
# These tasks run via Celery Beat to monitor provider and app availability.

import logging
import asyncio
import json
import time
import os
from typing import Dict, Any, Optional, List
import httpx

from celery import shared_task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager
from backend.apps.ai.utils.llm_utils import (
    PROVIDER_CLIENT_REGISTRY,
    _get_provider_client,
    resolve_default_server_from_provider_config
)

logger = logging.getLogger(__name__)

# Flag to track if DirectusService is available for health event recording
# This is set to True once the service is properly initialized during startup
_directus_service_available = False


async def _record_health_event_if_changed(
    service_type: str,
    service_id: str,
    new_status: str,
    previous_status: Optional[str],
    previous_check_timestamp: Optional[int],
    error_message: Optional[str] = None,
    response_time_ms: Optional[float] = None
) -> None:
    """
    Record a health event to the database if the status has changed.
    
    This function only records events when there's an actual status change
    (e.g., healthy → unhealthy or unhealthy → healthy). This keeps the 
    event log efficient and focused on meaningful incidents.
    
    Args:
        service_type: Type of service ('provider', 'app', 'external')
        service_id: Service identifier (e.g., 'openrouter', 'ai', 'stripe')
        new_status: Current status ('healthy', 'unhealthy', 'degraded')
        previous_status: Previous status from cache (can be None for first check)
        previous_check_timestamp: Unix timestamp of previous status change (for duration calculation)
        error_message: Sanitized error message if new_status is unhealthy
        response_time_ms: Response time in milliseconds
    """
    # Only record if status changed (or if this is the first check and status is unhealthy)
    if previous_status == new_status:
        return
    
    # Skip recording "initial → healthy" events (not interesting)
    # But record "initial → unhealthy" as that's a problem we want to track
    if previous_status is None and new_status == "healthy":
        logger.debug(f"[HEALTH_EVENT] Skipping initial healthy status for {service_type}/{service_id}")
        return
    
    # Calculate duration of previous status if we have timestamps
    duration_seconds = None
    if previous_check_timestamp:
        duration_seconds = int(time.time()) - previous_check_timestamp
    
    try:
        # Import and use DirectusService for recording events
        # We do this lazily to avoid circular imports and startup issues
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        
        directus = DirectusService(cache_service=CacheService())
        
        try:
            await directus.health_event.record_health_event(
                service_type=service_type,
                service_id=service_id,
                previous_status=previous_status,
                new_status=new_status,
                error_message=error_message,
                response_time_ms=response_time_ms,
                duration_seconds=duration_seconds
            )
        finally:
            await directus.close()
            
    except Exception as e:
        # Log but don't fail the health check if event recording fails
        logger.warning(
            f"[HEALTH_EVENT] Failed to record status change for {service_type}/{service_id}: {e}"
        )


# Cache key prefix for health status
HEALTH_CHECK_CACHE_KEY_PREFIX = "health_check:provider:"
HEALTH_CHECK_APP_CACHE_KEY_PREFIX = "health_check:app:"
HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX = "health_check:external:"
# Cache TTL: 10 minutes (longer than check intervals to ensure availability)
HEALTH_CHECK_CACHE_TTL = 600

# Health check intervals (in seconds)
HEALTH_CHECK_INTERVAL_WITH_ENDPOINT = 60  # 1 minute for providers with /health endpoint
HEALTH_CHECK_INTERVAL_WITHOUT_ENDPOINT = 300  # 5 minutes for providers without /health endpoint


def _is_credential_error(error_message: Optional[str]) -> bool:
    """
    Check if an error message indicates a credential/authentication issue.
    
    Args:
        error_message: The error message to check
    
    Returns:
        True if this appears to be a credential/authentication error, False otherwise
    """
    if not error_message:
        return False
    
    error_lower = error_message.lower()
    
    # AWS credential error indicators
    credential_indicators = [
        'unrecognizedclientexception',
        'invalidclienttokenid',
        'invalidaccesskeyid',
        'signaturedoesnotmatch',
        'invalid security token',
        'security token included in the request is invalid',
        'authentication/credential error',
        'credentials are invalid',
        'credentials are expired',
        'credentials have been deactivated',
        'invalid credentials',
        'access denied',
        'invalidsecurity'
    ]
    
    return any(indicator in error_lower for indicator in credential_indicators)


def _sanitize_error_message(error_message: Optional[str]) -> Optional[str]:
    """
    Sanitize error messages for public health endpoint.
    Extracts only error codes (e.g., "500", "400") or simple error types (e.g., "timeout").
    Removes detailed error messages, HTML content, and other sensitive information.
    
    Args:
        error_message: Raw error message
    
    Returns:
        Sanitized error message (e.g., "500", "timeout", "400") or None
    """
    if not error_message:
        return None
    
    error_lower = error_message.lower()
    
    # Check for credential errors first
    if _is_credential_error(error_message):
        return "credential_error"
    
    # Check for timeout
    if "timeout" in error_lower:
        return "timeout"
    
    # Extract HTTP status codes (e.g., "500", "400", "404", "503")
    import re
    http_code_match = re.search(r'\b(\d{3})\b', error_message)
    if http_code_match:
        code = http_code_match.group(1)
        # Only return valid HTTP error codes (4xx, 5xx)
        if code.startswith(('4', '5')):
            return code
    
    # Check for common error patterns
    if "connection" in error_lower or "connection error" in error_lower:
        return "connection_error"
    
    if "not found" in error_lower or "404" in error_lower:
        return "404"
    
    # For unknown errors, return a generic message
    # But first check if it's a known pattern
    if "no available models" in error_lower:
        return "no_models"
    
    # Default: return None to hide unknown error details
    return None


def _get_cheapest_model_for_server(server_id: str) -> Optional[str]:
    """
    Get the cheapest available model for a server to use in health check test requests.
    
    Scans all provider configs to find models that use this server, then selects the cheapest one.
    For Anthropic, prefers Haiku models over Sonnet for health checks.
    
    Args:
        server_id: The server ID (e.g., "cerebras", "openrouter", "groq", "mistral", "anthropic")
    
    Returns:
        Model ID string in format "provider/model-id" (e.g., "alibaba/qwen3-235b-a22b-2507") or None if no models found
    """
    try:
        all_provider_configs = config_manager.get_provider_configs()
        if not all_provider_configs:
            logger.warning(f"No provider configs loaded. Cannot find model for server '{server_id}'")
            return None
        
        # Find all models that use this server
        candidate_models = []  # List of (provider_id, model_id, model_config, cost)
        
        for provider_id, provider_config in all_provider_configs.items():
            models = provider_config.get("models", [])
            for model in models:
                if not isinstance(model, dict):
                    continue
                
                # Check if this model has the server in its servers list
                servers = model.get("servers", [])
                has_server = False
                for server in servers:
                    if isinstance(server, dict) and server.get("id") == server_id:
                        has_server = True
                        break
                
                if has_server:
                    model_id = model.get("id")
                    if model_id:
                        # Get input cost per million tokens
                        costs = model.get("costs", {})
                        input_cost = costs.get("input_per_million_token", {}).get("price")
                        candidate_models.append((provider_id, model_id, model, input_cost))
        
        if not candidate_models:
            logger.warning(f"No models found that use server '{server_id}'")
            return None
        
        # For Anthropic, prefer Haiku models for health checks
        if server_id == "anthropic":
            haiku_models = [
                (provider_id, model_id, model_config, input_cost)
                for provider_id, model_id, model_config, input_cost in candidate_models
                if "haiku" in model_id.lower()
            ]
            if haiku_models:
                # Use cheapest Haiku model
                cheapest_haiku = None
                cheapest_haiku_cost = float('inf')
                for provider_id, model_id, model_config, input_cost in haiku_models:
                    if input_cost is not None and input_cost < cheapest_haiku_cost:
                        cheapest_haiku_cost = input_cost
                        cheapest_haiku = (provider_id, model_id)
                
                if cheapest_haiku:
                    provider_id, model_id = cheapest_haiku
                    logger.debug(f"Selected Haiku model '{provider_id}/{model_id}' for Anthropic health check")
                    return f"{provider_id}/{model_id}"
                else:
                    # Use first Haiku if no cost info
                    provider_id, model_id, _, _ = haiku_models[0]
                    logger.debug(f"Using first Haiku model '{provider_id}/{model_id}' for Anthropic health check")
                    return f"{provider_id}/{model_id}"
        
        # For Groq, use llama-3.1-8b-instant for health checks (faster, non-reasoning model)
        if server_id == "groq":
            # Use llama-3.1-8b-instant directly - this is a Groq-native model, not in provider configs
            # Format: "groq/llama-3.1-8b-instant" but we need to find which provider uses groq
            # Since Groq is used by OpenAI provider, we'll use "openai/llama-3.1-8b-instant"
            # But actually, for Groq API, we can use the model ID directly without provider prefix
            # The health check will resolve it correctly via the server
            logger.debug(f"Using 'llama-3.1-8b-instant' for Groq health check (testing model)")
            # Find a provider that uses groq server to construct the model ID
            groq_provider = None
            for provider_id, _, _, _ in candidate_models:
                groq_provider = provider_id
                break
            if groq_provider:
                # Return model ID in format that will work with Groq server
                # The model ID will be resolved by the health check function
                return f"{groq_provider}/llama-3.1-8b-instant"
            else:
                # Fallback: use openai provider since Groq is typically used with OpenAI models
                logger.debug(f"Using 'openai/llama-3.1-8b-instant' for Groq health check (fallback)")
                return "openai/llama-3.1-8b-instant"
        
        # For other servers, find the cheapest model by comparing input costs
        cheapest_candidate = None
        cheapest_cost = float('inf')
        
        for provider_id, model_id, model_config, input_cost in candidate_models:
            if input_cost is not None and input_cost < cheapest_cost:
                cheapest_cost = input_cost
                cheapest_candidate = (provider_id, model_id)
        
        if cheapest_candidate:
            provider_id, model_id = cheapest_candidate
            logger.debug(f"Selected cheapest model '{provider_id}/{model_id}' (cost: ${cheapest_cost}/M tokens) for server '{server_id}'")
            return f"{provider_id}/{model_id}"
        
        # Fallback: use first model if no cost info available
        provider_id, model_id, _, _ = candidate_models[0]
        logger.debug(f"Using first available model '{provider_id}/{model_id}' for server '{server_id}' (no cost info available)")
        return f"{provider_id}/{model_id}"
        
    except Exception as e:
        logger.error(f"Error finding cheapest model for server '{server_id}': {e}", exc_info=True)
        return None


def _get_cheapest_model_for_provider(provider_id: str) -> Optional[str]:
    """
    Get the cheapest available model for a provider to use in health check test requests.
    
    NOTE: This function is kept for backward compatibility, but the registry contains server IDs,
    not provider IDs. Use _get_cheapest_model_for_server() for server IDs.
    
    Args:
        provider_id: The provider ID (e.g., "mistral", "openai") OR server ID (e.g., "cerebras", "openrouter")
    
    Returns:
        Model ID string (e.g., "mistral/mistral-small") or None if no models found
    """
    # First try as provider ID
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if provider_config:
            models = provider_config.get("models", [])
            if models:
                # Find the cheapest model by comparing input costs
                cheapest_model = None
                cheapest_cost = float('inf')
                
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    
                    # Get input cost per million tokens
                    costs = model.get("costs", {})
                    input_cost = costs.get("input_per_million_token", {}).get("price")
                    
                    if input_cost is not None and input_cost < cheapest_cost:
                        cheapest_cost = input_cost
                        cheapest_model = model.get("id")
                
                if cheapest_model:
                    logger.debug(f"Selected cheapest model '{cheapest_model}' (cost: ${cheapest_cost}/M tokens) for provider '{provider_id}'")
                    return f"{provider_id}/{cheapest_model}"
                
                # Fallback: use first model if no cost info available
                first_model = models[0]
                if isinstance(first_model, dict):
                    model_id = first_model.get("id")
                    if model_id:
                        logger.debug(f"Using first available model '{model_id}' for provider '{provider_id}' (no cost info available)")
                        return f"{provider_id}/{model_id}"
    except Exception as e:
        logger.debug(f"Error looking up '{provider_id}' as provider ID: {e}")
    
    # If not found as provider ID, try as server ID
    logger.debug(f"'{provider_id}' not found as provider ID, trying as server ID...")
    return _get_cheapest_model_for_server(provider_id)


async def _check_provider_health_endpoint(provider_id: str, health_endpoint: str) -> tuple[bool, Optional[str], Optional[float]]:
    """
    Check provider health via /health endpoint.
    
    Args:
        provider_id: Provider ID for logging
        health_endpoint: Full URL to health endpoint
    
    Returns:
        Tuple of (is_healthy, error_message, response_time_ms)
    """
    try:
        start_time = time.time()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(health_endpoint)
            response_time_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
            if response.status_code == 200:
                return True, None, response_time_ms
            else:
                return False, f"HTTP {response.status_code}", response_time_ms
    except httpx.TimeoutException:
        response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
        return False, "Timeout", response_time_ms
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
        return False, str(e), response_time_ms


async def _check_provider_via_test_request(provider_id: str, model_id: str, secrets_manager: SecretsManager) -> tuple[bool, Optional[str], Optional[float]]:
    """
    Check provider health by making a minimal test LLM request.
    
    Args:
        provider_id: Provider ID (actually server_id like "groq", "openrouter")
        model_id: Model ID to test (e.g., "mistral/mistral-small" or "openai/llama-3.1-8b-instant")
        secrets_manager: SecretsManager instance
    
    Returns:
        Tuple of (is_healthy, error_message, response_time_ms)
    
    TODO: Investigate OpenRouter health check - logs don't show up in OpenRouter web app activities.
          This suggests the health check requests might not be reaching OpenRouter correctly,
          or they might not be logged by OpenRouter. Need to verify:
          1. Are the health check requests actually being sent to OpenRouter?
          2. Are they using the correct API key and headers?
          3. Why don't they appear in OpenRouter's activity logs?
          4. Is the health check actually validating OpenRouter's availability correctly?
    """
    try:
        # Special case: For Groq health checks, use llama-3.1-8b-instant directly
        # This model is not in provider configs, so we bypass the normal resolution
        if provider_id == "groq" and "llama-3.1-8b-instant" in model_id:
            logger.debug(f"Using direct Groq API call for health check with model 'llama-3.1-8b-instant'")
            # Get Groq client directly
            provider_client = _get_provider_client("groq")
            if not provider_client:
                return False, "Groq provider client not found", None
            
            # Make minimal test request
            test_messages = [
                {"role": "system", "content": "Answer short"},
                {"role": "user", "content": "1+2?"}
            ]
            
            # Call Groq client directly with the model ID
            start_time = time.time()
            try:
                response = await asyncio.wait_for(
                    provider_client(
                        task_id="health_check",
                        model_id="llama-3.1-8b-instant",  # Direct Groq model ID
                        messages=test_messages,
                        secrets_manager=secrets_manager,
                        tools=None,
                        tool_choice=None,
                        stream=False,
                        temperature=0.0
                    ),
                    timeout=15.0
                )
                response_time_ms = (time.time() - start_time) * 1000
                
                if hasattr(response, 'success'):
                    if response.success:
                        return True, None, response_time_ms
                    else:
                        error_msg = getattr(response, 'error_message', 'Unknown error')
                        return False, error_msg, response_time_ms
                else:
                    return False, f"Unexpected response type: {type(response)}", response_time_ms
            except asyncio.TimeoutError:
                response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
                return False, "Request timeout", response_time_ms
            except Exception as e:
                response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
                logger.error(f"Exception during Groq health check test request: {e}", exc_info=True)
                return False, str(e), response_time_ms
        
        # Normal flow for other providers/models
        # Resolve model_id to get actual server and transformed model_id
        default_server_id, transformed_model_id = resolve_default_server_from_provider_config(model_id)
        if default_server_id and transformed_model_id:
            # Use the transformed model_id with server prefix
            actual_model_id = transformed_model_id
            # Extract provider prefix from transformed model_id
            if "/" in actual_model_id:
                provider_prefix = actual_model_id.split("/", 1)[0]
            else:
                logger.warning(f"Transformed model_id '{actual_model_id}' does not contain provider prefix")
                return False, "Invalid model_id format", None
        else:
            # No server resolution - use original
            if "/" in model_id:
                provider_prefix = model_id.split("/", 1)[0]
                actual_model_id = model_id.split("/", 1)[1]
            else:
                logger.warning(f"Model_id '{model_id}' does not contain provider prefix")
                return False, "Invalid model_id format", None
        
        # Get provider client
        provider_client = _get_provider_client(provider_prefix)
        if not provider_client:
            return False, f"Provider client not found for '{provider_prefix}'", None
        
        # Extract model suffix from actual_model_id (provider clients expect just the model suffix, not "provider/model-id")
        # For example: "anthropic/claude-haiku-4-5-20250929" -> "claude-haiku-4-5-20250929"
        #              "mistral/mistral-small-latest" -> "mistral-small-latest"
        model_suffix = actual_model_id
        if "/" in actual_model_id:
            model_suffix = actual_model_id.split("/", 1)[1]
        
        # Make minimal test request
        # System prompt: "Answer short"
        # User message: "1+2?"
        test_messages = [
            {"role": "system", "content": "Answer short"},
            {"role": "user", "content": "1+2?"}
        ]
        
        # Call provider with timeout (non-streaming mode) and measure response time
        start_time = time.time()
        try:
            response = await asyncio.wait_for(
                provider_client(
                    task_id="health_check",
                    model_id=model_suffix,  # Pass just the model suffix, not the full "provider/model-id" format
                    messages=test_messages,
                    secrets_manager=secrets_manager,
                    tools=None,
                    tool_choice=None,
                    stream=False,  # Non-streaming for health check
                    temperature=0.0
                ),
                timeout=15.0  # 15 second timeout for test request
            )
            response_time_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            # Check if response indicates success
            # Response should be a UnifiedResponse object (not a stream when stream=False)
            if hasattr(response, 'success'):
                if response.success:
                    return True, None, response_time_ms
                else:
                    error_msg = getattr(response, 'error_message', 'Unknown error')
                    return False, error_msg, response_time_ms
            else:
                # Unexpected response type
                return False, f"Unexpected response type: {type(response)}", response_time_ms
        except asyncio.TimeoutError:
            response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
            return False, "Request timeout", response_time_ms
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
            logger.error(f"Exception during health check test request for '{provider_id}': {e}", exc_info=True)
            return False, str(e), response_time_ms
            
    except Exception as e:
        logger.error(f"Error checking provider '{provider_id}' via test request: {e}", exc_info=True)
        return False, str(e), None


async def _check_provider_health(provider_id: str, health_endpoint: Optional[str] = None) -> Dict[str, Any]:
    """
    Check health of a single provider with a single attempt.
    
    Makes one health check attempt per provider. This ensures we only make
    a single request per provider every 5 minutes (as scheduled by Celery Beat).
    
    Args:
        provider_id: Provider ID to check
        health_endpoint: Optional health endpoint URL (if provider has one)
    
    Returns:
        Dict with status, last_check, last_error
    """
    logger.info(f"Health check: Checking provider '{provider_id}'...")
    
    # Initialize services outside try block so they're available in finally
    cache_service = CacheService()
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        
        # Determine check method
        use_health_endpoint = health_endpoint is not None
        
        # Single attempt (no retry to avoid duplicate requests)
        success = False
        error = None
        response_time_ms = None
        
        if use_health_endpoint:
            success, error, response_time_ms = await _check_provider_health_endpoint(provider_id, health_endpoint)
        else:
            # Use test request - need to find cheapest model
            # Note: provider_id is actually a server_id from the registry (e.g., "cerebras", "openrouter")
            # TODO: OpenRouter health check - verify requests are actually reaching OpenRouter and appearing in their activity logs
            model_id = _get_cheapest_model_for_server(provider_id)
            if model_id:
                success, error, response_time_ms = await _check_provider_via_test_request(provider_id, model_id, secrets_manager)
            else:
                error = "No available models for test request"
                logger.warning(f"Health check: Server '{provider_id}' has no models configured that use this server. Cannot perform health check.")
        
        # Determine status based on single attempt
        if success:
            status = "healthy"
            last_error = None
            logger.info(f"Health check: Provider '{provider_id}' is healthy ({response_time_ms:.1f}ms)" if response_time_ms else f"Health check: Provider '{provider_id}' is healthy")
        else:
            status = "unhealthy"
            last_error_raw = error
            last_error = _sanitize_error_message(last_error_raw)
            
            # Log with additional context for credential errors
            if _is_credential_error(last_error_raw):
                logger.error(
                    f"Health check: Provider '{provider_id}' is unhealthy due to credential/authentication error. "
                    f"Error: {last_error_raw}"
                )
                logger.warning(
                    f"Health check: Provider '{provider_id}' requires valid credentials to be configured. "
                    f"Please verify the credentials in the secrets manager. Health checks will continue to fail until this is resolved."
                )
            else:
                logger.error(f"Health check: Provider '{provider_id}' is unhealthy. Error: {last_error_raw}")
        
        # Get existing health data to preserve response_times_ms
        cache_key = f"{HEALTH_CHECK_CACHE_KEY_PREFIX}{provider_id}"
        existing_health_data = {}
        try:
            client = await cache_service.client
            if client:
                existing_data_json = await client.get(cache_key)
                if existing_data_json:
                    if isinstance(existing_data_json, bytes):
                        existing_data_json = existing_data_json.decode('utf-8')
                    existing_health_data = json.loads(existing_data_json)
        except Exception as e:
            logger.debug(f"Could not retrieve existing health data for '{provider_id}': {e}")
        
        # Update response_times_ms array (keep last 5)
        response_times_ms = existing_health_data.get("response_times_ms", {})
        current_timestamp = int(time.time())
        
        # Add new response time if we have one
        if response_time_ms is not None:
            response_times_ms[str(current_timestamp)] = round(response_time_ms, 2)
            
            # Keep only last 5 entries (sorted by timestamp, newest first)
            sorted_times = sorted(response_times_ms.items(), key=lambda x: int(x[0]), reverse=True)
            response_times_ms = dict(sorted_times[:5])
        
        # Record health event if status changed (for historical tracking)
        previous_status = existing_health_data.get("status")
        previous_check_timestamp = existing_health_data.get("last_check")
        await _record_health_event_if_changed(
            service_type="provider",
            service_id=provider_id,
            new_status=status,
            previous_status=previous_status,
            previous_check_timestamp=previous_check_timestamp,
            error_message=last_error,
            response_time_ms=response_time_ms
        )
        
        # Store result in cache
        health_data = {
            "status": status,
            "last_check": current_timestamp,
            "last_error": last_error,
            "response_times_ms": response_times_ms
        }
        
        try:
            client = await cache_service.client
            if client:
                await client.set(
                    cache_key,
                    json.dumps(health_data),
                    ex=HEALTH_CHECK_CACHE_TTL
                )
                logger.debug(f"Health check: Stored health status for '{provider_id}' in cache: {status}")
            else:
                logger.warning(f"Health check: Cache client not available, cannot store health status for '{provider_id}'")
        except Exception as e:
            logger.error(f"Health check: Failed to store health status for '{provider_id}' in cache: {e}", exc_info=True)
        
        return health_data
    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors during cleanup
        try:
            await secrets_manager.aclose()
        except Exception as cleanup_error:
            logger.warning(f"Error closing SecretsManager during provider health check: {cleanup_error}")


async def _check_brave_search_health(secrets_manager: SecretsManager) -> Dict[str, Any]:
    """
    Check health of Brave Search API via connectivity check (no billing).
    
    Brave Search does not have a dedicated /health endpoint, and performing
    test search requests would incur billing costs. Instead, we verify:
    1. API key is configured
    2. API endpoint is reachable (HEAD request, no billing)
    
    Args:
        secrets_manager: SecretsManager instance
    
    Returns:
        Dict with status, last_check, last_error, response_times_ms
    """
    logger.info("Health check: Checking provider 'brave' (Brave Search)...")
    
    # Initialize cache service
    cache_service = CacheService()
    
    # Import Brave Search health check function
    from backend.shared.providers.brave.brave_search import check_brave_search_health
    
    # Single attempt (measure response time)
    start_time = time.time()
    success, error = await check_brave_search_health(secrets_manager)
    response_time_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
    
    # Determine status based on single attempt
    if success:
        status = "healthy"
        last_error = None
        logger.info(f"Health check: Provider 'brave' is healthy ({response_time_ms:.1f}ms)")
    else:
        status = "unhealthy"
        last_error_raw = error
        last_error = _sanitize_error_message(last_error_raw)
        logger.error(f"Health check: Provider 'brave' is unhealthy. Error: {last_error_raw}")
    
    # Get existing health data to preserve response_times_ms
    cache_key = f"{HEALTH_CHECK_CACHE_KEY_PREFIX}brave"
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'brave': {e}")
    
    # Update response_times_ms array (keep last 5)
    response_times_ms_dict = existing_health_data.get("response_times_ms", {})
    current_timestamp = int(time.time())
    
    # Add new response time if we have one
    if response_time_ms is not None:
        response_times_ms_dict[str(current_timestamp)] = round(response_time_ms, 2)
        
        # Keep only last 5 entries (sorted by timestamp, newest first)
        sorted_times = sorted(response_times_ms_dict.items(), key=lambda x: int(x[0]), reverse=True)
        response_times_ms_dict = dict(sorted_times[:5])
    
    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="provider",
        service_id="brave",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )
    
    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": response_times_ms_dict
    }
    
    try:
        client = await cache_service.client
        if client:
            await client.set(
                cache_key,
                json.dumps(health_data),
                ex=HEALTH_CHECK_CACHE_TTL
            )
            logger.debug(f"Health check: Stored health status for 'brave' in cache: {status}")
        else:
            logger.warning("Health check: Cache client not available, cannot store health status for 'brave'")
    except Exception as e:
        logger.error(f"Health check: Failed to store health status for 'brave' in cache: {e}", exc_info=True)
    
    return health_data


async def _check_app_api_health(app_id: str, port: int = 8000) -> tuple[bool, Optional[str]]:
    """
    Check app API health by making a request to the app's /health endpoint.
    
    Args:
        app_id: App ID (e.g., "ai", "web")
        port: Internal port (default: 8000)
    
    Returns:
        Tuple of (is_healthy, error_message) - error_message is sanitized
    """
    try:
        hostname = f"app-{app_id}"
        health_url = f"http://{hostname}:{port}/health"
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_url)
            if response.status_code == 200:
                # Verify response structure
                try:
                    data = response.json()
                    if data.get("status") == "ok":
                        return True, None
                    else:
                        return False, _sanitize_error_message(f"Unexpected status: {data.get('status')}")
                except json.JSONDecodeError:
                    return False, _sanitize_error_message("Invalid JSON response")
            else:
                return False, _sanitize_error_message(f"HTTP {response.status_code}")
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.RequestError as e:
        # Sanitize request errors
        error_str = str(e)
        if "name resolution" in error_str.lower() or "temporary failure" in error_str.lower():
            return False, "connection_error"
        return False, _sanitize_error_message(error_str)
    except Exception as e:
        return False, _sanitize_error_message(str(e))


async def _check_app_worker_health(app_id: str) -> tuple[bool, Optional[str]]:
    """
    Check app worker health via Celery worker inspection.
    
    Args:
        app_id: App ID (e.g., "ai", "web")
    
    Returns:
        Tuple of (is_healthy, error_message)
    """
    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app
        
        # Worker queue name follows pattern: app_{app_id}
        queue_name = f"app_{app_id}"
        
        # Inspect active workers
        inspect = celery_app.control.inspect()
        
        # Get active workers (workers that are currently processing tasks)
        active_workers = inspect.active_queues()
        
        if not active_workers:
            return False, "No active Celery workers found"
        
        # Check if any worker is listening to this app's queue
        worker_found = False
        for worker_name, queues in active_workers.items():
            if queues:
                # queues is a list of queue dicts with 'name' key
                queue_names = [q.get('name') for q in queues if isinstance(q, dict)]
                if queue_name in queue_names:
                    worker_found = True
                    break
        
        if worker_found:
            return True, None
        else:
            return False, "no_worker"
    except Exception as e:
        logger.error(f"Error checking worker health for app '{app_id}': {e}", exc_info=True)
        return False, _sanitize_error_message(str(e))


async def _check_app_health(app_id: str, port: int = 8000) -> Dict[str, Any]:
    """
    Check health of a single app (both API and worker) with double-attempt logic.
    
    Args:
        app_id: App ID to check
        port: Internal port (default: 8000)
    
    Returns:
        Dict with api_status, worker_status, last_check, last_error
    """
    logger.info(f"Health check: Checking app '{app_id}' (API and worker)...")
    
    # Initialize cache service
    cache_service = CacheService()
    
    # Check API health (first attempt)
    api_attempt1_success, api_attempt1_error = await _check_app_api_health(app_id, port)
    
    # If first attempt failed, retry once
    if not api_attempt1_success:
        logger.warning(f"Health check: App '{app_id}' API first attempt failed: {api_attempt1_error}. Retrying...")
        await asyncio.sleep(1)
        api_attempt2_success, api_attempt2_error = await _check_app_api_health(app_id, port)
        api_healthy = api_attempt2_success
        api_error = api_attempt2_error or api_attempt1_error
    else:
        api_healthy = True
        api_error = None
    
    # Check worker health (first attempt)
    worker_attempt1_success, worker_attempt1_error = await _check_app_worker_health(app_id)
    
    # If first attempt failed, retry once
    if not worker_attempt1_success:
        logger.warning(f"Health check: App '{app_id}' worker first attempt failed: {worker_attempt1_error}. Retrying...")
        await asyncio.sleep(1)
        worker_attempt2_success, worker_attempt2_error = await _check_app_worker_health(app_id)
        worker_healthy = worker_attempt2_success
        worker_error = worker_attempt2_error or worker_attempt1_error
    else:
        worker_healthy = True
        worker_error = None
    
    # Determine overall app status
    if api_healthy and worker_healthy:
        overall_status = "healthy"
    elif api_healthy or worker_healthy:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"
    
    cache_key = f"{HEALTH_CHECK_APP_CACHE_KEY_PREFIX}{app_id}"
    current_timestamp = int(time.time())
    
    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for app '{app_id}': {e}")
    
    # Determine error message for event recording (combine API and worker errors)
    combined_error = None
    if not api_healthy and api_error:
        combined_error = f"API: {api_error}"
    if not worker_healthy and worker_error:
        if combined_error:
            combined_error += f", Worker: {worker_error}"
        else:
            combined_error = f"Worker: {worker_error}"
    
    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="app",
        service_id=app_id,
        new_status=overall_status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=combined_error,
        response_time_ms=None  # Apps don't have response time tracking
    )
    
    # Store result in cache
    health_data = {
        "status": overall_status,
        "api": {
            "status": "healthy" if api_healthy else "unhealthy",
            "last_error": api_error
        },
        "worker": {
            "status": "healthy" if worker_healthy else "unhealthy",
            "last_error": worker_error
        },
        "last_check": current_timestamp
    }
    
    try:
        client = await cache_service.client
        if client:
            await client.set(
                cache_key,
                json.dumps(health_data),
                ex=HEALTH_CHECK_CACHE_TTL
            )
            logger.debug(f"Health check: Stored health status for app '{app_id}' in cache: {overall_status}")
        else:
            logger.warning(f"Health check: Cache client not available, cannot store health status for app '{app_id}'")
    except Exception as e:
        logger.error(f"Health check: Failed to store health status for app '{app_id}' in cache: {e}", exc_info=True)
    
    return health_data


async def _check_stripe_health(secrets_manager: SecretsManager) -> Dict[str, Any]:
    """Check Stripe API health via a lightweight API call."""
    logger.info("Health check: Checking Stripe API...")
    cache_service = CacheService()

    try:
        import stripe

        # Get Stripe API key from Vault
        stripe_api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/stripe",
            secret_key="api_key"
        )

        if not stripe_api_key:
            status = "unhealthy"
            last_error = "missing_api_key"
            logger.warning("Health check: Stripe API key not configured")
        else:
            stripe.api_key = stripe_api_key
            start_time = time.time()

            try:
                # Lightweight test: list account (requires no parameters)
                stripe.Account.retrieve()
                response_time_ms = (time.time() - start_time) * 1000
                status = "healthy"
                last_error = None
                logger.info(f"Health check: Stripe API is healthy ({response_time_ms:.1f}ms)")
            except stripe.error.StripeError as e:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                last_error = _sanitize_error_message(str(e))
                logger.error(f"Health check: Stripe API is unhealthy: {str(e)}")

    except Exception as e:
        status = "unhealthy"
        last_error = _sanitize_error_message(str(e))
        response_time_ms = None
        logger.error(f"Health check: Error checking Stripe: {e}", exc_info=True)

    cache_key = f"{HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX}stripe"
    current_timestamp = int(time.time())

    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'stripe': {e}")

    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="external",
        service_id="stripe",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )

    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": {str(current_timestamp): round(response_time_ms, 2)} if response_time_ms else {}
    }

    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(health_data), ex=HEALTH_CHECK_CACHE_TTL)
    except Exception as e:
        logger.error(f"Health check: Failed to store Stripe health status in cache: {e}")

    return health_data


async def _check_sightengine_health(secrets_manager: SecretsManager) -> Dict[str, Any]:
    """Check Sightengine API health via test request."""
    logger.info("Health check: Checking Sightengine API...")
    cache_service = CacheService()

    try:
        # Get Sightengine credentials from Vault
        api_user = await secrets_manager.get_secret(
            secret_path="kv/data/providers/sightengine",
            secret_key="api_user"
        )
        api_secret = await secrets_manager.get_secret(
            secret_path="kv/data/providers/sightengine",
            secret_key="api_secret"
        )

        if not api_user or not api_secret:
            status = "unhealthy"
            last_error = "missing_credentials"
            response_time_ms = None
            logger.warning("Health check: Sightengine credentials not configured")
        else:
            start_time = time.time()

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Test with a simple API call - get moderation list (lightweight)
                    response = await client.get(
                        "https://api.sightengine.com/1.0/moderation/list",
                        params={"user_id": api_user, "secret": api_secret}
                    )
                    response_time_ms = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        status = "healthy"
                        last_error = None
                        logger.info(f"Health check: Sightengine API is healthy ({response_time_ms:.1f}ms)")
                    else:
                        status = "unhealthy"
                        last_error = _sanitize_error_message(f"HTTP {response.status_code}")
                        logger.error(f"Health check: Sightengine API returned {response.status_code}")

            except httpx.TimeoutException:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                last_error = "timeout"
                logger.error("Health check: Sightengine API timeout")
            except Exception as e:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                last_error = _sanitize_error_message(str(e))
                logger.error(f"Health check: Sightengine API error: {e}")

    except Exception as e:
        status = "unhealthy"
        last_error = _sanitize_error_message(str(e))
        response_time_ms = None
        logger.error(f"Health check: Error checking Sightengine: {e}", exc_info=True)

    cache_key = f"{HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX}sightengine"
    current_timestamp = int(time.time())

    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'sightengine': {e}")

    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="external",
        service_id="sightengine",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )

    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": {str(current_timestamp): round(response_time_ms, 2)} if response_time_ms else {}
    }

    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(health_data), ex=HEALTH_CHECK_CACHE_TTL)
    except Exception as e:
        logger.error(f"Health check: Failed to store Sightengine health status in cache: {e}")

    return health_data


async def _check_mailjet_health(secrets_manager: SecretsManager) -> Dict[str, Any]:
    """Check Mailjet API health via test request."""
    logger.info("Health check: Checking Mailjet API...")
    cache_service = CacheService()

    try:
        # Get Mailjet credentials from Vault
        api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_key"
        )
        api_secret = await secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_secret"
        )

        if not api_key or not api_secret:
            status = "unhealthy"
            last_error = "missing_credentials"
            response_time_ms = None
            logger.warning("Health check: Mailjet credentials not configured")
        else:
            start_time = time.time()

            try:
                import base64
                # Basic auth for Mailjet API
                credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()

                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Test with a lightweight API call - list webhook configurations
                    response = await client.get(
                        "https://api.mailjet.com/v3.1/webhookevents",
                        headers={"Authorization": f"Basic {credentials}"}
                    )
                    response_time_ms = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        status = "healthy"
                        last_error = None
                        logger.info(f"Health check: Mailjet API is healthy ({response_time_ms:.1f}ms)")
                    else:
                        status = "unhealthy"
                        last_error = _sanitize_error_message(f"HTTP {response.status_code}")
                        logger.error(f"Health check: Mailjet API returned {response.status_code}")

            except httpx.TimeoutException:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                last_error = "timeout"
                logger.error("Health check: Mailjet API timeout")
            except Exception as e:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                last_error = _sanitize_error_message(str(e))
                logger.error(f"Health check: Mailjet API error: {e}")

    except Exception as e:
        status = "unhealthy"
        last_error = _sanitize_error_message(str(e))
        response_time_ms = None
        logger.error(f"Health check: Error checking Mailjet: {e}", exc_info=True)

    cache_key = f"{HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX}mailjet"
    current_timestamp = int(time.time())

    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'mailjet': {e}")

    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="external",
        service_id="mailjet",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )

    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": {str(current_timestamp): round(response_time_ms, 2)} if response_time_ms else {}
    }

    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(health_data), ex=HEALTH_CHECK_CACHE_TTL)
    except Exception as e:
        logger.error(f"Health check: Failed to store Mailjet health status in cache: {e}")

    return health_data


async def _check_aws_bedrock_health(secrets_manager: SecretsManager) -> Dict[str, Any]:
    """Check AWS Bedrock API health via test request."""
    logger.info("Health check: Checking AWS Bedrock...")
    cache_service = CacheService()

    try:
        # Get AWS credentials from Vault
        aws_access_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/aws",
            secret_key="access_key_id"
        )
        aws_secret_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/aws",
            secret_key="secret_access_key"
        )
        aws_region = await secrets_manager.get_secret(
            secret_path="kv/data/providers/aws",
            secret_key="region"
        ) or "us-east-1"

        if not aws_access_key or not aws_secret_key:
            status = "unhealthy"
            last_error = "missing_credentials"
            response_time_ms = None
            logger.warning("Health check: AWS credentials not configured")
        else:
            start_time = time.time()

            try:
                import boto3
                from botocore.exceptions import ClientError

                # Create Bedrock client
                bedrock_client = boto3.client(
                    "bedrock",
                    region_name=aws_region,
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key
                )

                # Test with list_foundation_models (lightweight, read-only)
                bedrock_client.list_foundation_models()
                response_time_ms = (time.time() - start_time) * 1000
                status = "healthy"
                last_error = None
                logger.info(f"Health check: AWS Bedrock is healthy ({response_time_ms:.1f}ms)")

            except ClientError as e:
                # Handle AWS-specific errors (including credential errors)
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))
                error_str = f"{error_code}: {error_message}"
                last_error = _sanitize_error_message(error_str)
                
                # Check for credential errors using both error code and message
                credential_error_codes = [
                    'UnrecognizedClientException',
                    'InvalidUserID.NotFound',
                    'InvalidClientTokenId',
                    'SignatureDoesNotMatch',
                    'InvalidAccessKeyId',
                    'AccessDenied',
                    'InvalidSecurity',
                    'TokenRefreshRequired'
                ]
                
                is_cred_error = error_code in credential_error_codes or _is_credential_error(error_str)
                
                if is_cred_error:
                    logger.error(
                        f"Health check: AWS Bedrock credential/authentication error ({error_code}): {error_message}",
                        exc_info=True
                    )
                    logger.warning(
                        "Health check: AWS Bedrock credentials appear to be invalid or deactivated. "
                        "Please verify the AWS credentials (access_key_id, secret_access_key) in the secrets manager. "
                        "Health checks will continue to fail until valid credentials are configured."
                    )
                else:
                    logger.error(f"Health check: AWS Bedrock API error ({error_code}): {error_message}", exc_info=True)
            except Exception as e:
                response_time_ms = (time.time() - start_time) * 1000
                status = "unhealthy"
                error_str = str(e)
                last_error = _sanitize_error_message(error_str)
                
                # Detect and log credential errors with additional context
                if _is_credential_error(error_str):
                    logger.error(
                        f"Health check: AWS Bedrock error (credential/authentication issue): {e}",
                        exc_info=True
                    )
                    logger.warning(
                        "Health check: AWS Bedrock credentials appear to be invalid or deactivated. "
                        "Please verify the AWS credentials (access_key_id, secret_access_key) in the secrets manager. "
                        "Health checks will continue to fail until valid credentials are configured."
                    )
                else:
                    logger.error(f"Health check: AWS Bedrock error: {e}", exc_info=True)

    except Exception as e:
        status = "unhealthy"
        error_str = str(e)
        last_error = _sanitize_error_message(error_str)
        response_time_ms = None
        
        # Detect and log credential errors with additional context
        if _is_credential_error(error_str):
            logger.error(
                f"Health check: Error checking AWS Bedrock (credential/authentication issue): {e}",
                exc_info=True
            )
            logger.warning(
                "Health check: AWS Bedrock credentials appear to be invalid or deactivated. "
                "Please verify the AWS credentials in the secrets manager."
            )
        else:
            logger.error(f"Health check: Error checking AWS Bedrock: {e}", exc_info=True)

    cache_key = f"{HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX}bedrock"
    current_timestamp = int(time.time())

    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'bedrock': {e}")

    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="external",
        service_id="bedrock",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )

    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": {str(current_timestamp): round(response_time_ms, 2)} if response_time_ms else {}
    }

    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(health_data), ex=HEALTH_CHECK_CACHE_TTL)
    except Exception as e:
        logger.error(f"Health check: Failed to store AWS Bedrock health status in cache: {e}")

    return health_data


async def _check_vercel_domain_health(domain: str) -> Dict[str, Any]:
    """Check Vercel hosted domain health via HTTP request."""
    logger.info(f"Health check: Checking Vercel domain '{domain}'...")
    cache_service = CacheService()

    if not domain:
        status = "unhealthy"
        last_error = "missing_domain"
        response_time_ms = None
        logger.warning("Health check: Vercel domain not configured")
    else:
        try:
            start_time = time.time()

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check main domain with a simple HTTP GET
                response = await client.get(f"https://{domain}", follow_redirects=True)
                response_time_ms = (time.time() - start_time) * 1000

                # Accept 2xx or 3xx status codes (redirects are expected)
                if response.status_code < 400:
                    status = "healthy"
                    last_error = None
                    logger.info(f"Health check: Vercel domain '{domain}' is healthy ({response_time_ms:.1f}ms)")
                else:
                    status = "unhealthy"
                    last_error = _sanitize_error_message(f"HTTP {response.status_code}")
                    logger.error(f"Health check: Vercel domain '{domain}' returned {response.status_code}")

        except httpx.TimeoutException:
            response_time_ms = (time.time() - start_time) * 1000
            status = "unhealthy"
            last_error = "timeout"
            logger.error(f"Health check: Vercel domain '{domain}' timeout")
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            status = "unhealthy"
            last_error = _sanitize_error_message(str(e))
            logger.error(f"Health check: Vercel domain '{domain}' error: {e}")

    cache_key = f"{HEALTH_CHECK_EXTERNAL_CACHE_KEY_PREFIX}vercel"
    current_timestamp = int(time.time())

    # Get existing health data to check for status change
    existing_health_data = {}
    try:
        client = await cache_service.client
        if client:
            existing_data_json = await client.get(cache_key)
            if existing_data_json:
                if isinstance(existing_data_json, bytes):
                    existing_data_json = existing_data_json.decode('utf-8')
                existing_health_data = json.loads(existing_data_json)
    except Exception as e:
        logger.debug(f"Could not retrieve existing health data for 'vercel': {e}")

    # Record health event if status changed (for historical tracking)
    previous_status = existing_health_data.get("status")
    previous_check_timestamp = existing_health_data.get("last_check")
    await _record_health_event_if_changed(
        service_type="external",
        service_id="vercel",
        new_status=status,
        previous_status=previous_status,
        previous_check_timestamp=previous_check_timestamp,
        error_message=last_error,
        response_time_ms=response_time_ms
    )

    # Store result in cache
    health_data = {
        "status": status,
        "last_check": current_timestamp,
        "last_error": last_error,
        "response_times_ms": {str(current_timestamp): round(response_time_ms, 2)} if response_time_ms else {}
    }

    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(health_data), ex=HEALTH_CHECK_CACHE_TTL)
    except Exception as e:
        logger.error(f"Health check: Failed to store Vercel domain health status in cache: {e}")

    return health_data


@app.task(name="health_check.check_all_apps", bind=True)
def check_all_apps_health(self):
    """
    Periodic task to check health of all app services (API and workers).
    This task is scheduled by Celery Beat.
    
    Checks app APIs and workers every 5 minutes.
    Only checks apps that are discovered and enabled (same logic as /v1/apps/metadata).
    
    Uses a distributed lock to prevent multiple concurrent executions.
    """
    # Use distributed lock to prevent concurrent health checks
    # This prevents multiple API instances or retries from running duplicate checks
    lock_key = "health_check:lock:apps"
    lock_ttl = 600  # 10 minutes - longer than the check interval to prevent overlap
    
    async def acquire_lock_and_run():
        cache_service = CacheService()
        client = await cache_service.client
        if not client:
            logger.error("Health check: Cache client not available, cannot acquire lock. Skipping health check.")
            return
        
        # Try to acquire lock using SET with NX (only set if not exists) and EX (expiration)
        # This is atomic and prevents race conditions
        lock_acquired = await client.set(lock_key, str(time.time()), ex=lock_ttl, nx=True)
        
        if not lock_acquired:
            logger.warning("Health check: Another app health check is already running. Skipping this execution to prevent duplicate requests.")
            return
        
        try:
            logger.info("=" * 80)
            logger.info("Health check: Starting periodic health check for all apps...")
            logger.info("=" * 80)
            
            # Get discovered apps from cache (same as /v1/apps/metadata uses)
            # This ensures we only check apps that are actually enabled and have the right stage
            # Run async discovery in a nested function
            async def get_app_ids():
                app_ids = []
                try:
                    from backend.core.api.app.services.cache import CacheService
                    from backend.shared.python_schemas.app_metadata_schemas import AppYAML
                    
                    cache_service = CacheService()
                    discovered_metadata_json = None
                    
                    # Try to get from cache
                    try:
                        client = await cache_service.client
                        if client:
                            metadata_json = await client.get("discovered_apps_metadata_v1")
                            if metadata_json:
                                if isinstance(metadata_json, bytes):
                                    metadata_json = metadata_json.decode('utf-8')
                                discovered_metadata_json = json.loads(metadata_json)
                    except Exception as cache_error:
                        logger.warning(f"Could not retrieve discovered apps from cache: {cache_error}")
                    
                    # If cache is empty, discover apps by fetching metadata (same logic as discover_apps)
                    if not discovered_metadata_json:
                        logger.info("Health check: Discovered apps not in cache, discovering apps via metadata endpoints...")
                        import httpx
                        from backend.core.api.main import scan_filesystem_for_apps, filter_app_components_by_stage
                        
                        DEFAULT_APP_INTERNAL_PORT = 8000
                        server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
                        disabled_app_ids = config_manager.get_disabled_apps()
                        all_app_ids = scan_filesystem_for_apps()
                        
                        # Check all apps (except disabled ones) - filtering happens at component level
                        apps_to_check = [app_id for app_id in all_app_ids if app_id not in disabled_app_ids]
                        
                        logger.info(f"Health check: Will check {len(apps_to_check)} app(s): {apps_to_check}")
                        
                        discovered = {}
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            for app_id in apps_to_check:
                                hostname = f"app-{app_id}"
                                metadata_url = f"http://{hostname}:{DEFAULT_APP_INTERNAL_PORT}/metadata"
                                try:
                                    response = await client.get(metadata_url)
                                    response.raise_for_status()
                                    app_metadata_json = response.json()
                                    
                                    # Filter components by stage before parsing
                                    filtered_metadata_json = filter_app_components_by_stage(app_metadata_json, server_environment)
                                    
                                    # If no valid components after filtering, skip this app
                                    if filtered_metadata_json is None:
                                        continue
                                    
                                    app_yaml_data = AppYAML(**filtered_metadata_json)
                                    app_yaml_data.id = app_id
                                    discovered[app_id] = app_yaml_data
                                except Exception:
                                    # Skip apps that can't be reached or have invalid metadata
                                    continue
                        
                        app_ids = list(discovered.keys())
                    else:
                        # Use app IDs from cache - apps are already filtered by components when discovered
                        disabled_app_ids = config_manager.get_disabled_apps()
                        
                        cached_app_ids = list(discovered_metadata_json.keys())
                        app_ids = [app_id for app_id in cached_app_ids if app_id not in disabled_app_ids]
                        
                        logger.info(f"Health check: Retrieved {len(app_ids)} app(s) from cache: {', '.join(app_ids)}")
                
                except Exception as e:
                    logger.error(f"Error getting app list for health check: {e}", exc_info=True)
                    # Fallback: scan filesystem - check all apps (except disabled ones)
                    # Import here to avoid circular imports
                    from backend.core.api.main import scan_filesystem_for_apps
                    
                    APPS_DIR = "/app/backend/apps"
                    if os.path.isdir(APPS_DIR):
                        try:
                            disabled_app_ids = config_manager.get_disabled_apps()
                            
                            # Scan filesystem for all apps
                            all_app_ids = scan_filesystem_for_apps()
                            
                            # Check all apps except disabled ones
                            app_ids = [app_id for app_id in all_app_ids if app_id not in disabled_app_ids]
                            
                            logger.info(f"Health check: Fallback filesystem scan found {len(app_ids)} app(s): {app_ids}")
                        except OSError as scan_error:
                            logger.error(f"Error scanning apps directory {APPS_DIR}: {scan_error}")
                
                return app_ids
            
            # Get app IDs (run async function)
            app_ids = await get_app_ids()
            
            if not app_ids:
                logger.warning("Health check: No apps found to check. Skipping app health checks.")
                return
            
            logger.info(f"Health check: Found {len(app_ids)} app(s) to check: {', '.join(app_ids)}")
            
            # Run async health checks
            async def run_checks():
                tasks = []
                for app_id in app_ids:
                    task = _check_app_health(app_id)
                    tasks.append(task)
                
                # Run all checks concurrently
                logger.info(f"Health check: Executing {len(tasks)} app health check(s) concurrently...")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log results
                healthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "healthy")
                degraded_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "degraded")
                unhealthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "unhealthy")
                error_count = sum(1 for r in results if isinstance(r, Exception))
                
                logger.info("=" * 80)
                logger.info(
                    f"Health check: App health checks completed. "
                    f"Healthy: {healthy_count}, Degraded: {degraded_count}, Unhealthy: {unhealthy_count}, Errors: {error_count}"
                )
                logger.info("=" * 80)
                
                # Log details for unhealthy/degraded apps
                if unhealthy_count > 0 or degraded_count > 0:
                    for i, result in enumerate(results):
                        if isinstance(result, dict):
                            status = result.get("status")
                            if status in ["unhealthy", "degraded"]:
                                app_id = app_ids[i] if i < len(app_ids) else f"unknown_{i}"
                                api_status = result.get("api", {}).get("status", "unknown")
                                worker_status = result.get("worker", {}).get("status", "unknown")
                                logger.warning(
                                    f"Health check: App '{app_id}' is {status}. "
                                    f"API: {api_status}, Worker: {worker_status}"
                                )
            
            # Run async checks
            try:
                logger.info("Health check: Executing async app health checks...")
                await run_checks()
                logger.info("Health check: Async app health checks completed successfully")
            except Exception as e:
                logger.error(f"Health check: Error running app health checks: {e}", exc_info=True)
                raise  # Re-raise to ensure Celery knows the task failed
        finally:
            # Release the lock (delete the key)
            try:
                await client.delete(lock_key)
                logger.debug("Health check: Released distributed lock")
            except Exception as lock_error:
                logger.warning(f"Health check: Failed to release lock: {lock_error}")
    
    # Run the async function
    try:
        asyncio.run(acquire_lock_and_run())
    except Exception as e:
        logger.error(f"Health check: Error in lock acquisition or execution: {e}", exc_info=True)
        raise  # Re-raise to ensure Celery knows the task failed


@app.task(name="health_check.check_all_providers", bind=True)
def check_all_providers_health(self):
    """
    Periodic task to check health of all LLM providers and Brave Search.
    This task is scheduled by Celery Beat.
    
    Checks providers with /health endpoints every 1 minute.
    Checks providers without /health endpoints every 5 minutes.
    
    Uses a distributed lock to prevent multiple concurrent executions.
    """
    # Use distributed lock to prevent concurrent health checks
    # This prevents multiple API instances or retries from running duplicate checks
    lock_key = "health_check:lock:providers"
    lock_ttl = 600  # 10 minutes - longer than the check interval to prevent overlap
    
    async def acquire_lock_and_run():
        cache_service = CacheService()
        client = await cache_service.client
        if not client:
            logger.error("Health check: Cache client not available, cannot acquire lock. Skipping health check.")
            return
        
        # Try to acquire lock using SET with NX (only set if not exists) and EX (expiration)
        # This is atomic and prevents race conditions
        lock_acquired = await client.set(lock_key, str(time.time()), ex=lock_ttl, nx=True)
        
        if not lock_acquired:
            logger.warning("Health check: Another health check is already running. Skipping this execution to prevent duplicate requests.")
            return
        
        try:
            logger.info("=" * 80)
            logger.info("Health check: Starting periodic health check for all providers...")
            logger.info("=" * 80)
            
            # Get all providers from registry
            providers = list(PROVIDER_CLIENT_REGISTRY.keys())
            if not providers:
                logger.warning("Health check: No providers found in registry. Skipping health checks.")
                return
            
            logger.info(f"Health check: Found {len(providers)} LLM provider(s) to check: {', '.join(providers)}")
            
            # Run async health checks
            async def run_checks():
                # Initialize SecretsManager outside try block so it's available in finally
                secrets_manager = SecretsManager()
                
                try:
                    tasks = []
                    
                    # Check all LLM providers
                    for provider_id in providers:
                        # For now, all providers use test requests (no health endpoints configured yet)
                        # In the future, we can check if provider has health_endpoint configured
                        task = _check_provider_health(provider_id, health_endpoint=None)
                        tasks.append(task)
                    
                    # Also check Brave Search (not an LLM provider, so not in registry)
                    await secrets_manager.initialize()
                    brave_task = _check_brave_search_health(secrets_manager)
                    tasks.append(brave_task)
                    
                    # Run all checks concurrently
                    logger.info(f"Health check: Executing {len(tasks)} health check(s) concurrently...")
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Log results
                    healthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "healthy")
                    unhealthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "unhealthy")
                    error_count = sum(1 for r in results if isinstance(r, Exception))
                    
                    logger.info("=" * 80)
                    logger.info(
                        f"Health check: Completed. "
                        f"Healthy: {healthy_count}, Unhealthy: {unhealthy_count}, Errors: {error_count}"
                    )
                    logger.info("=" * 80)
                    
                    # Log details for unhealthy providers
                    if unhealthy_count > 0:
                        all_provider_ids = list(providers) + ["brave"]
                        for i, result in enumerate(results):
                            if isinstance(result, dict) and result.get("status") == "unhealthy":
                                provider_id = all_provider_ids[i] if i < len(all_provider_ids) else f"unknown_{i}"
                                logger.warning(
                                    f"Health check: Provider '{provider_id}' is unhealthy. "
                                    f"Last error: {result.get('last_error', 'Unknown')}"
                                )
                finally:
                    # CRITICAL: Close async resources (like httpx clients) before the event loop closes
                    # This prevents "Event loop is closed" errors during cleanup
                    try:
                        await secrets_manager.aclose()
                    except Exception as cleanup_error:
                        logger.warning(f"Error closing SecretsManager during provider health checks: {cleanup_error}")
            
            # Run async checks
            try:
                logger.info("Health check: Executing async health checks...")
                await run_checks()
                logger.info("Health check: Async health checks completed successfully")
            except Exception as e:
                logger.error(f"Health check: Error running health checks: {e}", exc_info=True)
                raise  # Re-raise to ensure Celery knows the task failed
        finally:
            # Release the lock (delete the key)
            try:
                await client.delete(lock_key)
                logger.debug("Health check: Released distributed lock")
            except Exception as lock_error:
                logger.warning(f"Health check: Failed to release lock: {lock_error}")
    
    # Run the async function
    try:
        asyncio.run(acquire_lock_and_run())
    except Exception as e:
        logger.error(f"Health check: Error in lock acquisition or execution: {e}", exc_info=True)
        raise  # Re-raise to ensure Celery knows the task failed


@app.task(name="health_check.check_external_services", bind=True)
def check_external_services_health(self):
    """
    Periodic task to check health of external services (Stripe, Sightengine, Mailjet, AWS Bedrock, Vercel).
    This task is scheduled by Celery Beat.

    Checks external services every 5 minutes.
    """
    logger.info("=" * 80)
    logger.info("Health check: Starting periodic health check for external services...")
    logger.info("=" * 80)

    async def run_checks():
        # Initialize SecretsManager outside try block so it's available in finally
        secrets_manager = SecretsManager()
        
        try:
            await secrets_manager.initialize()

            tasks = []

            # Check Stripe (only if payment is enabled)
            from backend.core.api.app.utils.server_mode import is_payment_enabled
            payment_enabled = is_payment_enabled()
            
            if payment_enabled:
                tasks.append(_check_stripe_health(secrets_manager))
                logger.info("Health check: Including Stripe health check (payment enabled)")
            else:
                logger.info("Health check: Skipping Stripe health check (payment disabled - self-hosted mode)")

            # Check Sightengine
            tasks.append(_check_sightengine_health(secrets_manager))

            # Check Mailjet
            tasks.append(_check_mailjet_health(secrets_manager))

            # Check AWS Bedrock
            tasks.append(_check_aws_bedrock_health(secrets_manager))

            # Check Vercel domain
            vercel_domain = os.getenv("VERCEL_DOMAIN", "")
            tasks.append(_check_vercel_domain_health(vercel_domain))

            # Run all checks concurrently
            logger.info(f"Health check: Executing {len(tasks)} external service health check(s) concurrently...")
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log results
            healthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "healthy")
            unhealthy_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "unhealthy")
            error_count = sum(1 for r in results if isinstance(r, Exception))

            logger.info("=" * 80)
            logger.info(
                f"Health check: External services checks completed. "
                f"Healthy: {healthy_count}, Unhealthy: {unhealthy_count}, Errors: {error_count}"
            )
            logger.info("=" * 80)

            # Log details for unhealthy services
            if unhealthy_count > 0:
                service_names = ["stripe", "sightengine", "mailjet", "bedrock", "vercel"]
                for i, result in enumerate(results):
                    if isinstance(result, dict) and result.get("status") == "unhealthy":
                        service_name = service_names[i] if i < len(service_names) else f"unknown_{i}"
                        logger.warning(
                            f"Health check: External service '{service_name}' is unhealthy. "
                            f"Last error: {result.get('last_error', 'Unknown')}"
                        )
        finally:
            # CRITICAL: Close async resources (like httpx clients) before the event loop closes
            # This prevents "Event loop is closed" errors during cleanup
            try:
                await secrets_manager.aclose()
            except Exception as cleanup_error:
                logger.warning(f"Error closing SecretsManager during external service health checks: {cleanup_error}")

    # Run async checks
    try:
        logger.info("Health check: Executing async external service health checks...")
        asyncio.run(run_checks())
        logger.info("Health check: Async external service health checks completed successfully")
    except Exception as e:
        logger.error(f"Health check: Error running external service health checks: {e}", exc_info=True)
        raise


@app.task(name="health_check.cleanup_old_events", bind=True)
def cleanup_old_health_events(self, retention_days: int = 90):
    """
    Periodic task to clean up old health events.
    
    This task removes health events older than the retention period to prevent
    unbounded database growth. Default retention is 90 days, which provides
    sufficient history for incident analysis while keeping storage manageable.
    
    Args:
        retention_days: Number of days to retain events (default 90)
    """
    logger.info("=" * 80)
    logger.info(f"Health check: Starting cleanup of health events older than {retention_days} days...")
    logger.info("=" * 80)

    async def run_cleanup():
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        
        directus = DirectusService(cache_service=CacheService())
        try:
            deleted_count = await directus.health_event.cleanup_old_events(retention_days=retention_days)
            
            if deleted_count >= 0:
                logger.info(f"Health check: Cleanup completed. Deleted {deleted_count} old health events.")
            else:
                logger.error("Health check: Cleanup failed.")
        finally:
            await directus.close()

    # Run async cleanup
    try:
        asyncio.run(run_cleanup())
    except Exception as e:
        logger.error(f"Health check: Error running health event cleanup: {e}", exc_info=True)
        raise
