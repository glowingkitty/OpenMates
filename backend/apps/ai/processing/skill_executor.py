# backend/apps/ai/processing/skill_executor.py
#
# Skill execution service for handling app skill execution from function calls.
# This module handles routing skill execution requests to the correct app services
# and managing parallel execution of multiple requests.
#
# Helper functions are split into separate modules for better separation of concerns:
# - rate_limiting.py: Provider API rate limit enforcement
# - celery_helpers.py: Celery task execution for long-running skills
# - content_sanitization.py: Prompt injection protection for external data
#
# SKILL CANCELLATION:
# Each skill invocation gets a unique skill_task_id. Users can cancel individual
# skills without cancelling the entire AI response. Cancelled skill_task_ids are
# stored in Redis and checked before/during execution. When a skill is cancelled,
# the main processor continues with empty results.
#
# RETRY LOGIC:
# Skills are executed with retry logic to handle transient failures (network timeouts,
# proxy IP issues, etc.). Default is 20s timeout with 1 retry attempt. On retry,
# external services like YouTube may route through a different proxy IP.

import logging
import uuid
import asyncio
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Default timeout for skill execution (in seconds)
# Reduced from 30s to 20s to fail faster and allow retry with different proxy IP
DEFAULT_SKILL_TIMEOUT = 20.0

# Default number of retry attempts for skill execution
# 1 retry = 2 total attempts (initial + 1 retry)
DEFAULT_SKILL_MAX_RETRIES = 1

# Delay between retry attempts (in seconds)
# Short delay to allow proxy rotation but not delay user too much
RETRY_DELAY_SECONDS = 1.0

# Redis key prefix for cancelled skill tasks
CANCELLED_SKILLS_KEY_PREFIX = "cancelled_skill:"
# TTL for cancelled skill entries (1 hour - skills should complete well before this)
CANCELLED_SKILL_TTL = 3600

# Import helper modules
from backend.apps.ai.processing.rate_limiting import (
    check_rate_limit,
    wait_for_rate_limit,
    RateLimitScheduledException
)
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery, get_celery_task_status
from backend.apps.ai.processing.content_sanitization import sanitize_external_content

# Re-export helper functions and exceptions for backward compatibility
# TODO(audit-2026-03-19): Move check_rate_limit, wait_for_rate_limit, sanitize_external_content, execute_skill_via_celery
# to backend/shared/python_utils/skill_utils.py — 9+ non-AI skill apps import from here, violating module boundaries.
__all__ = [
    "execute_skill",
    "execute_skill_with_multiple_requests",
    "check_rate_limit",
    "wait_for_rate_limit",
    "execute_skill_via_celery",
    "get_celery_task_status",
    "sanitize_external_content",
    "RateLimitScheduledException",
    # Skill cancellation functions
    "generate_skill_task_id",
    "cancel_skill_task",
    "is_skill_cancelled",
    "SkillCancelledException",
    # Timeout and retry configuration
    "DEFAULT_SKILL_TIMEOUT",
    "DEFAULT_SKILL_MAX_RETRIES"
]


class SkillCancelledException(Exception):
    """
    Exception raised when a skill is cancelled by the user.
    The main processor should catch this and continue with empty results.
    """
    def __init__(self, skill_task_id: str, app_id: str, skill_id: str):
        self.skill_task_id = skill_task_id
        self.app_id = app_id
        self.skill_id = skill_id
        super().__init__(f"Skill {app_id}.{skill_id} (task_id={skill_task_id}) was cancelled by user")


def generate_skill_task_id() -> str:
    """
    Generate a unique task ID for a skill invocation.
    This ID is used to track and cancel individual skill executions.
    
    Returns:
        A unique skill_task_id string (UUID format)
    """
    return str(uuid.uuid4())


async def cancel_skill_task(cache_service: Any, skill_task_id: str) -> bool:
    """
    Mark a skill task as cancelled in Redis.
    The skill executor will check this before/during execution.
    
    Args:
        cache_service: The cache service for Redis operations
        skill_task_id: The unique skill task ID to cancel
        
    Returns:
        True if successfully marked as cancelled, False otherwise
    """
    if not cache_service or not skill_task_id:
        logger.warning("Cannot cancel skill task: missing cache_service or skill_task_id")
        return False
    
    try:
        client = await cache_service.client
        if client:
            key = f"{CANCELLED_SKILLS_KEY_PREFIX}{skill_task_id}"
            # Set the cancellation flag with TTL
            await client.setex(key, CANCELLED_SKILL_TTL, "cancelled")
            logger.info(f"[SkillCancellation] Marked skill_task_id {skill_task_id} as cancelled")
            return True
        else:
            logger.error("[SkillCancellation] Redis client not available")
            return False
    except Exception as e:
        logger.error(f"[SkillCancellation] Error cancelling skill {skill_task_id}: {e}", exc_info=True)
        return False


