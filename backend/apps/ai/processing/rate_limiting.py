# backend/apps/ai/processing/rate_limiting.py
#
# Rate limiting helpers for provider API rate limit enforcement.
# Implements rate limiting using Dragonfly cache with plan-specific configurations
# loaded from provider YAML files.

import logging
import os
import time
import asyncio
from typing import Dict, Any, Optional, Tuple

from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

# Export exception for use by callers
__all__ = ["check_rate_limit", "wait_for_rate_limit", "RateLimitScheduledException"]


def _get_provider_rate_limit(provider_id: str) -> Optional[Dict[str, Any]]:
    """
    Get rate limit configuration for a provider.
    
    Loads the provider YAML config and extracts rate limits based on the plan
    specified in environment variable (e.g., BRAVE_SEARCH_PLAN).
    
    Args:
        provider_id: The provider ID (e.g., "brave", "openai")
    
    Returns:
        Dict with rate limit configuration (requests_per_second, requests_per_month),
        or None if not found
    """
    try:
        config_manager = ConfigManager()
        provider_config = config_manager.get_provider_config(provider_id)
        
        if not provider_config:
            logger.debug(f"Provider config not found for '{provider_id}'")
            return None
        
        # Get rate limits section
        rate_limits_config = provider_config.get("rate_limits")
        if not rate_limits_config:
            logger.debug(f"No rate_limits section in provider config for '{provider_id}'")
            return None
        
        # Determine which plan to use
        # Check for provider-specific plan env var (e.g., BRAVE_SEARCH_PLAN)
        # Format: {PROVIDER_ID}_PLAN (uppercase, with underscores)
        plan_env_var = f"{provider_id.upper().replace('-', '_')}_PLAN"
        plan = os.getenv(plan_env_var, "pro").lower()  # Default to "pro" if not set
        
        # Get plan-specific rate limits
        if isinstance(rate_limits_config, dict):
            # Check if it's the new format with plan keys (free, base, pro)
            if plan in rate_limits_config:
                plan_limits = rate_limits_config[plan]
                logger.debug(f"Using '{plan}' plan rate limits for provider '{provider_id}'")
                return plan_limits
            # Fallback: check if it's the old format (direct rate_limits)
            elif "requests_per_second" in rate_limits_config:
                logger.debug(f"Using direct rate_limits for provider '{provider_id}' (no plan-specific config)")
                return rate_limits_config
        
        logger.warning(f"Rate limits config for provider '{provider_id}' is not in expected format")
        return None
        
    except Exception as e:
        logger.error(f"Error getting rate limit for provider '{provider_id}': {e}", exc_info=True)
        return None


