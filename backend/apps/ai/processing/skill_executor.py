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

import logging
import json
from typing import Dict, Any, List, Optional
import httpx
import asyncio

logger = logging.getLogger(__name__)

# Import helper modules
from backend.apps.ai.processing.rate_limiting import (
    check_rate_limit,
    wait_for_rate_limit,
    RateLimitScheduledException
)
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery, get_celery_task_status
from backend.apps.ai.processing.content_sanitization import sanitize_external_content

# Re-export helper functions and exceptions for backward compatibility
__all__ = [
    "execute_skill",
    "execute_skill_with_multiple_requests",
    "check_rate_limit",
    "wait_for_rate_limit",
    "execute_skill_via_celery",
    "get_celery_task_status",
    "sanitize_external_content",
    "RateLimitScheduledException"
]

# Default port for app services
DEFAULT_APP_INTERNAL_PORT = 8000

# Maximum number of parallel requests per skill call
MAX_PARALLEL_REQUESTS = 5


async def execute_skill(
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    timeout: float = 30.0,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a skill by routing to the correct app service.
    
    Args:
        app_id: The ID of the app that owns the skill
        skill_id: The ID of the skill to execute
        arguments: The arguments to pass to the skill (from function call)
        timeout: Request timeout in seconds
        chat_id: Optional chat ID for linking usage entries to chat sessions
        message_id: Optional message ID for linking usage entries to messages
    
    Returns:
        Dict containing the skill execution result
    
    Raises:
        httpx.HTTPStatusError: If the skill execution fails with an HTTP error
        httpx.RequestError: If there's a network error
        Exception: For other errors
    """
    # Construct the skill endpoint URL
    # BaseApp registers routes as /skills/{skill_id}
    skill_url = f"http://app-{app_id}:{DEFAULT_APP_INTERNAL_PORT}/skills/{skill_id}"
    
    # Include chat_id and message_id in the request body as metadata
    # Skills can extract these to use when recording usage
    request_body = arguments.copy()
    if chat_id:
        request_body["_chat_id"] = chat_id  # Prefix with _ to indicate metadata
    if message_id:
        request_body["_message_id"] = message_id  # Prefix with _ to indicate metadata
    
    logger.debug(f"Executing skill '{app_id}.{skill_id}' at {skill_url} with arguments: {list(arguments.keys())}")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                skill_url,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            # Try to parse as JSON, fallback to text
            try:
                result = response.json()
            except json.JSONDecodeError:
                result = {"content": response.text}
            
            logger.debug(f"Skill '{app_id}.{skill_id}' executed successfully")
            return result
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error executing skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        logger.error(f"Request error executing skill '{app_id}.{skill_id}': {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error executing skill '{app_id}.{skill_id}': {e}", exc_info=True)
        raise


async def execute_skill_with_multiple_requests(
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    timeout: float = 30.0,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes a skill with support for multiple parallel requests.
    
    This function checks if the arguments contain a list of requests (e.g., multiple search queries)
    and processes them in parallel (up to MAX_PARALLEL_REQUESTS).
    
    Args:
        app_id: The ID of the app that owns the skill
        skill_id: The ID of the skill to execute
        arguments: The arguments to pass to the skill
                   If it contains a list-like structure, multiple requests will be created
        timeout: Request timeout in seconds per request
        chat_id: Optional chat ID for linking usage entries to chat sessions
        message_id: Optional message ID for linking usage entries to messages
    
    Returns:
        List of results from skill execution (one per request)
    """
    # Extract metadata fields from arguments if present (they might have been added by caller)
    # Don't modify the original arguments dict - create a copy for processing
    extracted_chat_id = arguments.get("_chat_id") or chat_id
    extracted_message_id = arguments.get("_message_id") or message_id
    
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
            result = await execute_skill(app_id, skill_id, arguments, timeout, extracted_chat_id, extracted_message_id)
            # Skills return a response with a "results" array - return as list for consistency
            return [result]
        elif len(requests_list) == 1:
            # Single request in array format - execute normally
            result = await execute_skill(app_id, skill_id, arguments, timeout, extracted_chat_id, extracted_message_id)
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
        result = await execute_skill(app_id, skill_id, standard_arguments, timeout, extracted_chat_id, extracted_message_id)
        return [result]
    
    # Single request - execute normally
    result = await execute_skill(app_id, skill_id, arguments, timeout, extracted_chat_id, extracted_message_id)
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