async def is_skill_cancelled(cache_service: Any, skill_task_id: str) -> bool:
    """
    Check if a skill task has been cancelled.
    
    Args:
        cache_service: The cache service for Redis operations
        skill_task_id: The unique skill task ID to check
        
    Returns:
        True if the skill was cancelled, False otherwise
    """
    if not cache_service or not skill_task_id:
        return False
    
    try:
        client = await cache_service.client
        if client:
            key = f"{CANCELLED_SKILLS_KEY_PREFIX}{skill_task_id}"
            result = await client.get(key)
            return result is not None
        return False
    except Exception as e:
        logger.debug(f"[SkillCancellation] Error checking cancellation for {skill_task_id}: {e}")
        return False

# Default port for app services
DEFAULT_APP_INTERNAL_PORT = 8000

# Maximum number of parallel requests per skill call
MAX_PARALLEL_REQUESTS = 5


async def execute_skill(
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    timeout: float = DEFAULT_SKILL_TIMEOUT,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    skill_task_id: Optional[str] = None,
    cache_service: Optional[Any] = None,
    max_retries: int = DEFAULT_SKILL_MAX_RETRIES
) -> Dict[str, Any]:
    """
    Execute a skill in-process via the SkillRegistry, with retry logic for
    transient skill-side failures (external API timeouts, proxy IP issues,
    network errors raised from inside the skill).

    Pre-OPE-342 this used to HTTP-POST to ``http://app-{id}:8000/skills/{skill_id}``.
    Now the worker process loads its own SkillRegistry at worker_process_init
    and dispatches directly via Python method calls — no inter-container HTTP,
    no JSON serialization overhead, one coherent OTel trace per AI request.

    The ``timeout`` parameter is honored via ``asyncio.wait_for`` around the
    in-process call so a runaway skill cannot block the worker indefinitely.

    Retries still help because most "skill failure" cases are external (the
    skill itself opens HTTP/SSL connections to YouTube, REWE, etc.). On retry,
    those external services may route through a different proxy IP.

    Args:
        app_id: The ID of the app that owns the skill
        skill_id: The ID of the skill to execute
        arguments: The arguments to pass to the skill (from function call)
        timeout: Per-attempt timeout in seconds (default: 20s)
        chat_id: Optional chat ID for linking usage entries to chat sessions
        message_id: Optional message ID for linking usage entries to messages
        user_id: Optional user ID for skills that require user context
        skill_task_id: Optional unique ID for this skill invocation (cancellation)
        cache_service: Optional cache service for checking cancellation status
        max_retries: Maximum number of retry attempts (default: 1 = 2 total attempts)

    Returns:
        Dict containing the skill execution result.

    Raises:
        SkillCancelledException: If the skill was cancelled by the user.
        HTTPException: 4xx errors from the skill (validation, missing skill,
            billing 402) are NOT retried — re-raised immediately.
        Exception: For other errors after all retries exhausted.
    """
    from fastapi import HTTPException
    from backend.core.api.app.services.skill_registry import get_global_registry

    # Check cancellation before starting
    if skill_task_id and cache_service:
        if await is_skill_cancelled(cache_service, skill_task_id):
            logger.info(f"[SkillCancellation] Skill '{app_id}.{skill_id}' (task_id={skill_task_id}) cancelled before execution")
            raise SkillCancelledException(skill_task_id, app_id, skill_id)

    # Build the request body — same shape the old HTTP path used
    request_body = arguments.copy()
    if chat_id:
        request_body["_chat_id"] = chat_id
    if message_id:
        request_body["_message_id"] = message_id
    if user_id:
        request_body["_user_id"] = user_id

    registry = get_global_registry()
    if not registry.has_app(app_id):
        # Worker registry didn't load this app — almost certainly an init bug.
        # Don't retry; raise loudly so the caller surfaces the misconfiguration.
        logger.error(
            f"In-process skill registry has no app '{app_id}'. "
            f"Worker init may have failed — check celery worker_process_init logs."
        )
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not registered in worker skill registry")

    logger.debug(f"Executing skill '{app_id}.{skill_id}' in-process with arguments: {list(arguments.keys())}")

    last_exception: Optional[Exception] = None
    total_attempts = max_retries + 1

    for attempt in range(total_attempts):
        # Check cancellation before each retry
        if attempt > 0 and skill_task_id and cache_service:
            if await is_skill_cancelled(cache_service, skill_task_id):
                logger.info(f"[SkillCancellation] Skill '{app_id}.{skill_id}' (task_id={skill_task_id}) cancelled before retry attempt {attempt + 1}")
                raise SkillCancelledException(skill_task_id, app_id, skill_id)

        try:
            if attempt > 0:
                logger.info(
                    f"[SkillRetry] Retrying skill '{app_id}.{skill_id}' (attempt {attempt + 1}/{total_attempts}) "
                    f"after {type(last_exception).__name__}"
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)

            # In-process dispatch with a hard per-attempt timeout so a hung
            # skill (e.g. external API not responding) can't block forever.
            result = await asyncio.wait_for(
                registry.dispatch_skill(app_id, skill_id, request_body),
                timeout=timeout,
            )

            # Check cancellation post-execution
            if skill_task_id and cache_service:
                if await is_skill_cancelled(cache_service, skill_task_id):
                    logger.info(f"[SkillCancellation] Skill '{app_id}.{skill_id}' (task_id={skill_task_id}) cancelled after execution")
                    raise SkillCancelledException(skill_task_id, app_id, skill_id)

            if not isinstance(result, dict):
                # Defensive: skills should always return a dict (or Pydantic model
                # converted to one by BaseApp._dispatch_skill_with_class). Wrap
                # anything else so downstream JSON serialization doesn't crash.
                result = {"content": result}

            if attempt > 0:
                logger.info(f"[SkillRetry] Skill '{app_id}.{skill_id}' succeeded on retry attempt {attempt + 1}/{total_attempts}")
            else:
                logger.debug(f"Skill '{app_id}.{skill_id}' executed successfully")
            return result

        except SkillCancelledException:
            raise
        except HTTPException as e:
            # 4xx errors are deterministic — don't retry. 5xx might be transient.
            if e.status_code < 500:
                logger.error(f"Skill '{app_id}.{skill_id}' raised HTTPException {e.status_code}: {e.detail}")
                raise
            last_exception = e
            logger.warning(
                f"[SkillRetry] Skill '{app_id}.{skill_id}' raised HTTP {e.status_code} "
                f"(attempt {attempt + 1}/{total_attempts}): {e.detail}"
            )
        except asyncio.TimeoutError as e:
            last_exception = e
            logger.warning(
                f"[SkillRetry] Skill '{app_id}.{skill_id}' timed out after {timeout}s "
                f"(attempt {attempt + 1}/{total_attempts})"
            )
        except Exception as e:
            last_exception = e
            logger.warning(
                f"[SkillRetry] Skill '{app_id}.{skill_id}' raised {type(e).__name__} "
                f"(attempt {attempt + 1}/{total_attempts}): {e}"
            )

    logger.error(
        f"Skill '{app_id}.{skill_id}' failed after {total_attempts} attempts. "
        f"Last error: {type(last_exception).__name__}"
    )
    if last_exception:
        raise last_exception
    raise RuntimeError(f"Skill '{app_id}.{skill_id}' failed after {total_attempts} attempts")