async def check_rate_limit(
    provider_id: str,
    skill_id: str,
    model_id: Optional[str] = None,
    cache_service: Optional[CacheService] = None
) -> Tuple[bool, Optional[float]]:
    """
    Check if a provider API rate limit allows a request.
    
    Rate limits are tracked per provider, per skill, and per model (when applicable)
    using Dragonfly cache-based counters that auto-expire after the rate limit reset time.
    
    Uses a sliding window approach with 1-second granularity:
    - Tracks requests per second using cache keys with 1-second TTL
    - Checks against rate limits from provider YAML configuration
    - Loads plan-specific rate limits based on environment variable (e.g., BRAVE_SEARCH_PLAN)
    
    Args:
        provider_id: The provider ID (e.g., "brave", "openai")
        skill_id: The skill ID (e.g., "search", "generate")
        model_id: Optional model ID for model-specific rate limits
        cache_service: Optional CacheService instance (creates new one if not provided)
    
    Returns:
        Tuple of (is_allowed, retry_after_seconds)
        - is_allowed: True if request can proceed, False if rate limited
        - retry_after_seconds: Seconds to wait before retry (None if allowed)
    """
    try:
        # Get rate limit configuration from provider YAML
        rate_limit_config = _get_provider_rate_limit(provider_id)
        if not rate_limit_config:
            # If no rate limit config found, allow the request
            logger.warning(f"No rate limit configuration found for provider '{provider_id}', allowing request")
            return (True, None)
        
        requests_per_second = rate_limit_config.get("requests_per_second")
        if requests_per_second is None:
            # Unlimited rate limit
            logger.debug(f"Provider '{provider_id}' has unlimited rate limit (requests_per_second is None)")
            return (True, None)
        
        # Initialize cache service if not provided
        if cache_service is None:
            cache_service = CacheService()
        
        # Create cache key for this provider/skill/model combination
        # Key format: rate_limit:{provider_id}:{skill_id}:{model_id}:{timestamp}
        # Timestamp is current second (Unix timestamp truncated to seconds)
        current_second = int(time.time())
        
        if model_id:
            cache_key = f"rate_limit:{provider_id}:{skill_id}:{model_id}:{current_second}"
        else:
            cache_key = f"rate_limit:{provider_id}:{skill_id}:{current_second}"
        
        # Get current count for this second
        client = await cache_service.client
        if not client:
            logger.warning(f"Cache client not available for rate limit check, allowing request")
            return (True, None)
        
        # Increment counter and get new value
        # INCR creates the key with value 1 if it doesn't exist
        current_count = await client.incr(cache_key)
        
        # Set TTL to 2 seconds (current second + 1 second buffer)
        # This ensures the key exists for the full second window
        await client.expire(cache_key, 2)
        
        # Check if we've exceeded the rate limit
        if current_count > requests_per_second:
            # Calculate retry time (wait until next second)
            retry_after = 1.0 - (time.time() - current_second)
            if retry_after < 0:
                retry_after = 0.1  # Minimum 100ms wait
            
            logger.debug(
                f"Rate limit exceeded for provider '{provider_id}', skill '{skill_id}': "
                f"{current_count}/{requests_per_second} requests in current second. "
                f"Retry after {retry_after:.2f}s"
            )
            return (False, retry_after)
        
        logger.debug(
            f"Rate limit check passed for provider '{provider_id}', skill '{skill_id}': "
            f"{current_count}/{requests_per_second} requests in current second"
        )
        return (True, None)
        
    except Exception as e:
        logger.error(f"Error checking rate limit for provider '{provider_id}', skill '{skill_id}': {e}", exc_info=True)
        # On error, allow the request (fail open) but log the error
        return (True, None)