async def execute_skill_with_multiple_requests(
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    timeout: float = DEFAULT_SKILL_TIMEOUT,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    skill_task_id: Optional[str] = None,
    cache_service: Optional[Any] = None,
    max_retries: int = DEFAULT_SKILL_MAX_RETRIES
) -> List[Dict[str, Any]]:
    """
    Executes a skill with support for multiple parallel requests and retry logic.
    
    This function checks if the arguments contain a list of requests (e.g., multiple search queries)
    and processes them in parallel (up to MAX_PARALLEL_REQUESTS).
    
    Includes retry logic for handling transient failures (timeouts, network errors).
    
    Args:
        app_id: The ID of the app that owns the skill
        skill_id: The ID of the skill to execute
        arguments: The arguments to pass to the skill
                   If it contains a list-like structure, multiple requests will be created
        timeout: Request timeout in seconds per request (default: 20s)
        chat_id: Optional chat ID for linking usage entries to chat sessions
        message_id: Optional message ID for linking usage entries to messages
        user_id: Optional user ID for skills that require user context (e.g., reminders)
        skill_task_id: Optional unique ID for this skill invocation (for cancellation)
        cache_service: Optional cache service for checking cancellation status
        max_retries: Maximum number of retry attempts (default: 1)
    
    Returns:
        List of results from skill execution (one per request)
        
    Raises:
        SkillCancelledException: If the skill was cancelled by the user
    """
    # Extract metadata fields from arguments if present (they might have been added by caller)
    # Don't modify the original arguments dict - create a copy for processing
    extracted_chat_id = arguments.get("_chat_id") or chat_id
    extracted_message_id = arguments.get("_message_id") or message_id
    extracted_user_id = arguments.get("_user_id") or user_id
    
    # Check if arguments contain multiple requests in the standard "requests" array format
    # Skills that support multiple requests expect them in a single call with {"requests": [...]}
    # The skill's execute() method handles parallel processing internally
    if "requests" in arguments and isinstance(arguments["requests"], list):
        requests_list = arguments["requests"]
        if len(requests_list) > 1:
            # Multiple requests in standard format - make ONE call with all requests
            # The skill will process them in parallel internally
            # Limit to MAX_PARALLEL_REQUESTS
            if len(requests_list) > MAX_PARALLEL_REQUESTS:
                logger.warning(
                    f"Skill '{app_id}.{skill_id}' has {len(requests_list)} requests, "
                    f"limiting to {MAX_PARALLEL_REQUESTS} parallel requests"
                )
                # Create a copy of arguments with limited requests
                limited_arguments = arguments.copy()
                limited_arguments["requests"] = requests_list[:MAX_PARALLEL_REQUESTS]
                arguments = limited_arguments
            
            logger.info(f"Executing skill '{app_id}.{skill_id}' with {len(arguments['requests'])} requests in a single call")
            # Make ONE call to the skill with all requests - the skill handles parallel processing
            result = await execute_skill(
                app_id, skill_id, arguments, timeout, 
                extracted_chat_id, extracted_message_id, extracted_user_id,
                skill_task_id, cache_service, max_retries
            )
            # Skills return a response with a "results" array - return as list for consistency
            return [result]
        elif len(requests_list) == 1:
            # Single request in array format - execute normally
            result = await execute_skill(
                app_id, skill_id, arguments, timeout, 
                extracted_chat_id, extracted_message_id, extracted_user_id,
                skill_task_id, cache_service, max_retries
            )
            return [result]
        else:
            # Empty requests array
            return [{"error": "Empty requests array"}]
    
    # Check for legacy pattern: a parameter with a list of values
    # Example: {"query": ["search1", "search2", "search3"]}
    # This is for backward compatibility - convert to standard format
    multiple_requests = _extract_multiple_requests(arguments)
    
    if multiple_requests and len(multiple_requests) > 1:
        # Legacy pattern detected - convert to standard "requests" array format
        # Limit to MAX_PARALLEL_REQUESTS
        if len(multiple_requests) > MAX_PARALLEL_REQUESTS:
            logger.warning(
                f"Skill '{app_id}.{skill_id}' has {len(multiple_requests)} requests (legacy format), "
                f"limiting to {MAX_PARALLEL_REQUESTS} parallel requests"
            )
            multiple_requests = multiple_requests[:MAX_PARALLEL_REQUESTS]
        
        # Convert to standard format: {"requests": [...]}
        standard_arguments = {"requests": multiple_requests}
        logger.info(f"Executing skill '{app_id}.{skill_id}' with {len(multiple_requests)} requests in a single call (converted from legacy format)")
        # Make ONE call to the skill with all requests
        result = await execute_skill(
            app_id, skill_id, standard_arguments, timeout, 
            extracted_chat_id, extracted_message_id, extracted_user_id,
            skill_task_id, cache_service, max_retries
        )
        return [result]
    
    # Single request - execute normally
    result = await execute_skill(
        app_id, skill_id, arguments, timeout, 
        extracted_chat_id, extracted_message_id, extracted_user_id,
        skill_task_id, cache_service, max_retries
    )
    return [result]


def _extract_multiple_requests(arguments: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    Extracts multiple requests from skill arguments.
    
    According to REST API architecture (docs/architecture/rest_api.md), skills accept
    a "requests" array format:
    {
      "requests": [
        {"query": "search1"},
        {"query": "search2"}
      ]
    }
    
    This function also supports legacy patterns where a parameter contains a list of values.
    
    Args:
        arguments: The skill arguments
    
    Returns:
        List of argument dicts for multiple requests, or None if single request
    """
    # Primary pattern: "requests" array (REST API standard format)
    # See docs/architecture/rest_api.md for the standard format
    if "requests" in arguments and isinstance(arguments["requests"], list):
        requests_list = arguments["requests"]
        if len(requests_list) > 1:
            # Each item in the requests array is a separate request
            # Remove "requests" key and use each item as a separate request
            return requests_list
        elif len(requests_list) == 1:
            # Single request in array format - extract it
            return [requests_list[0]]
        else:
            # Empty requests array
            return None
    
    # Legacy pattern: a parameter with a list of values
    # Example: {"query": ["search1", "search2", "search3"]}
    # This is for backward compatibility and LLM function calling
    for key, value in arguments.items():
        if isinstance(value, list) and len(value) > 1:
            # Create multiple requests, one per list item
            requests = []
            for item in value:
                request_args = arguments.copy()
                request_args[key] = item
                requests.append(request_args)
            return requests
    
    # If no multiple requests pattern found, return None to indicate single request
    return None