async def wait_for_rate_limit(
    provider_id: str,
    skill_id: str,
    model_id: Optional[str] = None,
    cache_service: Optional[CacheService] = None,
    celery_producer: Optional[Any] = None,
    celery_task_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Wait for a rate limit to reset before proceeding.
    
    Hybrid approach for optimal performance and scalability:
    - Short waits (< 2s): Direct optimized sleep (no polling, minimal overhead)
    - Long waits (>= 2s): Celery task scheduling (non-blocking, frees worker threads)
    
    According to app_skills.md architecture: "Requests are never rejected due to rate limits.
    Instead, they're queued and processed when limits allow."
    
    Args:
        provider_id: The provider ID
        skill_id: The skill ID
        model_id: Optional model ID
        cache_service: Optional CacheService instance (creates new one if not provided)
        celery_producer: Optional Celery instance for scheduling long waits
        celery_task_context: Optional dict with 'app_id', 'skill_id', 'arguments' for Celery scheduling
    """
    # Get initial rate limit check to determine wait time
    is_allowed, retry_after = await check_rate_limit(
        provider_id=provider_id,
        skill_id=skill_id,
        model_id=model_id,
        cache_service=cache_service
    )
    
    if is_allowed:
        return  # No wait needed
    
    if not retry_after or retry_after <= 0:
        retry_after = 0.1  # Default minimum wait
    
    # Hybrid approach: short waits use direct sleep, long waits use Celery
    CELERY_THRESHOLD = 2.0  # Use Celery for waits >= 2 seconds
    
    if retry_after < CELERY_THRESHOLD:
        # Short wait: Direct optimized sleep (no polling needed)
        # Since rate limits reset every second, we can sleep directly to the retry time
        logger.debug(
            f"Rate limit wait for provider '{provider_id}', skill '{skill_id}': "
            f"short wait ({retry_after:.2f}s), using direct sleep"
        )
        await asyncio.sleep(retry_after)
        
        # Single final check after sleep
        is_allowed, _ = await check_rate_limit(
            provider_id=provider_id,
            skill_id=skill_id,
            model_id=model_id,
            cache_service=cache_service
        )
        if not is_allowed:
            logger.warning(
                f"Rate limit still active for provider '{provider_id}', skill '{skill_id}' "
                f"after {retry_after:.2f}s wait, proceeding anyway"
            )
        return
    
    # Long wait: Use Celery scheduling if available, otherwise fall back to optimized polling
    if celery_producer and celery_task_context:
        # Schedule via Celery for non-blocking execution
        app_id = celery_task_context.get("app_id")
        skill_id_for_celery = celery_task_context.get("skill_id")
        arguments = celery_task_context.get("arguments")
        chat_id = celery_task_context.get("chat_id")
        message_id = celery_task_context.get("message_id")
        
        if app_id and skill_id_for_celery and arguments is not None:
            try:
                from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery
                
                # Schedule the skill execution with countdown
                countdown_seconds = int(retry_after) + 1  # Round up to next second
                task_name = f"apps.{app_id}.tasks.skill_{skill_id_for_celery}"
                queue_name = f"app_{app_id}"
                
                # Include chat context in task arguments for followup processing
                task_kwargs = {
                    "arguments": arguments
                }
                if chat_id:
                    task_kwargs["_chat_id"] = chat_id
                if message_id:
                    task_kwargs["_message_id"] = message_id
                
                # Chain a followup task that will process results and send followup message
                # when the skill task completes
                from celery import chain
                from backend.apps.ai.tasks.rate_limit_followup_task import process_rate_limit_followup_task
                
                # Create the skill task
                skill_task = celery_producer.signature(
                    task_name,
                    kwargs=task_kwargs,
                    queue=queue_name,
                    countdown=countdown_seconds
                )
                
                # Create the followup task (runs after skill task completes)
                # Note: In Celery chains, the followup task receives the skill task result as first argument
                # So we need to use .s() with the result as first arg, then other args
                followup_task = process_rate_limit_followup_task.s(
                    app_id=app_id,
                    skill_id=skill_id_for_celery,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=None,  # TODO: Get from context if available
                    user_id_hash=None  # TODO: Get from context if available
                )
                
                # Chain tasks: skill_task -> followup_task
                # The followup task will receive skill_result as first argument automatically
                task_chain = chain(skill_task, followup_task)
                result = task_chain.apply_async()
                
                # Get the skill task ID (first task in chain)
                skill_task_id = skill_task.id
                
                logger.info(
                    f"Rate limit wait for provider '{provider_id}', skill '{skill_id}': "
                    f"long wait ({retry_after:.2f}s), scheduled Celery task chain with skill task {skill_task_id} "
                    f"and followup task, countdown={countdown_seconds}s"
                )
                
                # Raise a special exception to indicate task was scheduled
                # The caller should handle this appropriately
                raise RateLimitScheduledException(
                    task_id=skill_task_id,
                    wait_time=retry_after,
                    message=f"Skill execution scheduled via Celery due to rate limit"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to schedule Celery task for rate-limited request: {e}. "
                    f"Falling back to direct wait."
                )
                # Fall through to direct wait
    
    # Fallback: Optimized direct wait for long periods (if Celery not available)
    # Use single sleep to next second boundary, then check once
    logger.info(
        f"Rate limit wait for provider '{provider_id}', skill '{skill_id}': "
        f"long wait ({retry_after:.2f}s), using optimized direct wait"
    )
    
    # Sleep to the next second boundary (rate limits reset per second)
    wait_until_next_second = retry_after
    await asyncio.sleep(wait_until_next_second)
    
    # Single final check
    is_allowed, _ = await check_rate_limit(
        provider_id=provider_id,
        skill_id=skill_id,
        model_id=model_id,
        cache_service=cache_service
    )
    if not is_allowed:
        logger.warning(
            f"Rate limit still active for provider '{provider_id}', skill '{skill_id}' "
            f"after {retry_after:.2f}s wait, proceeding anyway"
        )


class RateLimitScheduledException(Exception):
    """
    Exception raised when a rate-limited request is scheduled via Celery.
    
    This allows callers to handle scheduled tasks differently from immediate execution.
    """
    def __init__(self, task_id: str, wait_time: float, message: str):
        self.task_id = task_id
        self.wait_time = wait_time
        self.message = message
        super().__init__(self.message)

