# backend/apps/ai/processing/main_processor.py
# Handles the main processing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import json
import httpx
import datetime
import zoneinfo
import os
import copy
import hashlib
from toon_format import encode

# Import Pydantic models for type hinting
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.utils.llm_utils import (
    call_main_llm_stream,
    truncate_message_history_to_token_budget,
    AllServersFailedError,
    STANDARDIZED_USER_ERROR_MESSAGE,
)
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.core.api.app.utils.override_parser import UserOverrides
from backend.apps.ai.llm_providers.mistral_client import ParsedMistralToolCall, MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata, ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import ParsedAnthropicToolCall, AnthropicUsageMetadata
from backend.apps.ai.llm_providers.bedrock_shared import ParsedBedrockToolCall, BedrockUsageMetadata
from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
from backend.apps.ai.llm_providers.types import UnifiedStreamChunk, StreamChunkType
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.translations import TranslationService

# Import tool generator
from backend.apps.ai.processing.tool_generator import generate_tools_from_apps
# Import skill executor
from backend.apps.ai.processing.skill_executor import (
    execute_skill_with_multiple_requests,
    SkillCancelledException,
    generate_skill_task_id,
    DEFAULT_SKILL_TIMEOUT
)
# Import billing utilities
from backend.shared.python_utils.billing_utils import calculate_total_credits, MINIMUM_CREDITS_CHARGED


logger = logging.getLogger(__name__)

# Max iterations for tool calling to prevent infinite loops
MAX_TOOL_CALL_ITERATIONS = 5

# === SKILL CALL BUDGET LIMITS ===
# These limits prevent runaway research loops where the AI keeps requesting more and more searches.
# Each "skill call" is counted per-request (e.g., a tool call with 3 requests counts as 3 skill calls).
#
# SOFT_LIMIT_SKILL_CALLS: When this limit is reached, inject a budget warning into the next LLM call,
# instructing the AI to finish with gathered information or ask the user for follow-up.
SOFT_LIMIT_SKILL_CALLS = 3
#
# HARD_LIMIT_SKILL_CALLS: When this limit is reached, stop executing further skills entirely.
# Force the LLM to answer with gathered information by setting tool_choice="none".
# Maximum of 5 request attempts per assistant message to prevent excessive research loops.
HARD_LIMIT_SKILL_CALLS = 5


def _hash_skill_arguments(app_id: str, skill_id: str, arguments: Dict[str, Any]) -> str:
    """
    Create a deterministic hash of skill arguments for deduplication.
    
    This prevents the same skill from being executed multiple times with identical
    arguments within a single AI response. This commonly happens when LLMs
    (especially Gemini) repeatedly call the same tool across iterations even after
    receiving a successful result.
    
    The hash is computed from (app_id, skill_id, sorted_json_arguments).
    Same skill with different arguments will have different hashes and execute normally.
    
    Args:
        app_id: The app identifier (e.g., 'reminder')
        skill_id: The skill identifier (e.g., 'set-reminder')
        arguments: The parsed arguments dict from the tool call
        
    Returns:
        MD5 hash string for deduplication lookup
    """
    # Sort keys for deterministic hashing regardless of JSON key order
    args_str = json.dumps(arguments, sort_keys=True, default=str)
    hash_input = f"{app_id}:{skill_id}:{args_str}"
    return hashlib.md5(hash_input.encode()).hexdigest()


def _flatten_for_toon_tabular(obj: Any, prefix: str = "") -> Any:
    """
    Flatten nested objects into primitive fields for TOON tabular format encoding.
    
    This function matches the proven working approach from toon_encoding_test.ipynb.
    TOON tabular format requires uniform objects with only primitive fields (no nested objects or arrays).
    This function converts nested structures to flat primitive fields:
    - profile: { name: "..." } → profile_name: "..."
    - meta_url: { favicon: "..." } → meta_url_favicon: "..."
- thumbnail: { original: "..." } → thumbnail_original: "..."
    - extra_snippets: [...] → extra_snippets: "|".join([...]) (pipe-delimited string)
    
    This enables TOON to use efficient tabular format like:
    results[10]{type,title,url,description,page_age,profile_name,meta_url_favicon,thumbnail_original,extra_snippets,hash}:
      search_result,Title 1,url1,desc1,age1,name1,favicon1,thumb1,snippets1,hash1
      search_result,Title 2,url2,desc2,age2,name2,favicon2,thumb2,snippets2,hash2
    
    Instead of repeating field names for each result (which wastes tokens).
    This approach saves 25-32% in token usage compared to nested JSON format.
    
    Args:
        obj: Object to flatten (dict, list, or primitive)
        prefix: Prefix for flattened field names (used for recursion)
    
    Returns:
        Flattened object with only primitive fields
    """
    if isinstance(obj, dict):
        flattened = {}
        for key, value in obj.items():
            # Build the new key with prefix if provided
            new_key = f"{prefix}_{key}" if prefix else key
            
            if isinstance(value, dict):
                # Recursively flatten nested dictionaries
                # This handles cases like profile: {name: "..."} → profile_name: "..."
                flattened.update(_flatten_for_toon_tabular(value, new_key))
            elif isinstance(value, list):
                # Handle lists - different strategies based on content type
                if not value:
                    # Empty list - store as empty string
                    flattened[new_key] = ""
                elif all(isinstance(v, (str, int, float, bool, type(None))) for v in value):
                    # List of primitives - join with pipe delimiter
                    # None values are converted to empty strings in the pipe-delimited format
                    flattened[new_key] = "|".join(str(v) if v is not None else "" for v in value)
                elif all(isinstance(v, dict) for v in value):
                    # List of dictionaries - flatten each dictionary individually
                    # This is CRITICAL: flatten each dict so TOON can use tabular format
                    # Store as a list of flattened dicts (TOON will encode this as tabular array)
                    flattened_list = [_flatten_for_toon_tabular(item, "") for item in value]
                    flattened[new_key] = flattened_list
                else:
                    # Mixed list or list with non-dict complex objects - convert to JSON string (fallback)
                    # This should be rare, but handles edge cases where list contains objects
                    flattened[new_key] = json.dumps(value)
            else:
                # Primitive value (str, int, float, bool, None) - keep as-is
                # TOON format will handle None values appropriately (as null)
                flattened[new_key] = value
        return flattened
    elif isinstance(obj, list):
        # If we get a list at the top level, flatten each item
        return [_flatten_for_toon_tabular(item, prefix) for item in obj]
    else:
        # Primitive value - return as-is
        return obj


def _filter_skill_results_for_llm(
    results: List[Dict[str, Any]],
    exclude_fields: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """
    Filter skill results to remove fields not relevant for LLM inference.
    
    Removes fields specified in exclude_fields_for_llm from app.yml.
    Supports dot notation for nested fields (e.g., "meta_url.favicon", "thumbnail.original").
    
    CRITICAL: This function preserves essential fields that MUST be included in LLM inference:
    - url: Required for LLM to reference sources
    - page_age: Required for LLM to understand result freshness
    - profile.name: Required for LLM to identify source credibility
    
    Full results with all fields are stored in chat history for persistence.
    This filtered version is only used for the current LLM call to reduce token usage.
    
    Args:
        results: List of skill result dictionaries
        exclude_fields: List of field paths to exclude (supports dot notation for nested fields)
    
    Returns:
        Filtered list of results with excluded fields removed (but essential fields preserved)
    """
    if not exclude_fields:
        # No fields to exclude, return results as-is
        return results
    
    # Essential fields that MUST be preserved for LLM inference
    # These fields are critical for the LLM to understand and reference search results
    ESSENTIAL_FIELDS = {"url", "page_age", "profile.name"}
    
    filtered = []
    
    def remove_field_path(obj: Dict[str, Any], field_path: str) -> None:
        """
        Remove a field from an object using dot notation path.
        Handles nested dictionaries (e.g., "meta_url.favicon").
        
        CRITICAL: Never removes essential fields (url, page_age, profile.name).
        """
        # Check if this is an essential field - if so, skip removal
        if field_path in ESSENTIAL_FIELDS:
            logger.debug(f"Skipping removal of essential field '{field_path}' - required for LLM inference")
            return
        
        # Check if this is a nested essential field (e.g., "profile.name")
        if field_path.startswith("profile.") and "profile.name" in ESSENTIAL_FIELDS:
            # Don't remove profile.name even if profile.* is being filtered
            if field_path == "profile.name":
                logger.debug(f"Skipping removal of essential field '{field_path}' - required for LLM inference")
                return
        
        parts = field_path.split('.', 1)
        if len(parts) == 1:
            # Simple field - remove directly (but not if it's essential)
            if parts[0] not in ESSENTIAL_FIELDS:
                obj.pop(parts[0], None)
        else:
            # Nested field - navigate to parent and remove child
            parent_key, child_path = parts
            if parent_key in obj and isinstance(obj[parent_key], dict):
                # Special handling for profile.name - preserve it even if filtering profile
                if parent_key == "profile" and child_path == "name":
                    logger.debug("Preserving essential field 'profile.name' - required for LLM inference")
                    return
                remove_field_path(obj[parent_key], child_path)
                # If parent dict is now empty, remove it
                if not obj[parent_key]:
                    obj.pop(parent_key, None)
    
    for result in results:
        # CRITICAL: Use deepcopy to avoid modifying original results when removing nested fields
        # Shallow copy() shares nested dict references, so remove_field_path would corrupt originals
        filtered_result = copy.deepcopy(result)
        
        # Handle both single result dict and result dict with "previews" array
        if "previews" in filtered_result:
            # Result has a "previews" array - filter each preview
            filtered_previews = []
            for preview in filtered_result.get("previews", []):
                # Use deepcopy for nested dicts to avoid corrupting original previews
                filtered_preview = copy.deepcopy(preview)
                
                # Remove each excluded field (but preserve essential fields)
                for field_path in exclude_fields:
                    remove_field_path(filtered_preview, field_path)
                
                filtered_previews.append(filtered_preview)
            
            filtered_result["previews"] = filtered_previews
        else:
            # Direct result object - filter it directly (but preserve essential fields)
            for field_path in exclude_fields:
                remove_field_path(filtered_result, field_path)
        
        filtered.append(filtered_result)
    
    return filtered


DEFAULT_APP_INTERNAL_PORT = 8000
APPROX_MAX_CONVERSATION_TOKENS = 120000
AVG_CHARS_PER_TOKEN = 4
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
INTERNAL_API_TIMEOUT = 10.0  # Timeout for internal API requests in seconds


async def _make_internal_api_request(
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Helper function to make internal API requests to the main API service.
    Used for fetching provider pricing and other configuration data.
    """
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    else:
        logger.warning("INTERNAL_API_SHARED_TOKEN not set. Internal API calls will be unauthenticated.")
    
    url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    
    async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT) as client:
        try:
            response = await client.request(method, url, json=payload, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Internal API HTTP error for {method} {endpoint}: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Internal API request error for {method} {endpoint}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in internal API request for {method} {endpoint}: {e}", exc_info=True)
            raise


async def _publish_skill_status(
    cache_service: Optional[CacheService],
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    status: str,
    preview_data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> None:
    """
    Publish skill execution status update to Redis for WebSocket delivery.
    
    Args:
        cache_service: CacheService instance for publishing events
        task_id: Task ID for the skill execution
        request_data: AskSkillRequest containing user and chat info
        app_id: The app ID that owns the skill
        skill_id: The skill ID being executed
        status: Status of execution ('processing', 'finished', 'error')
        preview_data: Optional preview data for the skill results
        error: Optional error message if status is 'error'
    """
    if not cache_service:
        logger.debug(f"[Task ID: {task_id}] Cache service not available, skipping skill status publish")
        return

    # CRITICAL: Skip WebSocket events for external requests (REST API)
    # This prevents skill status updates from popping up in the web app when a user makes an API call.
    if request_data.is_external:
        logger.debug(f"[Task ID: {task_id}] External request detected. Skipping skill status publish for Web App.")
        return
    
    try:
        # Construct the skill status payload matching frontend expectations
        skill_status_payload = {
            "type": "skill_execution_status",
            "event_for_client": "skill_execution_status",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "message_id": request_data.message_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "app_id": app_id,
            "skill_id": skill_id,
            "status": status,
            "preview_data": preview_data or {}
        }
        
        # Add error if present
        if error:
            skill_status_payload["error"] = error
        
        # Publish to Redis channel for WebSocket delivery
        # Channel format: ai_typing_indicator_events::{user_id_hash}
        channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
        await cache_service.publish_event(channel, skill_status_payload)
        logger.info(
            f"[Task ID: {task_id}] Published skill status '{status}' for skill '{app_id}.{skill_id}' "
            f"to channel '{channel}' with preview_data keys: {list(preview_data.keys()) if preview_data else 'none'}"
        )
    except Exception as e:
        logger.error(
            f"[Task ID: {task_id}] Failed to publish skill status for '{app_id}.{skill_id}': {e}",
            exc_info=True
        )


def _validate_skill_provider(
    provider: Optional[str],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    log_prefix: str,
) -> Optional[str]:
    """
    Validate a provider value against the skill's known providers list from app.yml.

    If the provider is not in the skill's providers list (or is None/empty), returns
    the first valid provider from the skill definition. This prevents LLM hallucination
    (e.g. returning 'Brave Search' for the events skill that only supports 'Meetup').

    Args:
        provider:                 Provider string from LLM output or metadata (may be wrong)
        app_id:                   App identifier (e.g. 'events', 'web', 'maps')
        skill_id:                 Skill identifier (e.g. 'search')
        discovered_apps_metadata: Full app metadata dict from which skill providers are read
        log_prefix:               Log prefix for debug/warning messages

    Returns:
        A valid provider string, or the original provider if the skill has no providers
        list defined (in which case we cannot validate).
    """
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata:
        return provider

    skill_provider_refs = None
    for skill_def in (app_metadata.skills or []):
        if skill_def.id == skill_id:
            skill_provider_refs = skill_def.providers
            break

    if not skill_provider_refs:
        # No providers list in app.yml — cannot validate, return as-is
        return provider

    # Extract provider names from ProviderRef objects for comparison
    skill_providers = [ref.name for ref in skill_provider_refs]

    if provider in skill_providers:
        return provider

    # "auto" and "none" are valid meta-values meaning "use all providers" —
    # don't override them with a specific provider name.
    if provider and provider.lower() in ("auto", "none"):
        return provider

    # Provider is invalid (hallucinated or wrong) — override with the first valid one
    correct_provider = skill_providers[0]
    if provider:
        logger.warning(
            "%s Provider %r is not in the skill's providers list %r for %s.%s — "
            "overriding with %r",
            log_prefix,
            provider,
            skill_providers,
            app_id,
            skill_id,
            correct_provider,
        )
    else:
        logger.debug(
            "%s No provider set for %s.%s — defaulting to %r",
            log_prefix,
            app_id,
            skill_id,
            correct_provider,
        )
    return correct_provider


async def _charge_skill_credits(
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    results: List[Dict[str, Any]],
    parsed_args: Dict[str, Any],
    log_prefix: str,
    grouped_results: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Calculate and charge credits for a skill execution.
    Creates usage entry automatically via BillingService.
    
    Args:
        grouped_results: Optional grouped results from multi-request skills.
            Each group has {"id": ..., "results": [...], "error": "..."}.
            Used to count only successful requests for billing (failed requests are not charged).
    """
    try:
        # Get skill definition from app metadata
        app_metadata = discovered_apps_metadata.get(app_id)
        if not app_metadata:
            logger.warning(f"{log_prefix} App '{app_id}' not found in discovered apps metadata. Skipping skill billing.")
            return
        
        # Find the skill definition
        skill_def: Optional[AppSkillDefinition] = None
        for skill in app_metadata.skills or []:
            if skill.id == skill_id:
                skill_def = skill
                break
        
        if not skill_def:
            logger.warning(f"{log_prefix} Skill '{skill_id}' not found in app '{app_id}' metadata. Skipping skill billing.")
            return
        
        # Get pricing config from skill definition
        pricing_config = None
        if skill_def.pricing:
            # Skill has explicit pricing in app.yml - use it
            pricing_config = skill_def.pricing.model_dump(exclude_none=True)
            logger.debug(f"{log_prefix} Using skill-level pricing from app.yml for '{app_id}.{skill_id}'")
        elif skill_def.full_model_reference:
            # Skill has a full model reference - try to get model-specific pricing
            try:
                # Parse provider and model from full_model_reference (e.g., "google/gemini-3-pro-image-preview")
                if "/" in skill_def.full_model_reference:
                    provider_id, model_suffix = skill_def.full_model_reference.split("/", 1)
                    
                    endpoint = f"internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
                    pricing_config = await _make_internal_api_request("GET", endpoint)
                    if pricing_config:
                        logger.debug(f"{log_prefix} Using model-specific pricing for '{skill_def.full_model_reference}': {pricing_config}")
                else:
                    logger.warning(f"{log_prefix} Invalid full_model_reference format: '{skill_def.full_model_reference}'. Expected 'provider/model'.")
            except Exception as e:
                logger.warning(f"{log_prefix} Error fetching model-specific pricing for '{skill_def.full_model_reference}': {e}")
                
        if not pricing_config and skill_def.providers and len(skill_def.providers) > 0:
            # Skill doesn't have explicit pricing, but has providers - try to get provider-level pricing
            # Use the first provider (most skills will have one primary provider)
            provider_name = skill_def.providers[0].name
            # Normalize provider name to lowercase (provider IDs in YAML are lowercase, e.g., "brave")
            provider_id = provider_name.lower()
            
            # Map provider names to provider IDs (handles cases like "Google" -> "google_maps" for maps app)
            # This matches the frontend mapping logic in generate-apps-metadata.js
            if provider_name == "Google" and app_id == "maps":
                provider_id = "google_maps"
            elif provider_name == "Brave" or provider_name == "Brave Search":
                provider_id = "brave"
            
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' has no explicit pricing, attempting to fetch provider-level pricing from '{provider_id}' (mapped from '{provider_name}')")
            
            try:
                # Fetch provider pricing via internal API
                endpoint = f"internal/config/provider_pricing/{provider_id}"
                provider_pricing = await _make_internal_api_request("GET", endpoint)
                
                if provider_pricing and isinstance(provider_pricing, dict):
                    # Convert provider pricing format to billing format
                    # Provider pricing may have formats like:
                    # - per_request_credits: 5 (Brave)
                    # - per_unit: { credits: X } (already in correct format)
                    # - etc.
                    
                    if "per_request_credits" in provider_pricing:
                        # Convert per_request_credits to per_unit.credits format
                        credits_per_request = provider_pricing["per_request_credits"]
                        pricing_config = {
                            "per_unit": {
                                "credits": credits_per_request
                            }
                        }
                        logger.debug(f"{log_prefix} Converted provider pricing: per_request_credits={credits_per_request} -> per_unit.credits={credits_per_request}")
                    elif "per_unit" in provider_pricing:
                        # Provider already uses per_unit format
                        pricing_config = {"per_unit": provider_pricing["per_unit"]}
                        logger.debug(f"{log_prefix} Using provider pricing per_unit format: {provider_pricing['per_unit']}")
                    else:
                        logger.warning(f"{log_prefix} Provider '{provider_id}' has pricing but unsupported format: {list(provider_pricing.keys())}. Falling back to minimum charge.")
                else:
                    logger.warning(f"{log_prefix} Could not retrieve valid provider pricing for '{provider_id}'. Response: {provider_pricing}")
            except Exception as e:
                logger.warning(f"{log_prefix} Error fetching provider pricing for '{provider_id}': {e}. Falling back to minimum charge.")
        
        # Skip charging if the skill returned no results (e.g. API key failure,
        # provider outage). Users should not be billed for failed requests.
        if not results:
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}' returned 0 results, skipping billing.")
            return
        
        # Skip charging if ALL results indicate failure (error/cancelled status).
        # When a skill execution fails (HTTP error, rate limit, timeout, etc.),
        # the results list contains dicts with status="error" or status="cancelled".
        # Users should not be charged for failed executions.
        # Note: the REST API flow (apps_api.py) already handles this via
        # is_skill_execution_successful() — this mirrors that logic for the
        # AI chat flow.
        if all(
            isinstance(r, dict) and r.get("status") in ("error", "cancelled")
            for r in results
        ):
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}' failed — all {len(results)} result(s) have error/cancelled status, skipping billing.")
            return
        
        # Calculate credits based on skill execution
        # All skills use 'requests' array format - charge per request (units_processed)
        # IMPORTANT: Only charge for SUCCESSFUL requests. Failed requests (e.g., rate-limited
        # searches, HTTP errors) should not be billed to the user.
        units_processed = None
        if grouped_results and isinstance(grouped_results, list):
            # Use grouped_results to count only successful requests (no error field, non-empty results)
            total_requests = len(grouped_results)
            successful_requests = sum(
                1 for group in grouped_results
                if isinstance(group, dict)
                and not group.get("error")  # No error field
                and group.get("results")    # Has non-empty results
            )
            units_processed = successful_requests
            if successful_requests < total_requests:
                logger.info(
                    f"{log_prefix} Skill '{app_id}.{skill_id}': {successful_requests}/{total_requests} "
                    f"request(s) succeeded — only charging for successful ones"
                )
            else:
                logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' executed with {units_processed} successful request(s)")
        elif "requests" in parsed_args and isinstance(parsed_args["requests"], list):
            # Fallback: count all requests in the requests array (when grouped_results not available)
            units_processed = len(parsed_args["requests"])
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' executed with {units_processed} request(s) in requests array")
        else:
            # Fallback: if no requests array found, charge for single execution
            # This handles edge cases where a skill might not use the requests pattern yet
            units_processed = 1
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' has no 'requests' array, charging for single execution")
        
        # If all requests failed, skip billing entirely
        if units_processed <= 0:
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}': no successful requests, skipping billing entirely.")
            return
        
        # Calculate credits
        if pricing_config:
            credits_charged = calculate_total_credits(
                pricing_config=pricing_config,
                units_processed=units_processed
            )
        else:
            # Default to minimum charge if no pricing config
            credits_charged = MINIMUM_CREDITS_CHARGED
            logger.info(f"{log_prefix} No pricing config for skill '{app_id}.{skill_id}', using minimum charge: {credits_charged}")
        
        if credits_charged <= 0:
            logger.debug(f"{log_prefix} Calculated credits for skill '{app_id}.{skill_id}' is 0, skipping billing.")
            return
        
        # Resolve provider info (name + region) for usage tracking
        # This allows the usage detail view to show provider and region for ALL skills,
        # not just AI Ask. We derive the provider_id from full_model_reference or providers list.
        resolved_provider_name = None
        resolved_region = None
        resolved_model_used = skill_def.full_model_reference  # e.g., "bfl/flux-schnell" or None
        
        # Determine provider_id for info lookup
        info_provider_id = None
        if skill_def.full_model_reference and "/" in skill_def.full_model_reference:
            info_provider_id = skill_def.full_model_reference.split("/", 1)[0]
        elif skill_def.providers and len(skill_def.providers) > 0:
            # Re-use the same name-to-ID mapping as the pricing lookup
            pname = skill_def.providers[0].name
            info_provider_id = pname.lower()
            if pname == "Google" and app_id == "maps":
                info_provider_id = "google_maps"
            elif pname in ("Brave", "Brave Search"):
                info_provider_id = "brave"
        
        if info_provider_id:
            try:
                model_ref_param = f"?model_ref={skill_def.full_model_reference}" if skill_def.full_model_reference else ""
                info_endpoint = f"internal/config/provider_info/{info_provider_id}{model_ref_param}"
                provider_info = await _make_internal_api_request("GET", info_endpoint)
                if provider_info and isinstance(provider_info, dict):
                    resolved_provider_name = provider_info.get("name")
                    resolved_region = provider_info.get("region")
                    logger.debug(f"{log_prefix} Resolved provider info for '{info_provider_id}': name={resolved_provider_name}, region={resolved_region}")
            except Exception as e:
                logger.warning(f"{log_prefix} Failed to fetch provider info for '{info_provider_id}': {e}")
        
        # Prepare usage details
        # Include chat_id and message_id when skill is triggered in a chat context
        # These fields are important for linking usage entries to chat sessions
        # The billing service will validate and only include non-empty values
        usage_details = {
            "chat_id": request_data.chat_id,  # Always available in AskSkillRequest
            "message_id": request_data.message_id,  # Always available in AskSkillRequest
            "is_incognito": getattr(request_data, 'is_incognito', False),  # Include incognito flag for billing
            "units_processed": units_processed,
            "model_used": resolved_model_used,  # Full model reference (e.g., "bfl/flux-schnell") or None
            "server_provider": resolved_provider_name,  # Provider display name (e.g., "Brave Search", "BFL")
            "server_region": resolved_region,  # Server region (e.g., "US", "EU")
        }
        
        # Charge credits via internal API — one call per successful request.
        # This creates one usage entry per request instead of one combined entry,
        # so users can see individual search/map/news requests in the usage detail view.
        # credits_charged is the TOTAL for all requests; per_request_credits is the
        # per-unit cost computed by dividing total credits by units_processed.
        per_request_credits = credits_charged // units_processed if units_processed > 0 else credits_charged
        # Use ceiling division to handle rounding: the last request gets any remainder.
        credits_remainder = credits_charged - (per_request_credits * units_processed)
        
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        
        async with httpx.AsyncClient() as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            for i in range(units_processed):
                # Add any remainder credits to the last request
                request_credits = per_request_credits + (credits_remainder if i == units_processed - 1 else 0)
                if request_credits <= 0:
                    continue
                
                # Each individual request gets units_processed=1 to reflect one request
                request_usage_details = {**usage_details, "units_processed": 1}
                
                charge_payload = {
                    "user_id": request_data.user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "credits": request_credits,
                    "skill_id": skill_id,  # Required: ID of the skill that was executed
                    "app_id": app_id,  # Required: ID of the app that contains the skill
                    "usage_details": request_usage_details  # Contains chat_id, message_id, and other optional metadata
                }
                logger.info(f"{log_prefix} Charging {request_credits} credits for skill '{app_id}.{skill_id}' (request {i + 1}/{units_processed}).")
                response = await client.post(url, json=charge_payload, headers=headers, timeout=10.0)
                response.raise_for_status()
                logger.debug(f"{log_prefix} Charged request {i + 1}/{units_processed} for '{app_id}.{skill_id}': {response.json()}")
            
            logger.info(f"{log_prefix} Successfully charged {credits_charged} total credits for skill '{app_id}.{skill_id}' across {units_processed} request(s).")
            
    except httpx.HTTPStatusError as e:
        logger.error(f"{log_prefix} HTTP error charging credits for skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits for skill '{app_id}.{skill_id}': {e}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution


def _convert_timestamps_to_human_readable(value: Any) -> Any:
    """
    Recursively converts Unix timestamps in app settings/memories data to human-readable date strings.
    
    CRITICAL: LLMs cannot reliably interpret raw Unix timestamps (e.g., 1768390180).
    They may hallucinate incorrect years, especially for dates outside their training data.
    Converting timestamps to human-readable format (e.g., "January 14, 2026") ensures
    the LLM correctly understands when settings/memories were created.
    
    Detects timestamps by:
    1. Looking for keys containing 'date', 'time', 'created', 'updated', 'added', '_at' (case-insensitive)
    2. Checking if the value is an integer in a reasonable Unix timestamp range (2010-2100)
    
    Args:
        value: The value to process (can be dict, list, or primitive)
    
    Returns:
        The processed value with timestamps converted to readable strings
    """
    # Define timestamp field name patterns (case-insensitive)
    TIMESTAMP_PATTERNS = ('date', 'time', 'created', 'updated', 'added', '_at')
    
    # Unix timestamp range: 2010-01-01 to 2100-01-01 (to avoid false positives)
    MIN_TIMESTAMP = 1262304000  # 2010-01-01 00:00:00 UTC
    MAX_TIMESTAMP = 4102444800  # 2100-01-01 00:00:00 UTC
    
    def is_likely_timestamp(key: str, val: Any) -> bool:
        """Check if a field is likely a Unix timestamp based on key name and value."""
        if not isinstance(val, (int, float)):
            return False
        key_lower = key.lower()
        # Check if key matches any timestamp pattern
        if any(pattern in key_lower for pattern in TIMESTAMP_PATTERNS):
            # Check if value is in valid Unix timestamp range
            return MIN_TIMESTAMP <= val <= MAX_TIMESTAMP
        return False
    
    def timestamp_to_readable(timestamp: int) -> str:
        """Convert Unix timestamp to human-readable date string."""
        try:
            dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
            # Format: "January 14, 2026" - clear and unambiguous
            return dt.strftime("%B %d, %Y")
        except Exception:
            # If conversion fails, return original value as string
            return str(timestamp)
    
    if isinstance(value, dict):
        processed = {}
        for k, v in value.items():
            if is_likely_timestamp(k, v):
                processed[k] = timestamp_to_readable(int(v))
            else:
                processed[k] = _convert_timestamps_to_human_readable(v)
        return processed
    elif isinstance(value, list):
        return [_convert_timestamps_to_human_readable(item) for item in value]
    else:
        return value


async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    encryption_service: EncryptionService, # Added EncryptionService
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    secrets_manager: Optional[SecretsManager] = None,
    cache_service: Optional[CacheService] = None,
    always_include_skills: Optional[List[str]] = None,  # Skills to ALWAYS include regardless of preprocessing
    user_overrides: Optional[UserOverrides] = None  # User overrides from @mention syntax (for skip-permission logic)
) -> AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]]:
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")
    
    # --- Auto-reject any pending app settings/memories request for this chat ---
    # If user sends a new message without responding to the permission dialog,
    # we auto-interpret this as a rejection of the previous request.
    # This ensures we only process the NEW message, not both.
    if cache_service:
        try:
            pending_context = await cache_service.get_pending_app_settings_memories_request(request_data.chat_id)
            if pending_context:
                old_request_id = pending_context.get("request_id", "unknown")
                old_message_id = pending_context.get("message_id", "unknown")
                logger.info(
                    f"{log_prefix} Found pending app settings/memories request {old_request_id} for message {old_message_id}. "
                    f"User sent new message - auto-rejecting previous request."
                )
                
                # Delete the pending context (auto-reject) and clean up per-user index
                await cache_service.delete_pending_app_settings_memories_request(request_data.chat_id, user_id=request_data.user_id)
                
                # Notify client to dismiss the permission dialog
                # Use Redis pub/sub to send to WebSocket
                try:
                    # Note: json is imported at module level, don't re-import locally as it shadows the global import
                    redis_client = await cache_service.client
                    if redis_client:
                        channel = f"user_cache_events:{request_data.user_id}"
                        pubsub_message = {
                            "event_type": "dismiss_app_settings_memories_dialog",
                            "payload": {
                                "chat_id": request_data.chat_id,
                                "request_id": old_request_id,
                                "reason": "new_message_sent",
                                "message_id": old_message_id  # The original message that triggered the request
                            }
                        }
                        await redis_client.publish(channel, json.dumps(pubsub_message))
                        logger.info(f"{log_prefix} Sent dismiss_app_settings_memories_dialog event to client")
                except Exception as e:
                    logger.warning(f"{log_prefix} Failed to notify client about auto-rejection: {e}")
        except Exception as e:
            logger.error(f"{log_prefix} Error checking/auto-rejecting pending request: {e}", exc_info=True)
    
    # --- Request app settings/memories from client (zero-knowledge architecture) ---
    # The server NEVER decrypts app settings/memories - client decrypts using crypto API
    # App settings/memories are stored in cache (similar to embeds) when client confirms
    # Cache key format: app_settings_memories:{user_id}:{app_id}:{item_key}
    # This is more efficient than extracting from YAML in chat history
    #
    # IMPORTANT: If app settings/memories are needed but not in cache:
    # - Server sends request to client via WebSocket
    # - Task COMPLETES immediately (no LLM processing)
    # - Client shows permission dialog to user
    # - Once user confirms/rejects, client sends data back
    # - On user's NEXT message, data is available in cache for LLM processing
    loaded_app_settings_and_memories_content: Dict[str, Any] = {}
    # Start with any cleartext the client sent for @memory/@memory-entry mentions (so we do not request those again)
    if getattr(request_data, "mentioned_settings_memories_cleartext", None):
        mentioned = request_data.mentioned_settings_memories_cleartext
        if isinstance(mentioned, dict) and mentioned:
            for key, value in mentioned.items():
                if isinstance(key, str) and value is not None:
                    loaded_app_settings_and_memories_content[key] = value
            logger.info(f"{log_prefix} Pre-filled {len(mentioned)} app settings/memories from client-mentioned cleartext: {list(mentioned.keys())}")

    if preprocessing_results.load_app_settings_and_memories and cache_service:
        logger.debug(f"{log_prefix} Preprocessing requested app settings/memories: {preprocessing_results.load_app_settings_and_memories}")
        try:
            # Import helper function for creating requests
            from backend.core.api.app.utils.app_settings_memories_request import (
                create_app_settings_memories_request_message
            )
            
            requested_keys = list(preprocessing_results.load_app_settings_and_memories)
            # Include keys from client-mentioned cleartext so we have a full set; they are already in loaded_app_settings_and_memories_content
            if getattr(request_data, "mentioned_settings_memories_cleartext", None):
                mentioned = request_data.mentioned_settings_memories_cleartext
                if isinstance(mentioned, dict):
                    for key in mentioned:
                        if key not in requested_keys:
                            requested_keys.append(key)
            
            # Check cache first (similar to how embeds are handled)
            # Cache stores vault-encrypted data that server can decrypt for AI processing
            # Chat-specific caching ensures app settings/memories are evicted with the chat
            cached_data = await cache_service.get_app_settings_memories_batch_from_cache(
                user_id=request_data.user_id,
                chat_id=request_data.chat_id,
                requested_keys=requested_keys
            )
            
            if cached_data:
                logger.info(f"{log_prefix} Found {len(cached_data)} app settings/memories entries in cache")
                
                # IMPORTANT: Decrypt the vault-encrypted content before passing to LLM
                # The cache stores: {"app_id": ..., "item_key": ..., "content": "<encrypted>", "cached_at": ...}
                # We need to decrypt "content" and pass only the decrypted content to the LLM
                for key, cache_entry in cached_data.items():
                    try:
                        encrypted_content = cache_entry.get("content")
                        if encrypted_content and user_vault_key_id and encryption_service:
                            # Decrypt the vault-encrypted content
                            decrypted_content = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_content,
                                key_id=user_vault_key_id
                            )
                            if decrypted_content:
                                # Try to parse as JSON (content might be serialized JSON)
                                try:
                                    parsed_content = json.loads(decrypted_content)
                                    loaded_app_settings_and_memories_content[key] = parsed_content
                                    content_type = type(parsed_content).__name__
                                    if isinstance(parsed_content, list):
                                        content_metadata = f"list_len={len(parsed_content)}"
                                    elif isinstance(parsed_content, dict):
                                        dict_keys = list(parsed_content.keys())
                                        content_metadata = f"dict_key_count={len(dict_keys)}"
                                    else:
                                        content_metadata = "scalar"
                                    logger.info(
                                        f"{log_prefix} Successfully decrypted app settings/memories for {key} "
                                        f"(type={content_type}, {content_metadata})"
                                    )
                                except json.JSONDecodeError:
                                    # If not JSON, use as plain string
                                    loaded_app_settings_and_memories_content[key] = decrypted_content
                                    logger.info(
                                        f"{log_prefix} Successfully decrypted app settings/memories for {key} "
                                        f"(type=str, length={len(decrypted_content)})"
                                    )
                            else:
                                logger.warning(f"{log_prefix} Failed to decrypt app settings/memories for {key}")
                        else:
                            # If no encryption service or vault key, log warning
                            logger.warning(f"{log_prefix} Cannot decrypt app settings/memories for {key} - missing encryption_service or user_vault_key_id")
                    except Exception as decrypt_error:
                        logger.error(f"{log_prefix} Error decrypting app settings/memories for {key}: {decrypt_error}", exc_info=True)
            
            # Check if we need to create a new request for missing keys.
            # Keys already in loaded_app_settings_and_memories_content (from client cleartext or cache) must not be requested again.
            missing_keys = [
                key for key in requested_keys
                if key not in loaded_app_settings_and_memories_content
            ]

            if missing_keys and getattr(request_data, "is_app_settings_memories_continuation", False):
                # This is a continuation task (user already confirmed/rejected the original request).
                # Do NOT issue another permission dialog — the user's decision was already recorded.
                # Proceed without the missing data instead.
                logger.info(
                    f"{log_prefix} Continuation task: skipping new permission request for "
                    f"{len(missing_keys)} missing keys {missing_keys} — user already responded to the original request. "
                    f"Proceeding without these keys."
                )
                missing_keys = []

            if missing_keys:
                logger.info(f"{log_prefix} Creating new app settings/memories request for {len(missing_keys)} missing keys")
                # Create new system message request in chat history
                # Client will encrypt with chat key and store it
                # When user confirms, client will send app settings/memories as separate data (like embeds)
                # and server will store them in cache for future use
                request_id = await create_app_settings_memories_request_message(
                    chat_id=request_data.chat_id,
                    requested_keys=missing_keys,
                    cache_service=cache_service,
                    connection_manager=None,  # Celery tasks run in separate processes, can't access WebSocket manager directly
                    user_id=request_data.user_id,
                    device_fingerprint_hash=None,  # Will use first available device connection
                    message_id=request_data.message_id  # User message that triggered this request (for UI display)
                )
                
                if request_id:
                    logger.info(f"{log_prefix} Created app settings/memories request {request_id} - storing pending context and returning")
                    # IMPORTANT: Store the pending request context so we can re-trigger processing
                    # when user confirms or rejects. The confirmation/rejection acts as a trigger
                    # for a NEW AI processing pass - not a continuation of this task.
                    #
                    # Flow:
                    # 1. This task completes (no LLM response)
                    # 2. Client shows permission dialog
                    # 3. User confirms/rejects (could be seconds or hours later)
                    # 4. Server receives confirmation → triggers NEW ask_skill task
                    # 5. New task finds data in cache (if confirmed) → normal LLM response
                    #
                    # NOTE: We only store minimal context here - NOT the message_history!
                    # The chat history is already cached on the server (recent chat).
                    # When continuing, we retrieve the chat from cache.
                    try:
                        # Store MINIMAL context needed to re-trigger processing
                        # Do NOT store message_history - it's already in the chat cache
                        pending_context = {
                            "request_id": request_id,
                            "chat_id": request_data.chat_id,
                            "message_id": request_data.message_id,
                            "user_id": request_data.user_id,
                            "user_id_hash": request_data.user_id_hash,
                            "mate_id": request_data.mate_id,
                            "active_focus_id": request_data.active_focus_id,
                            "chat_has_title": request_data.chat_has_title,
                            "is_incognito": request_data.is_incognito,
                            "requested_keys": missing_keys,  # Keys that were requested
                            "task_id": task_id,
                        }
                        await cache_service.store_pending_app_settings_memories_request(
                            chat_id=request_data.chat_id,
                            context=pending_context,
                            ttl=86400 * 7  # 7 days - user can confirm/reject within a week
                        )
                        logger.info(f"{log_prefix} Stored pending context for request {request_id}")
                    except Exception as e:
                        logger.error(f"{log_prefix} Failed to store pending context: {e}", exc_info=True)
                        # Continue without storing - user will need to send a new message
                    
                    # CRITICAL: Yield a special marker to signal that we're awaiting user permission.
                    # The stream_consumer.py will detect this marker and NOT send an error message.
                    # Without this marker, the empty stream would be treated as an error.
                    yield {"__awaiting_app_settings_memories_permission__": True, "request_id": request_id}
                    
                    # Return early - task complete, no LLM response
                    return
                else:
                    logger.warning(f"{log_prefix} Failed to create app settings/memories request message - continuing without app settings/memories")
            else:
                logger.info(f"{log_prefix} All requested app settings/memories keys found in cache")
            
        except Exception as e:
            logger.error(f"{log_prefix} Error handling app settings/memories requests: {e}", exc_info=True)
            # Continue without app settings/memories - don't fail the entire request

    prompt_parts = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Resolve user's timezone — fall back to UTC if not set or unrecognised
    user_timezone = request_data.user_preferences.get("timezone") if request_data.user_preferences else None
    try:
        user_tz = zoneinfo.ZoneInfo(user_timezone) if user_timezone else datetime.timezone.utc
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        logger.warning(f"Unrecognised timezone '{user_timezone}', falling back to UTC")
        user_tz = datetime.timezone.utc
        user_timezone = None  # Don't include an invalid tz name in the prompt

    # Convert current time to user's local timezone so the LLM works in local time directly
    now_local = now_utc.astimezone(user_tz)
    date_time_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")

    if user_timezone:
        # Include both local time and timezone name so the LLM never needs to convert
        prompt_parts.append(
            f"Current date and time (in user's timezone): {date_time_str}\n"
            f"User's timezone: {user_timezone}"
        )
    else:
        # No timezone info — fall back to UTC and note it
        date_time_str_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S %Z")
        prompt_parts.append(f"Current date and time: {date_time_str_utc} (user timezone unknown)")
    # Add temporal awareness instruction right after the date to emphasize its importance
    # This ensures the LLM properly filters past vs future events based on the current date
    prompt_parts.append(base_instructions.get("base_temporal_awareness_instruction", ""))
    prompt_parts.append(base_instructions.get("base_ethics_instruction", ""))
    selected_mate_config = next((mate for mate in all_mates_configs if mate.id == preprocessing_results.selected_mate_id), None)
    if selected_mate_config:
        prompt_parts.append(selected_mate_config.default_system_prompt)
    # Insert creator_and_used_model_instruction right after the mate-specific prompt
    # This informs the user who created the assistant and which model (name and id) powers the response.
    try:
        creator_and_model_instruction_template = base_instructions.get("creator_and_used_model_instruction")
        if creator_and_model_instruction_template:
            # Prefer the model name from preprocessing; fall back to suffix of the model id or a generic label
            selected_model_id: str = preprocessing_results.selected_main_llm_model_id or ""
            # If model name is missing, use the id's suffix (after provider prefix) as a reasonable display name
            derived_model_name: str = (
                preprocessing_results.selected_main_llm_model_name
                or (selected_model_id.split("/", 1)[-1] if selected_model_id else "")
            )

            filled_instruction = creator_and_model_instruction_template.format(
                MODEL_NAME=derived_model_name,
                MODEL_ID=selected_model_id,
            )
            prompt_parts.append(filled_instruction)
            logger.debug(
                f"{log_prefix} Added creator_and_used_model_instruction with model_name='{derived_model_name}', model_id='{selected_model_id}'."
            )
        else:
            logger.debug(f"{log_prefix} Base instructions missing 'creator_and_used_model_instruction'; skipping injection.")
    except Exception as e:
        # Robust error handling to ensure prompt construction never fails because of formatting issues
        logger.error(
            f"{log_prefix} Failed to inject creator_and_used_model_instruction: {e}",
            exc_info=True,
        )
    # TODO: Update this key once app use is implemented - currently using base_capabilities_instruction
    # which explains what the chatbot can and cannot do yet
    # Inject available apps list into capabilities instruction
    base_capabilities_instruction_template = base_instructions.get("base_capabilities_instruction", "")
    if base_capabilities_instruction_template:
        # Extract available app IDs from discovered_apps_metadata
        available_app_ids = sorted(list(discovered_apps_metadata.keys())) if discovered_apps_metadata else []
        available_apps_str = ", ".join(available_app_ids) if available_app_ids else "none (no apps available)"
        
        # Replace placeholder with actual available apps list
        filled_capabilities_instruction = base_capabilities_instruction_template.replace(
            "{AVAILABLE_APPS}",
            available_apps_str
        )
        prompt_parts.append(filled_capabilities_instruction)
        logger.info(
            f"{log_prefix} Injected available apps list into system prompt: {available_apps_str} "
            f"({len(available_app_ids)} app(s) available)"
        )
    else:
        logger.warning(f"{log_prefix} base_capabilities_instruction not found in base_instructions.yml")
    
    prompt_parts.append(base_instructions.get("follow_up_instruction", ""))
    prompt_parts.append(base_instructions.get("base_link_encouragement_instruction", ""))
    
    # Add app deep linking instruction so the AI uses correct relative hash links
    # Only include when apps are available (no point linking to apps that don't exist)
    if discovered_apps_metadata:
        prompt_parts.append(base_instructions.get("base_app_deep_linking_instruction", ""))
    
    # Add settings/memories deep link instruction so the AI can suggest creating/updating
    # entries inline in its response. Only include when apps are available (the AI needs
    # to know the category IDs and field names). The instruction is always-on for simplicity;
    # the AI will only generate links when the conversation actually reveals preferences.
    if discovered_apps_metadata:
        settings_deep_link_instruction = base_instructions.get("base_settings_memories_deep_link_instruction", "")
        if settings_deep_link_instruction:
            prompt_parts.append(settings_deep_link_instruction)
    
    # === BUILD PRESELECTED SKILLS SET ===
    # Build this BEFORE the instruction injection block so we can filter app instructions
    # by whether their skills are preselected. Also used later for tool generation.
    preselected_skills = None
    if hasattr(preprocessing_results, 'relevant_app_skills'):
        if preprocessing_results.relevant_app_skills is not None:
            preselected_skills = set(preprocessing_results.relevant_app_skills)
            if preselected_skills:
                logger.debug(f"{log_prefix} Using preselected skills from preprocessing: {preselected_skills}")
            else:
                logger.debug(f"{log_prefix} No skills preselected by preprocessing (empty list)")
        else:
            logger.warning(f"{log_prefix} relevant_app_skills is None (should be list or empty list). Treating as empty list.")
            preselected_skills = set()

    # HARDENING: Merge always_include_skills into preselected_skills — but NOT when the user
    # explicitly requested specific skills via @skill:app:skill_id. In that case we use only
    # the user's selection and add a mandatory instruction to use those tools.
    user_requested_skills_only = getattr(preprocessing_results, "user_requested_skills_only", False)
    if user_requested_skills_only and preselected_skills:
        logger.info(
            f"{log_prefix} [USER_SKILLS] User explicitly requested skill(s); not merging always_include_skills. "
            f"Preselected only: {preselected_skills}"
        )
    elif always_include_skills:
        if preselected_skills is None:
            preselected_skills = set()
        skills_to_add = set(always_include_skills) - preselected_skills
        if skills_to_add:
            logger.info(
                f"{log_prefix} [SKILL_HARDENING] Adding always-include skills to preselected set: {skills_to_add}. "
                f"These skills are configured to always be available regardless of preprocessing."
            )
        preselected_skills = preselected_skills | set(always_include_skills)
        logger.debug(f"{log_prefix} Final preselected skills (after merging always-include): {preselected_skills}")


    # When user explicitly requested skills, add a mandatory instruction so the model must use them
    if user_requested_skills_only and preselected_skills:
        mandatory_skills_list = ", ".join(sorted(preselected_skills))
        mandatory_instruction = (
            f"The user explicitly requested that you use the following tool(s) for this request; "
            f"you MUST call at least one of them: {mandatory_skills_list}. Do not use other tools unless the user's request clearly requires them."
        )
        prompt_parts.append(mandatory_instruction)
        logger.info(f"{log_prefix} [USER_SKILLS] Added mandatory skill instruction for: {mandatory_skills_list}")

    # === DYNAMIC APP-SPECIFIC INSTRUCTIONS ===
    # Load instructions from each available app's app.yml configuration.
    # Instructions are ONLY included when at least one skill from the app is preselected
    # (or the app has no skills, e.g. purely instructional apps).
    # This prevents the AI from seeing references to tools it can't call in this turn,
    # which would cause tool name hallucination (e.g., calling 'images' when images-generate
    # wasn't preselected as a tool).
    app_instructions_added = []
    app_instructions_skipped = []
    if discovered_apps_metadata:
        # Get the conversation category from preprocessing for category-filtered instructions
        conversation_category = preprocessing_results.category if preprocessing_results else None

        # Build normalized set of relevant embed preview types from preprocessing.
        # The preprocessor uses freeform strings (e.g., 'email', 'document') that may
        # differ from app embed type IDs (e.g., 'email', 'doc'). The normalization map
        # bridges cases where the preprocessor string differs from the app.yml ID.
        relevant_previews = set()
        if preprocessing_results and preprocessing_results.relevant_embedded_previews:
            relevant_previews = set(preprocessing_results.relevant_embedded_previews)
        PREVIEW_TO_EMBED_TYPE = {
            "document": "doc",
        }
        normalized_previews = set()
        for p in relevant_previews:
            normalized_previews.add(p)
            if p in PREVIEW_TO_EMBED_TYPE:
                normalized_previews.add(PREVIEW_TO_EMBED_TYPE[p])

        for app_id, app_metadata in discovered_apps_metadata.items():
            if not app_metadata.instructions:
                continue

            # Check if this app has any skills preselected for this turn.
            app_has_preselected_skill = False
            if app_metadata.skills and preselected_skills:
                app_has_preselected_skill = any(
                    f"{app_id}-{skill.id}" in preselected_skills
                    for skill in app_metadata.skills
                )

            for instruction_def in app_metadata.instructions:
                # Instructions with for_embed_types bypass skill preselection gating.
                # They are injected when the preprocessor identified any matching embed
                # preview type as relevant (e.g., email drafting format instructions
                # triggered by relevant_embedded_previews: ['email']).
                if instruction_def.for_embed_types:
                    if not (set(instruction_def.for_embed_types) & normalized_previews):
                        continue
                    # Embed-type match — skip skill preselection, fall through to category check
                else:
                    # Standard gating: skip if app has skills but none were preselected
                    if app_metadata.skills and preselected_skills and not app_has_preselected_skill:
                        continue

                # Check if instruction has category filtering
                if instruction_def.categories:
                    # Only include if conversation category matches
                    if conversation_category and conversation_category in instruction_def.categories:
                        prompt_parts.append(instruction_def.instruction)
                        app_instructions_added.append(f"{app_id} (category: {conversation_category})")
                    # Skip if categories specified but don't match
                else:
                    prompt_parts.append(instruction_def.instruction)
                    app_instructions_added.append(app_id)

            # Track skipped apps (only if ALL instructions were gated out)
            if app_metadata.skills and preselected_skills and not app_has_preselected_skill:
                if not any(inst.for_embed_types for inst in app_metadata.instructions):
                    app_instructions_skipped.append(app_id)
        
        if app_instructions_added:
            logger.info(f"{log_prefix} [APP_INSTRUCTIONS] Loaded instructions from apps: {', '.join(app_instructions_added)}")
        else:
            logger.debug(f"{log_prefix} [APP_INSTRUCTIONS] No app-specific instructions to load (apps: {list(discovered_apps_metadata.keys())})")
        if app_instructions_skipped:
            logger.debug(f"{log_prefix} [APP_INSTRUCTIONS] Skipped instructions for apps without preselected skills: {', '.join(app_instructions_skipped)}")
    else:
        logger.warning(f"{log_prefix} [APP_INSTRUCTIONS] No discovered apps - app-specific instructions unavailable")
    
    # === IMAGE CONTENT SAFETY INSTRUCTION ===
    # Conditionally inject prompt-injection defence for image uploads.
    # Only included when the images-view skill is preselected by the preprocessor,
    # so conversations without images pay zero extra tokens for this instruction.
    if preselected_skills and "images-view" in preselected_skills:
        image_safety_instruction = base_instructions.get("base_image_content_safety_instruction", "")
        if image_safety_instruction:
            prompt_parts.append(image_safety_instruction)
            logger.info(f"{log_prefix} [IMAGE_SAFETY] Injected image content safety instruction (images-view is preselected)")
    
    # === TOOL-CALLING THINKING DISCIPLINE ===
    # Prevents reasoning models (e.g., Gemini Flash) from hallucinating about tool
    # output in their thinking phase before the tool returns. Only injected when
    # skills are preselected, so conversations without tool use pay zero tokens.
    if preselected_skills:
        thinking_discipline = base_instructions.get("base_tool_thinking_discipline_instruction", "")
        if thinking_discipline:
            prompt_parts.append(thinking_discipline)
            logger.debug(f"{log_prefix} [THINKING_DISCIPLINE] Injected tool-calling thinking discipline instruction")
    
    # Add generic proactive skill usage instruction (only when apps are available)
    # This encourages using available skills proactively for time-sensitive queries
    if discovered_apps_metadata:
        prompt_parts.append(base_instructions.get("base_proactive_skill_usage_instruction", ""))
    else:
        # When no apps available, skip the proactive skill usage instruction
        # to avoid confusing the AI about capabilities it doesn't have
        logger.info(f"{log_prefix} Skipping base_proactive_skill_usage_instruction - no apps available")
    
    prompt_parts.append(base_instructions.get("base_url_sourcing_instruction", ""))

    # === EMBED INSTRUCTION GATING ===
    # Scan message history once to determine which embed types exist in the conversation.
    # This prevents the LLM from seeing (and misusing) embed syntax when no embed results
    # are present. Without this guard, the LLM can hallucinate embed reference syntax —
    # e.g. fabricating > [quote](embed:web-result-1) blocks — even when no web search was run.
    # See docs/architecture/embed-prompt-gating.md (issue c35ac944).
    #
    # Composite skills that produce embed_refs the LLM can reference inline or as cards.
    # Format must match preselected_skills entries: "app_id-skill_id".
    _EMBED_PRODUCING_PRESELECTED_IDS = {
        "web-search", "news-search", "videos-search",
        "maps-search", "events-search",
        "travel-search_connections", "travel-search_stays",
        "shopping-search_products",
        "web-read",  # Non-composite single-result skills also produce embed_refs
    }
    # Subset whose results contain quotable text (web/news search results with
    # title/description/snippets that the source-quote verification can check against):
    _QUOTABLE_PRESELECTED_IDS = {"web-search", "news-search", "web-read"}

    # Determine whether embeds already exist in chat history (from prior turns).
    # Uses the same lightweight substring checks as the preprocessor's skill-forcing logic.
    _has_any_embeds_in_history = False
    _has_quotable_embeds_in_history = False
    for _msg in request_data.message_history:
        _msg_content = _msg.content if hasattr(_msg, "content") else (
            _msg.get("content") if isinstance(_msg, dict) else None
        )
        if not isinstance(_msg_content, str):
            continue
        # Any TOON block with an embed_ref field indicates embed results from a previous turn
        if not _has_any_embeds_in_history and "embed_ref:" in _msg_content:
            _has_any_embeds_in_history = True
        # Quotable embeds: web/news search results and web.read results contain
        # text-heavy content (title/description/snippets/markdown) worth quoting.
        # We check for embed_ref alongside app_id/skill_id markers in TOON content.
        if not _has_quotable_embeds_in_history and "embed_ref:" in _msg_content and (
            ("app_id: web" in _msg_content and "skill_id: search" in _msg_content) or
            ("app_id: news" in _msg_content and "skill_id: search" in _msg_content) or
            ("app_id: web" in _msg_content and "skill_id: read" in _msg_content)
        ):
            _has_quotable_embeds_in_history = True
        if _has_any_embeds_in_history and _has_quotable_embeds_in_history:
            break

    # Determine whether the current turn is about to produce embeds.
    # If a composite skill is preselected, the LLM will receive embed_ref slugs in tool results.
    _current_turn_produces_embeds = bool(
        preselected_skills and preselected_skills & _EMBED_PRODUCING_PRESELECTED_IDS
    )
    # If a quotable skill is preselected, the LLM will receive source_quote_hint in tool results.
    _current_turn_produces_quotable_embeds = bool(
        preselected_skills and preselected_skills & _QUOTABLE_PRESELECTED_IDS
    )

    # Inject inline/preview embed instruction only when the LLM will actually have embed_refs
    # to reference — either from history or from skills running this turn.
    _include_embed_referencing = _has_any_embeds_in_history or _current_turn_produces_embeds
    if _include_embed_referencing:
        prompt_parts.append(base_instructions.get("base_embed_referencing_instruction", ""))
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Injected embed referencing instruction "
            f"(history_embeds={_has_any_embeds_in_history}, current_turn_produces={_current_turn_produces_embeds})"
        )
    else:
        logger.debug(f"{log_prefix} [EMBED_PROMPT] Skipped embed referencing instruction — no embeds in history or preselected skills")

    # Inject source quote instruction only when quotable search results exist or are expected.
    # Quotable embed types: web search results, news search results (contain title/description/snippets).
    _include_source_quote = _has_quotable_embeds_in_history or _current_turn_produces_quotable_embeds
    if _include_source_quote:
        prompt_parts.append(base_instructions.get("base_embed_source_quote_instruction", ""))
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Injected source quote instruction "
            f"(history_quotable={_has_quotable_embeds_in_history}, current_turn_quotable={_current_turn_produces_quotable_embeds})"
        )
    else:
        logger.debug(f"{log_prefix} [EMBED_PROMPT] Skipped source quote instruction — no quotable embeds in history or preselected skills")
    # Add code block formatting instruction to ensure proper language and filename syntax
    # This helps with consistent parsing and rendering of code embeds
    prompt_parts.append(base_instructions.get("base_code_block_instruction", ""))
    # Add document generation instruction for rich document embeds (document_html fences)
    # This enables the LLM to create structured HTML documents rendered as document previews
    prompt_parts.append(base_instructions.get("base_document_generation_instruction", ""))
    # Add math plot instruction only when the math app is available.
    # Teaches the LLM to emit ```plot f(x) = ... ``` fences that stream_consumer.py
    # converts to interactive math-plot embeds rendered by function-plot on the frontend.
    if discovered_apps_metadata and "math" in discovered_apps_metadata:
        prompt_parts.append(base_instructions.get("base_plot_code_block_instruction", ""))
    
    # DEBUG: Log the app_settings_memories content before adding to prompt
    # This helps diagnose issues where data is found in cache but not injected into prompt
    server_environment = os.getenv("SERVER_ENVIRONMENT", "production").lower()
    if loaded_app_settings_and_memories_content:
        if server_environment == "development":
            logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] Adding {len(loaded_app_settings_and_memories_content)} item(s) to system prompt: {list(loaded_app_settings_and_memories_content.keys())}")
        else:
            logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] Adding {len(loaded_app_settings_and_memories_content)} item(s) to system prompt (keys redacted - production environment)")
    else:
        logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] No app settings/memories content to add to system prompt (dict is empty)")
    
    if loaded_app_settings_and_memories_content:
        # First, add the instruction telling the LLM how to use this data
        # CRITICAL: This instruction is essential because without it, the LLM may ignore the data
        # and respond with "I don't know anything about you" even when the data is present.
        app_settings_usage_instruction = base_instructions.get("base_app_settings_memories_usage_instruction", "")
        if app_settings_usage_instruction:
            prompt_parts.append(app_settings_usage_instruction)
        
        # Then add the actual data
        settings_and_memories_prompt_section = ["\n--- Relevant Information from Your App Settings and Memories ---"]
        for key, value in loaded_app_settings_and_memories_content.items():
            # CRITICAL: Convert Unix timestamps to human-readable date strings
            # LLMs hallucinate dates when given raw timestamps (e.g., may say "added in 2024" for 2026 timestamps)
            # This ensures dates like "added_date" are formatted as "January 14, 2026" instead of 1768390180
            processed_value = _convert_timestamps_to_human_readable(value)
            value_str = json.dumps(processed_value) if not isinstance(processed_value, str) else processed_value
            settings_and_memories_prompt_section.append(f"- {key}: {value_str}")
        prompt_parts.append("\n".join(settings_and_memories_prompt_section))

    active_focus_prompt_text: Optional[str] = None
    if request_data.active_focus_id:
        try:
            # Parse focus mode ID (format: "app_id-focus_id" using hyphen for consistency with tool names)
            app_id_of_focus, focus_id_in_app = request_data.active_focus_id.split('-', 1)
            app_metadata_for_focus = discovered_apps_metadata.get(app_id_of_focus)
            if app_metadata_for_focus and app_metadata_for_focus.focuses:
                for focus_def in app_metadata_for_focus.focuses:
                    if focus_def.id == focus_id_in_app:
                        active_focus_prompt_text = focus_def.system_prompt
                        break
        except Exception as e:
            logger.error(f"{log_prefix} Error processing active_focus_id '{request_data.active_focus_id}': {e}", exc_info=True)
    if active_focus_prompt_text:
        prompt_parts.insert(0, f"--- Active Focus: {request_data.active_focus_id} ---\n{active_focus_prompt_text}\n--- End Active Focus ---")

    # Enforce response language based on the preprocessor's detected output_language.
    # Appended last so it sits at the end of the system prompt where LLMs give it high
    # attention — this overrides any language the mate persona or instructions might imply.
    # ISO 639-1 code → human-readable name mapping (must stay in sync with SUPPORTED_LANGUAGES
    # in preprocessor.py). English is skipped — no instruction needed since it's the default.
    _LANGUAGE_NAMES: dict[str, str] = {
        "de": "German", "zh": "Chinese", "es": "Spanish", "fr": "French",
        "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "it": "Italian", "tr": "Turkish", "vi": "Vietnamese", "id": "Indonesian",
        "pl": "Polish", "nl": "Dutch", "ar": "Arabic", "hi": "Hindi",
        "th": "Thai", "cs": "Czech", "sv": "Swedish",
    }
    output_language_code = preprocessing_results.output_language or "en"
    if output_language_code != "en":
        language_name = _LANGUAGE_NAMES.get(output_language_code, output_language_code)
        prompt_parts.append(
            f"IMPORTANT: The user is communicating in {language_name}. "
            f"You MUST respond entirely in {language_name}. "
            f"Do not switch to any other language under any circumstances."
        )
        logger.debug(f"{log_prefix} Added language enforcement instruction for '{output_language_code}' ({language_name}).")

    full_system_prompt = "\n\n".join(filter(None, prompt_parts))
    
    # Generate tool definitions from discovered apps using the tool generator
    # Filter by preselected skills from preprocessing (architecture: only preselected skills are forwarded)
    # Note: preselected_skills was already built earlier (before app instruction injection)
    # so it's available here for tool generation.
    assigned_app_ids = selected_mate_config.assigned_apps if selected_mate_config else None
    
    # Initialize TranslationService to resolve skill descriptions from translation keys
    # TranslationService caches translations internally, so it's safe to create a new instance
    translation_service = TranslationService()
    
    available_tools_for_llm = generate_tools_from_apps(
        discovered_apps_metadata=discovered_apps_metadata,
        assigned_app_ids=assigned_app_ids,
        preselected_skills=preselected_skills,
        translation_service=translation_service
    )
    
    # --- Add focus mode tools if relevant ---
    # Focus modes are treated as special system tools that change the AI's behavior
    # activate_focus_mode: only when relevant focus modes exist AND no focus mode is active
    # deactivate_focus_mode: only when a focus mode is currently active
    
    relevant_focus_modes = preprocessing_results.relevant_focus_modes if hasattr(preprocessing_results, 'relevant_focus_modes') else []
    has_active_focus_mode = bool(request_data.active_focus_id)
    # Whether the user explicitly specified this focus mode via @focus:app:id mention
    user_requested_focus_only = getattr(preprocessing_results, 'user_requested_focus_only', False)
    
    if relevant_focus_modes and not has_active_focus_mode:
        # Build enum and descriptions for activate_focus_mode tool
        focus_mode_descriptions = []
        for focus_id in relevant_focus_modes:
            try:
                app_id, mode_id = focus_id.split('-', 1)
                app_metadata = discovered_apps_metadata.get(app_id)
                if app_metadata and app_metadata.focuses:
                    for focus in app_metadata.focuses:
                        if focus.id == mode_id:
                            # Get translated description
                            description = translation_service.get_nested_translation(focus.description_translation_key) or focus.description_translation_key
                            focus_mode_descriptions.append(f"- {focus_id}: {description}")
                            break
            except Exception as e:
                logger.warning(f"{log_prefix} Error building description for focus mode {focus_id}: {e}")
        
        activate_tool = {
            "type": "function",
            "function": {
                "name": "system-activate_focus_mode",
                "description": "Activate a focus mode to specialize the assistant's behavior for a specific task. Focus modes provide specialized instructions that help with particular types of requests.\n\nAvailable focus modes:\n" + "\n".join(focus_mode_descriptions) if focus_mode_descriptions else "Activate a focus mode to specialize the assistant's behavior.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "focus_id": {
                            "type": "string",
                            "description": "The focus mode to activate (format: app_id-focus_id)",
                            "enum": relevant_focus_modes
                        }
                    },
                    "required": ["focus_id"]
                }
            }
        }
        available_tools_for_llm.append(activate_tool)
        logger.info(f"{log_prefix} Added activate_focus_mode tool with {len(relevant_focus_modes)} available focus mode(s): {relevant_focus_modes}")
    
    if has_active_focus_mode:
        # Add deactivate tool when a focus mode is active
        deactivate_tool = {
            "type": "function",
            "function": {
                "name": "system-deactivate_focus_mode",
                "description": f"Deactivate the current focus mode ({request_data.active_focus_id}) and return to normal assistant behavior. Use this when the user no longer needs the specialized focus mode or asks to exit it.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        available_tools_for_llm.append(deactivate_tool)
        logger.info(f"{log_prefix} Added deactivate_focus_mode tool (current focus: {request_data.active_focus_id})")
    
    # Log available tools for debugging
    tool_names = [tool["function"]["name"] for tool in available_tools_for_llm]
    logger.info(f"{log_prefix} Available tools for main processing LLM: {len(available_tools_for_llm)} total")
    logger.debug(f"{log_prefix} Tool names: {', '.join(tool_names) if tool_names else 'None'}")
    if preselected_skills:
        logger.info(f"{log_prefix} Using preselected skills filter: {preselected_skills}")
    if assigned_app_ids:
        logger.info(f"{log_prefix} Using assigned apps filter: {assigned_app_ids}")

    # Build a robust tool resolver map to handle LLM hallucinations (e.g., underscores instead of hyphens)
    # Maps tool_name (and variants) -> (app_id, skill_id)
    tool_resolver_map: Dict[str, tuple[str, str]] = {}
    
    # Iterate through all discovered apps and skills to build the map
    # We use discovered_apps_metadata instead of available_tools_for_llm to ensure we catch all valid skills
    # even if they weren't generated as tools for this specific turn (though usually they should match)
    for app_id, app_metadata in discovered_apps_metadata.items():
        if not app_metadata or not app_metadata.skills:
            continue
            
        for skill in app_metadata.skills:
            # Standard hyphenated name: app-skill (e.g., "web-search")
            hyphen_name = f"{app_id}-{skill.id}"
            tool_resolver_map[hyphen_name] = (app_id, skill.id)
            
            # Underscore variant: app_skill (e.g., "web_search") - common LLM hallucination
            underscore_name = f"{app_id}_{skill.id}"
            tool_resolver_map[underscore_name] = (app_id, skill.id)
            
            # Also map the skill ID directly if it's unique? No, that might be risky.
            # But we can map just the skill ID if the app ID is implicit? No, explicit is better.

    current_message_history: List[Dict[str, Any]] = [msg.model_dump(exclude_none=True) for msg in request_data.message_history]
    
    # Truncate message history to fit within the conversation token budget.
    # This ensures the main LLM receives the most recent context within its context window,
    # dropping oldest messages first when history exceeds the limit.
    current_message_history = truncate_message_history_to_token_budget(
        current_message_history,
        max_tokens=APPROX_MAX_CONVERSATION_TOKENS,
    )
    
    # Track all tool calls for code block generation
    # This will be used to prepend a code block with skill input/output/metadata to the assistant response
    tool_calls_info: List[Dict[str, Any]] = []

    # Track embed IDs that failed (error/cancelled) during skill execution.
    # These will be yielded at the end of the stream so the stream_consumer can
    # strip their embed references from the final message content.
    # Without this, the message markdown would contain embed references for embeds
    # that no longer exist, causing the client to re-request them on every page load.
    failed_embed_ids: set[str] = set()
    
    # --- Yield debug metadata for the inspection script ---
    # This provides the full system prompt, tool definitions, and truncated message history
    # to the stream consumer, which passes it back to ask_skill_task for debug caching.
    # Only the first + last 3 messages are included to keep the debug entry manageable.
    DEBUG_MSG_HISTORY_HEAD = 1  # First message (usually system context or first user message)
    DEBUG_MSG_HISTORY_TAIL = 3  # Last 3 messages (most recent context)
    if len(current_message_history) <= DEBUG_MSG_HISTORY_HEAD + DEBUG_MSG_HISTORY_TAIL:
        debug_message_history = current_message_history
    else:
        debug_message_history = (
            current_message_history[:DEBUG_MSG_HISTORY_HEAD]
            + [{"__truncated__": True, "omitted_messages": len(current_message_history) - DEBUG_MSG_HISTORY_HEAD - DEBUG_MSG_HISTORY_TAIL}]
            + current_message_history[-DEBUG_MSG_HISTORY_TAIL:]
        )
    
    # Build concise tool summaries (name + first 120 chars of description)
    TOOL_DESCRIPTION_PREVIEW_LENGTH = 120
    debug_tool_summaries = []
    for tool in available_tools_for_llm:
        func = tool.get("function", {})
        desc = func.get("description", "")
        debug_tool_summaries.append({
            "name": func.get("name", "unknown"),
            "description_preview": desc[:TOOL_DESCRIPTION_PREVIEW_LENGTH] + ("..." if len(desc) > TOOL_DESCRIPTION_PREVIEW_LENGTH else ""),
        })
    
    yield {
        "__debug_metadata__": True,
        "system_prompt": full_system_prompt,
        "system_prompt_char_count": len(full_system_prompt),
        "available_tools": debug_tool_summaries,
        "available_tools_count": len(available_tools_for_llm),
        "message_history_sent_to_llm": debug_message_history,
        "message_history_total_count": len(current_message_history),
    }
    
    # --- End of existing logic ---

    # --- User-requested focus mode: bypass LLM + countdown ---
    # When the user explicitly mentioned a focus mode via @focus:app_id:focus_id in their message,
    # we skip the normal flow (LLM deciding to call activate_focus_mode, 5s countdown) and
    # directly activate the focus mode with countdown=0 (immediate).
    # This mirrors the exact same activation pipeline used in the deferred path, but without delay.
    if user_requested_focus_only and relevant_focus_modes and not has_active_focus_mode:
        focus_id = relevant_focus_modes[0]  # Only one can be selected per the UI constraint
        logger.info(
            f"{log_prefix} [FOCUS_MODE_OVERRIDE] User explicitly requested focus mode '{focus_id}' via @mention. "
            f"Bypassing LLM tool call and countdown — activating immediately."
        )

        # Create the focus mode activation embed (same as the LLM-initiated path)
        fm_embed_id = None
        if cache_service and user_vault_key_id and directus_service:
            try:
                from backend.core.api.app.services.embed_service import EmbedService
                embed_service = EmbedService(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service
                )

                # Resolve the translated focus mode display name
                focus_mode_display_name = focus_id  # fallback
                try:
                    fm_app_id, fm_mode_id = focus_id.split('-', 1)
                    user_language = preprocessing_results.output_language or "en"
                    fm_app_metadata = discovered_apps_metadata.get(fm_app_id)
                    if fm_app_metadata and fm_app_metadata.focuses:
                        for fm_def in fm_app_metadata.focuses:
                            if fm_def.id == fm_mode_id:
                                focus_mode_display_name = translation_service.get_nested_translation(
                                    fm_def.name_translation_key, lang=user_language
                                ) or ""
                                if not focus_mode_display_name and user_language != "en":
                                    focus_mode_display_name = translation_service.get_nested_translation(
                                        fm_def.name_translation_key, lang="en"
                                    ) or fm_def.name_translation_key
                                elif not focus_mode_display_name:
                                    focus_mode_display_name = fm_def.name_translation_key
                                break
                except Exception:
                    pass

                fm_embed_data = await embed_service.create_focus_mode_activation_embed(
                    focus_id=focus_id,
                    app_id=focus_id.split('-', 1)[0] if '-' in focus_id else focus_id,
                    focus_mode_name=focus_mode_display_name,
                    chat_id=request_data.chat_id,
                    message_id=request_data.message_id,
                    user_id=request_data.user_id,
                    user_id_hash=request_data.user_id_hash,
                    user_vault_key_id=user_vault_key_id,
                    task_id=task_id,
                    log_prefix=log_prefix
                )

                if fm_embed_data:
                    fm_embed_id = fm_embed_data.get("embed_id")
                    fm_embed_ref = fm_embed_data.get("embed_reference")
                    if fm_embed_ref:
                        yield f"```json\n{fm_embed_ref}\n```\n\n"
                        logger.info(
                            f"{log_prefix} [FOCUS_MODE_OVERRIDE] Yielded focus mode activation embed "
                            f"(embed_id={fm_embed_id})"
                        )
            except Exception as embed_error:
                logger.error(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Error creating focus mode embed: {embed_error}",
                    exc_info=True
                )

        # Load focus mode system prompt (same as the LLM-initiated path)
        focus_prompt_text = ""
        try:
            focus_app_id, focus_mode_id = focus_id.split('-', 1)
            translation_key = f"focus_modes.{focus_app_id}_{focus_mode_id}.systemprompt"
            user_language = preprocessing_results.output_language or "en"
            focus_prompt_text = translation_service.get_nested_translation(translation_key, lang=user_language) or ""
            if not focus_prompt_text and user_language != "en":
                focus_prompt_text = translation_service.get_nested_translation(translation_key, lang="en") or ""
                logger.info(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Loaded focus prompt in fallback language (en) "
                    f"({len(focus_prompt_text)} chars)"
                )
            else:
                logger.info(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Loaded focus prompt in user language ({user_language}) "
                    f"({len(focus_prompt_text)} chars)"
                )
        except Exception as e:
            logger.error(f"{log_prefix} [FOCUS_MODE_OVERRIDE] Error loading focus prompt: {e}", exc_info=True)

        # Store pending activation context in Redis (same structure as the LLM-initiated path)
        if cache_service:
            try:
                pending_context = {
                    "focus_id": focus_id,
                    "focus_prompt": focus_prompt_text,
                    "embed_id": fm_embed_id,
                    "chat_id": request_data.chat_id,
                    "message_id": request_data.message_id,
                    "user_id": request_data.user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "mate_id": preprocessing_results.selected_mate_id or request_data.mate_id,
                    "chat_has_title": request_data.chat_has_title,
                    "is_incognito": getattr(request_data, 'is_incognito', False),
                    "task_id": task_id,
                }
                await cache_service.store_pending_focus_activation(
                    chat_id=request_data.chat_id,
                    context=pending_context,
                )
                logger.info(f"{log_prefix} [FOCUS_MODE_OVERRIDE] Stored pending focus activation context")
            except Exception as e:
                logger.error(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Failed to store pending context: {e}",
                    exc_info=True
                )

        # Schedule auto-confirm task with countdown=0 (immediate, no user-facing countdown delay)
        # The standard 5-second countdown is skipped because the user explicitly chose this focus mode.
        try:
            from backend.core.api.app.tasks.celery_config import app as celery_app_instance
            celery_app_instance.send_task(
                'apps.ai.tasks.focus_mode_auto_confirm',
                kwargs={
                    "chat_id": request_data.chat_id,
                },
                queue='app_ai',
                countdown=0,  # Immediate — user explicitly requested this focus mode, no countdown needed
            )
            logger.info(
                f"{log_prefix} [FOCUS_MODE_OVERRIDE] Scheduled auto-confirm task with countdown=0 "
                f"(user-requested focus mode '{focus_id}' bypasses the 5s countdown)"
            )
        except Exception as e:
            logger.error(
                f"{log_prefix} [FOCUS_MODE_OVERRIDE] Failed to schedule auto-confirm task: {e}",
                exc_info=True
            )

        # Yield the same special marker and return — stream_consumer handles this identically
        # to the LLM-initiated path (no error, awaiting continuation from auto-confirm task)
        logger.info(
            f"{log_prefix} [FOCUS_MODE_OVERRIDE] Yielding pending marker and returning — "
            f"auto-confirm fires immediately for user-requested focus mode '{focus_id}'"
        )
        yield {"__awaiting_focus_mode_confirmation__": True, "focus_id": focus_id, "chat_id": request_data.chat_id}
        return

    # Validate that we have a model_id before proceeding with main processing
    # This prevents crashes when preprocessing fails and model_id is None
    if not preprocessing_results.selected_main_llm_model_id:
        error_msg = (
            f"{log_prefix} Cannot proceed with main processing: selected_main_llm_model_id is None. "
            f"This usually indicates preprocessing failed (rejection_reason: {preprocessing_results.rejection_reason}). "
            f"Main processing requires a valid model_id."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # === BUILD MODEL FALLBACK LIST ===
    # Create ordered list of models to try: primary -> secondary -> fallback
    # This enables automatic retry with different models if the primary fails
    models_to_try: List[str] = []
    if preprocessing_results.selected_main_llm_model_id:
        models_to_try.append(preprocessing_results.selected_main_llm_model_id)
    if preprocessing_results.selected_secondary_model_id:
        if preprocessing_results.selected_secondary_model_id not in models_to_try:
            models_to_try.append(preprocessing_results.selected_secondary_model_id)
    if preprocessing_results.selected_fallback_model_id:
        if preprocessing_results.selected_fallback_model_id not in models_to_try:
            models_to_try.append(preprocessing_results.selected_fallback_model_id)

    # Track which model we're currently using (may change if we need to fallback)
    current_model_index = 0
    current_model_id = models_to_try[0] if models_to_try else preprocessing_results.selected_main_llm_model_id

    logger.info(
        f"{log_prefix} MODEL_FALLBACK: Prepared {len(models_to_try)} model(s) to try: {models_to_try}. "
        f"Starting with: {current_model_id}"
    )

    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None

    # === CUMULATIVE TOKEN TRACKING ACROSS ALL LLM ITERATIONS ===
    # When tool calls are involved, the LLM is called multiple times per user turn:
    # once to decide which tools to use, and again after receiving tool results.
    # Each intermediate call sends the full (growing) chat history plus all tool results
    # accumulated so far, so each call incurs real API token costs.
    #
    # We accumulate the token counts from every LLM call in this turn so the user is
    # billed for the true total rather than only the final iteration's tokens.
    # The final `usage` object from the last iteration is still used for provider/model
    # metadata — only its token counts are replaced by these cumulative totals.
    #
    # `tool_inference_iterations` counts how many EXTRA LLM calls were triggered by
    # tool use (i.e., total iterations minus 1).  A value of 0 means no tool calls
    # were made (single LLM call, baseline behaviour).  This is stored in the usage
    # entry so users can see it in Settings → Usage detail view.
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    tool_inference_iterations: int = 0  # Number of extra LLM calls caused by tool use

    # === SKILL CALL BUDGET TRACKING ===
    # Track total skill calls across all iterations to prevent runaway research loops.
    # Each request within a tool call counts as one skill call.
    total_skill_calls = 0
    streaming_skill_count = 0  # Mirrors total_skill_calls during streaming to suppress over-budget placeholders
    budget_warning_injected = False
    images_search_executed = False  # Track whether images-search ran, to inject embed preview instruction
    force_no_tools = False  # When True, force tool_choice="none" to make LLM answer with gathered info
    
    # === SKILL CALL DEDUPLICATION ===
    # Track successfully completed skill calls to prevent duplicate executions.
    # Some LLMs (especially Gemini) repeatedly call the same tool across iterations
    # even after receiving a successful result. This wastes credits and creates
    # duplicate side effects (e.g., multiple reminders for "set me a reminder").
    # Key: hash of (app_id, skill_id, arguments), Value: dict with results and embed_id
    completed_skill_calls: Dict[str, Dict[str, Any]] = {}
    
    for iteration in range(MAX_TOOL_CALL_ITERATIONS):
        logger.info(f"{log_prefix} LLM call iteration {iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}, total_skill_calls={total_skill_calls}")
        
        # === LAST ITERATION SAFETY CHECK ===
        # If we're on the last iteration, always force no tools to ensure we get an answer.
        # This acts as a safety net in case the budget limits weren't reached.
        if iteration == MAX_TOOL_CALL_ITERATIONS - 1 and not force_no_tools:
            force_no_tools = True
            if not budget_warning_injected:
                budget_warning_injected = True
            logger.info(
                f"{log_prefix} [MAX_ITERATIONS] Last iteration ({iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}) - "
                f"forcing tool_choice='none' to ensure final answer is generated."
            )
        
        # Determine tool_choice based on budget state
        # If we've hit the hard limit or this is the last iteration, force the LLM to answer without tools
        if force_no_tools:
            current_tool_choice = "none"
            logger.info(
                f"{log_prefix} [SKILL_BUDGET] Forcing tool_choice='none' - LLM must answer with gathered information "
                f"(total_skill_calls={total_skill_calls}, hard_limit={HARD_LIMIT_SKILL_CALLS})"
            )
        else:
            current_tool_choice = "auto"
        
        # Build system prompt for this iteration
        # Inject budget warning if we've exceeded the soft limit
        iteration_system_prompt = full_system_prompt
        if budget_warning_injected:
            budget_warning = (
                "\n\n--- IMPORTANT: Research Budget Limit ---\n"
                "You have used most of your available research calls for this response. "
                "Please provide the best possible answer using the information you have already gathered. "
                "If you need more information to fully answer the user's question, suggest specific follow-up questions "
                "the user could ask, rather than making additional research calls.\n"
                "--- End Research Budget Warning ---\n"
            )
            iteration_system_prompt = full_system_prompt + budget_warning
            logger.info(f"{log_prefix} [SKILL_BUDGET] Injected budget warning into system prompt")

        # Inject embed preview instruction when images-search was executed
        if images_search_executed:
            image_embed_instruction = (
                "\n\n--- IMPORTANT: Image Search Results Available ---\n"
                "You have image search results available. You MUST include them visually in your response "
                "using large embed preview cards. For each relevant image result, use the syntax:\n"
                "[!](embed:embed_ref)\n"
                "Place each image card on its own line. When showing multiple images, place them consecutively "
                "to create a carousel. Use the embed_ref values from the image search tool results.\n"
                "--- End Image Search Instructions ---\n"
            )
            iteration_system_prompt = iteration_system_prompt + image_embed_instruction
            logger.info(f"{log_prefix} [IMAGE_SEARCH] Injected embed preview instruction into system prompt")

        # === MODEL FALLBACK RETRY LOGIC ===
        # Try models in sequence until one succeeds or all fail
        # This handles transient API errors, rate limits, and model availability issues
        llm_stream = None
        model_fallback_attempts = 0
        last_model_error = None

        while current_model_index < len(models_to_try):
            try:
                current_model_id = models_to_try[current_model_index]
                model_fallback_attempts += 1

                if model_fallback_attempts > 1:
                    logger.warning(
                        f"{log_prefix} MODEL_FALLBACK: Attempting fallback model #{current_model_index + 1}: {current_model_id} "
                        f"(previous error: {last_model_error})"
                    )

                llm_stream = call_main_llm_stream(
                    task_id=task_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    model_id=current_model_id,  # Use current_model_id from fallback list
                    temperature=preprocessing_results.llm_response_temp,
                    secrets_manager=secrets_manager,
                    tools=available_tools_for_llm if not force_no_tools else None,
                    tool_choice=current_tool_choice
                )
                # Stream created successfully - break out of retry loop
                break

            except Exception as model_error:
                last_model_error = str(model_error)
                logger.error(
                    f"{log_prefix} MODEL_FALLBACK: Model {current_model_id} failed: {model_error}. "
                    f"Trying next model..."
                )
                current_model_index += 1

                # If we've exhausted all models, raise the last error
                if current_model_index >= len(models_to_try):
                    logger.error(
                        f"{log_prefix} MODEL_FALLBACK: All {len(models_to_try)} models failed. "
                        f"Last error: {last_model_error}"
                    )
                    raise RuntimeError(
                        f"All models failed. Tried: {models_to_try}. Last error: {last_model_error}"
                    ) from model_error

        current_turn_text_buffer = []
        tool_calls_for_this_turn: List[Union[ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedBedrockToolCall, ParsedOpenAIToolCall]] = []
        llm_turn_had_content = False
        
        # Dictionary to store placeholder embeds created for tool calls during stream processing
        # Key: tool_call_id, Value: placeholder_embed_data dict
        # This allows us to create placeholders IMMEDIATELY when tool calls are detected,
        # showing the "processing" state to users before skill execution starts
        inline_placeholder_embeds: Dict[str, Dict[str, Any]] = {}

        # Sync streaming budget counter with execution-phase counter at each iteration start
        # so it carries over correctly from previous iterations
        streaming_skill_count = total_skill_calls
        
        # Flag set when AllServersFailedError is caught during stream consumption.
        # When set, the outer loop will attempt the next model in the fallback list.
        _stream_all_servers_failed = False
        _stream_all_servers_error: Optional[AllServersFailedError] = None
        try:
          async for chunk in aggregate_paragraphs(llm_stream):
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, BedrockUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                # Accumulate token counts from every LLM call in this turn.
                # Each tool-use iteration re-sends the full history plus tool results,
                # so all iterations contribute real API costs that must be billed.
                _iter_input = 0
                _iter_output = 0
                if isinstance(chunk, MistralUsage):
                    _iter_input = chunk.prompt_tokens or 0
                    _iter_output = chunk.completion_tokens or 0
                elif isinstance(chunk, GoogleUsageMetadata):
                    _iter_input = chunk.prompt_token_count or 0
                    _iter_output = chunk.candidates_token_count or 0
                elif isinstance(chunk, (AnthropicUsageMetadata, BedrockUsageMetadata)):
                    _iter_input = chunk.input_tokens or 0
                    _iter_output = chunk.output_tokens or 0
                elif isinstance(chunk, OpenAIUsageMetadata):
                    _iter_input = chunk.input_tokens or 0
                    _iter_output = chunk.output_tokens or 0
                cumulative_input_tokens += _iter_input
                cumulative_output_tokens += _iter_output
                logger.debug(
                    f"{log_prefix} [CUMULATIVE_TOKENS] Iteration {iteration + 1}: "
                    f"+{_iter_input} input, +{_iter_output} output tokens. "
                    f"Running totals: {cumulative_input_tokens} in / {cumulative_output_tokens} out"
                )
                continue
            if isinstance(chunk, (ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedBedrockToolCall, ParsedOpenAIToolCall)):
                tool_calls_for_this_turn.append(chunk)
                
                # === IMMEDIATE PLACEHOLDER CREATION ===
                # Create and yield the embed placeholder as soon as a tool call is detected
                # This shows the "processing" state to users BEFORE skill execution starts
                try:
                    tool_name = chunk.function_name
                    tool_arguments_str = chunk.function_arguments_raw
                    tool_call_id = chunk.tool_call_id
                    
                    # Parse arguments to extract metadata for placeholder
                    try:
                        parsed_args = json.loads(tool_arguments_str)
                    except json.JSONDecodeError:
                        parsed_args = {}
                        logger.warning(f"{log_prefix} Failed to parse tool arguments for inline placeholder, using empty dict")
                    
                    # Resolve tool name to app_id and skill_id
                    resolved_tool = tool_resolver_map.get(tool_name)
                    if resolved_tool:
                        app_id, skill_id = resolved_tool
                    else:
                        # Fallback parsing
                        if '-' in tool_name:
                            app_id, skill_id = tool_name.split('-', 1)
                        elif '_' in tool_name:
                            app_id, skill_id = tool_name.split('_', 1)
                        else:
                            app_id, skill_id = "unknown", "unknown"
                    
                    # === DEDUPLICATION CHECK (INLINE PLACEHOLDER PHASE) ===
                    # Check if this exact skill call was already executed in a previous iteration.
                    # If so, skip creating placeholder - the execution phase will also skip it.
                    # This prevents duplicate embeds from appearing in the stream.
                    call_hash = _hash_skill_arguments(app_id, skill_id, parsed_args)
                    if call_hash in completed_skill_calls:
                        logger.info(
                            f"{log_prefix} INLINE: [DEDUP] Skipping placeholder for duplicate '{app_id}.{skill_id}' "
                            f"(hash={call_hash[:8]}...). Already executed successfully in a previous iteration."
                        )
                        # Don't create placeholder embed - skip to next chunk
                        # The execution phase will also detect this duplicate and skip execution
                        continue
                    
                    # === STREAMING-PHASE BUDGET CHECK ===
                    # Count requests in this tool call to check against budget.
                    # Skip placeholder creation entirely when the budget would be exceeded,
                    # preventing phantom "Searching..." cards that flash then transition to error.
                    _streaming_requests_count = 1
                    _streaming_requests_list = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                    if isinstance(_streaming_requests_list, list) and len(_streaming_requests_list) > 0:
                        _streaming_requests_count = len(_streaming_requests_list)

                    if app_id != "system" and (
                        streaming_skill_count >= HARD_LIMIT_SKILL_CALLS
                        or streaming_skill_count + _streaming_requests_count > HARD_LIMIT_SKILL_CALLS
                    ):
                        logger.info(
                            f"{log_prefix} INLINE: [BUDGET_SKIP] Suppressing placeholder for '{tool_name}' "
                            f"({_streaming_requests_count} requests) - would exceed budget "
                            f"(streaming_skill_count={streaming_skill_count}, limit={HARD_LIMIT_SKILL_CALLS})"
                        )
                        continue  # Skip placeholder creation entirely

                    # Create placeholder embed IMMEDIATELY (before skill execution)
                    # Skip for system tools (e.g., activate_focus_mode, deactivate_focus_mode)
                    # because they create their own specific embed types (focus_mode_activation)
                    # rather than the generic app_skill_use placeholder
                    if cache_service and user_vault_key_id and directus_service and app_id != "unknown" and app_id != "system":
                        from backend.core.api.app.services.embed_service import EmbedService
                        
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        
                        # Extract metadata for placeholder display
                        # Handle both direct args (query) and nested args (requests[0].query)
                        # CRITICAL: This metadata is included in the embed placeholder so the frontend
                        # can display the query immediately while the skill executes
                        
                        # Check if we have multiple requests
                        requests_list = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                        is_multiple_requests = isinstance(requests_list, list) and len(requests_list) > 1
                        
                        if is_multiple_requests:
                            # MULTIPLE REQUESTS: Create one placeholder per request
                            logger.info(
                                f"{log_prefix} INLINE: Detected {len(requests_list)} requests, creating placeholders for each"
                            )
                            
                            # Store multiple placeholders - key by request index/id for later matching
                            placeholder_embeds_list = []
                            
                            for request_idx, request in enumerate(requests_list):
                                if not isinstance(request, dict):
                                    continue
                                
                                # Extract ALL input parameters for this specific request
                                # This ensures placeholders include all relevant metadata (query, url, languages, etc.)
                                # not just query and provider
                                request_metadata = {}
                                
                                # Copy all input parameters from the request to metadata
                                # This preserves all skill-specific parameters (url for videos, query for search, etc.)
                                for key, value in request.items():
                                    # Skip internal metadata fields (id is handled separately)
                                    if key != "id":
                                        request_metadata[key] = value
                                
                                # Provider from request or fallback (for search skills).
                                # Validate against the skill's known providers list to prevent
                                # LLM hallucination (e.g. 'Brave Search' for the events skill).
                                raw_provider = request_metadata.get("provider")
                                if raw_provider is not None or skill_id == "search":
                                    validated_provider = _validate_skill_provider(
                                        provider=raw_provider,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        discovered_apps_metadata=discovered_apps_metadata,
                                        log_prefix=log_prefix,
                                    )
                                    if validated_provider is not None:
                                        request_metadata["provider"] = validated_provider
                                
                                # Add request ID for later matching
                                # ALWAYS auto-generate 1-indexed IDs - ignore any LLM-provided IDs
                                # This ensures consistency between placeholder creation here and
                                # skill execution in base_skill.py which respects provided IDs
                                # LLMs may provide 0-indexed or arbitrary IDs despite schema instructions,
                                # so we enforce our own ID scheme for reliable matching
                                request_id = request_idx + 1
                                # SET the ID in the request dict so skill receives our auto-generated ID
                                # This overwrites any LLM-provided ID in the request
                                request["id"] = request_id
                                # Normalize to string for consistent matching (handles int/str mismatches)
                                request_id_normalized = str(request_id)
                                request_metadata["request_id"] = request_id
                                
                                # Log all extracted metadata for debugging
                                metadata_summary = ", ".join([f"{k}={v}" for k, v in request_metadata.items() if k != "request_id"])
                                logger.debug(
                                    f"{log_prefix} INLINE: Creating placeholder {request_idx + 1}/{len(requests_list)}: "
                                    f"request_id={request_id} (normalized={request_id_normalized}), metadata=[{metadata_summary}]"
                                )
                                
                                # Create placeholder for this request
                                placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    metadata=request_metadata,
                                    log_prefix=f"{log_prefix}[request_{request_idx}]"
                                )
                                
                                if placeholder_embed_data:
                                    # Store with normalized request ID for later matching
                                    placeholder_embed_data["request_id"] = request_id_normalized
                                    placeholder_embeds_list.append(placeholder_embed_data)
                                    
                                    # Yield embed reference immediately
                                    embed_reference_json = placeholder_embed_data.get("embed_reference")
                                    if embed_reference_json:
                                        embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                        yield embed_code_block
                                        logger.info(
                                            f"{log_prefix} INLINE: Created and yielded placeholder {request_idx + 1}/{len(requests_list)}: "
                                            f"embed_id={placeholder_embed_data.get('embed_id')}, "
                                            f"request_id={request_id}, "
                                            f"query_present={'query' in request_metadata}, "
                                            f"query_length={len(request_metadata.get('query')) if isinstance(request_metadata.get('query'), str) else 0}"
                                        )
                            
                            # Store list of placeholders for later matching
                            # CRITICAL: Also store the modified parsed_args with our auto-generated IDs
                            # This ensures the execution phase uses the same IDs we assigned here
                            # (parsed_args is parsed separately in both phases from the same tool_arguments_str)
                            if placeholder_embeds_list:
                                inline_placeholder_embeds[tool_call_id] = {
                                    "multiple": True,
                                    "placeholders": placeholder_embeds_list,
                                    "parsed_args": parsed_args  # Store with our modified request IDs
                                }
                                
                                # Publish "processing" status for all requests
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data={"request_count": len(placeholder_embeds_list)}
                                )

                                # Track streaming budget for multi-request placeholder
                                if app_id != "system":
                                    streaming_skill_count += _streaming_requests_count
                        else:
                            # SINGLE REQUEST: Extract ALL input parameters
                            # This ensures placeholders include all relevant metadata (query, url, languages, etc.)
                            # not just query and provider
                            metadata = {}
                            
                            # If we have a requests array with one item, extract all parameters from that
                            if requests_list and len(requests_list) > 0:
                                first_request = requests_list[0]
                                if isinstance(first_request, dict):
                                    # Copy all input parameters from the first request
                                    for key, value in first_request.items():
                                        if key != "id":  # Skip id field
                                            metadata[key] = value
                                    logger.debug(f"{log_prefix} INLINE: Extracted metadata from requests[0]: {list(metadata.keys())}")
                            else:
                                # Direct parameters (simple skill format without requests array)
                                # Copy all input parameters from parsed_args
                                for key, value in parsed_args.items():
                                    if key not in ['requests']:  # Skip requests array if present
                                        metadata[key] = value
                                logger.debug(f"{log_prefix} INLINE: Extracted metadata from direct args: {list(metadata.keys())}")
                            
                            # Provider validation for search skills.
                            # Validates the provider (from LLM args or absent) against the skill's
                            # known providers list in app.yml to prevent LLM hallucination.
                            if skill_id == "search" or "provider" in metadata:
                                validated_provider = _validate_skill_provider(
                                    provider=metadata.get("provider"),
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    discovered_apps_metadata=discovered_apps_metadata,
                                    log_prefix=log_prefix,
                                )
                                if validated_provider is not None:
                                    metadata["provider"] = validated_provider
                            
                            # Log final metadata for debugging
                            metadata_summary = ", ".join([f"{k}={v}" for k, v in metadata.items()])
                            logger.info(
                                f"{log_prefix} INLINE: Final metadata for placeholder: [{metadata_summary}]"
                            )
                            
                            # Create single placeholder
                            placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                metadata=metadata,
                                log_prefix=log_prefix
                            )
                            
                            if placeholder_embed_data:
                                # Store for later use during skill execution
                                inline_placeholder_embeds[tool_call_id] = placeholder_embed_data
                                
                                # CRITICAL: Yield the embed reference IMMEDIATELY as a code block chunk
                                # This ensures the frontend shows "processing" state BEFORE skill execution starts
                                # The code block format allows the frontend to parse and render the embed placeholder
                                embed_reference_json = placeholder_embed_data.get("embed_reference")
                                if embed_reference_json:
                                    embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                    # Yield immediately - this will be picked up by stream consumer and published right away
                                    yield embed_code_block
                                    
                                    logger.info(
                                        f"{log_prefix} INLINE: Created and yielded processing placeholder code block for '{tool_name}': "
                                        f"embed_id={placeholder_embed_data.get('embed_id')}, "
                                        f"code_block_length={len(embed_code_block)}"
                                    )
                                else:
                                    logger.warning(f"{log_prefix} INLINE: Placeholder embed_data missing embed_reference JSON")
                                
                                # Publish "processing" status immediately via Redis event
                                # This provides additional signal to frontend that skill is processing
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data=metadata  # Include query/provider in preview
                                )

                                # Track streaming budget for single-request placeholder
                                if app_id != "system":
                                    streaming_skill_count += _streaming_requests_count
                            else:
                                logger.warning(f"{log_prefix} INLINE: Failed to create placeholder embed for '{tool_name}'")
                except Exception as e:
                    # Don't fail the stream processing if inline placeholder creation fails
                    logger.error(f"{log_prefix} INLINE: Error creating placeholder during stream: {e}", exc_info=True)
                
            elif isinstance(chunk, UnifiedStreamChunk):
                # Handle thinking/reasoning content from models like Gemini 3 Pro
                # These chunks contain the model's internal reasoning process
                # Pass them through to stream_consumer which will publish to thinking Redis channel
                if chunk.type == StreamChunkType.THINKING:
                    # Thinking content - yield through for stream_consumer to handle
                    logger.debug(f"{log_prefix} Yielding thinking chunk ({len(chunk.content or '')} chars)")
                    yield chunk
                elif chunk.type == StreamChunkType.THINKING_SIGNATURE:
                    # Thinking signature - yield through for storage
                    logger.debug(f"{log_prefix} Yielding thinking signature")
                    yield chunk
                elif chunk.type == StreamChunkType.TEXT:
                    # Text content wrapped in UnifiedStreamChunk - extract and yield as string
                    llm_turn_had_content = True
                    if chunk.content:
                        yield chunk.content
                        if tool_calls_for_this_turn:
                            current_turn_text_buffer.append(chunk.content)
                else:
                    logger.warning(f"{log_prefix} Unknown UnifiedStreamChunk type: {chunk.type}")
            elif isinstance(chunk, str):
                llm_turn_had_content = True
                # CRITICAL: Always yield text chunks immediately, even when tool calls are pending
                # This ensures paragraph-by-paragraph streaming works correctly
                # Tool calls will be executed after the LLM finishes its turn, but text should stream immediately
                yield chunk
                # Also buffer for message history (needed for tool execution context)
                if tool_calls_for_this_turn:
                    current_turn_text_buffer.append(chunk)
            else:
                logger.warning(f"{log_prefix} Received unexpected chunk type from stream: {type(chunk)}")
        except AllServersFailedError as asf_err:
            # All servers for the current model failed before yielding any content.
            # Try the next model in the fallback list instead of showing an error.
            _stream_all_servers_failed = True
            _stream_all_servers_error = asf_err
            logger.warning(
                f"{log_prefix} MODEL_FALLBACK: AllServersFailedError during stream consumption "
                f"for model '{models_to_try[current_model_index]}': {asf_err}. "
                f"Will attempt next model if available."
            )

        # === MODEL FALLBACK AFTER STREAM FAILURE ===
        # If all servers failed for the current model during stream consumption,
        # try the next model in the fallback list before giving up.
        if _stream_all_servers_failed:
            current_model_index += 1
            if current_model_index < len(models_to_try):
                next_model = models_to_try[current_model_index]
                logger.warning(
                    f"{log_prefix} MODEL_FALLBACK: Switching to fallback model #{current_model_index + 1}: "
                    f"{next_model} (previous model failed: {_stream_all_servers_error})"
                )
                # Reset iteration state and continue the outer for loop
                # to retry with the next model on the same iteration
                continue
            else:
                # All models exhausted — yield standardized error to user
                logger.error(
                    f"{log_prefix} MODEL_FALLBACK: All {len(models_to_try)} models exhausted. "
                    f"Last error: {_stream_all_servers_error}"
                )
                yield STANDARDIZED_USER_ERROR_MESSAGE
                break

        final_buffered_text_for_turn = "".join(current_turn_text_buffer)

        if not tool_calls_for_this_turn:
            break

        # This iteration produced tool calls — the loop will continue with at least one
        # more LLM call to process the tool results.  Each such additional call re-sends
        # the full conversation history plus the new tool results, contributing real token
        # costs that we must bill.  Counting extra iterations here lets us surface this
        # information to the user in the usage detail view.
        tool_inference_iterations += 1
        logger.info(
            f"{log_prefix} [CUMULATIVE_TOKENS] Tool calls detected — incrementing tool_inference_iterations "
            f"to {tool_inference_iterations}."
        )

        logger.info(f"{log_prefix} Processing {len(tool_calls_for_this_turn)} tool call(s).")
        
        assistant_message_content_for_history = final_buffered_text_for_turn
        # Format tool calls for message history
        # CRITICAL: Include thought_signature for Gemini 3 thinking models - required for multi-turn function calling
        assistant_message_tool_calls_formatted = [
            {
                "id": tc.tool_call_id,
                "type": "function",
                "function": {"name": tc.function_name, "arguments": tc.function_arguments_raw},
                # Include thought_signature if present (for Gemini 3 thinking models)
                **({"thought_signature": tc.thought_signature} if hasattr(tc, 'thought_signature') and tc.thought_signature else {})
            }
            for tc in tool_calls_for_this_turn
        ]
        assistant_message: Dict[str, Any] = {"role": "assistant", "content": assistant_message_content_for_history or None, "tool_calls": assistant_message_tool_calls_formatted}
        current_message_history.append(assistant_message)

        # Execute all tool calls (skills) in this turn
        for tool_call in tool_calls_for_this_turn:
            tool_name = tool_call.function_name
            tool_arguments_str = tool_call.function_arguments_raw
            tool_call_id = tool_call.tool_call_id
            tool_result_content_str: str
            
            try:
                # Parse function arguments
                parsed_args = json.loads(tool_arguments_str)
                
                # Extract app_id and skill_id from tool name
                # Use the robust resolver map to handle name variations (hyphens vs underscores)
                resolved_tool = tool_resolver_map.get(tool_name)
                
                if resolved_tool:
                    app_id, skill_id = resolved_tool
                    logger.debug(f"{log_prefix} Resolved tool '{tool_name}' to app_id='{app_id}', skill_id='{skill_id}'")
                else:
                    # Fallback to standard splitting if not found in map (e.g. if map building failed or new pattern)
                    logger.warning(f"{log_prefix} Tool '{tool_name}' not found in resolver map. Attempting fallback split.")
                    try:
                        # Try splitting by hyphen first (standard)
                        if '-' in tool_name:
                            app_id, skill_id = tool_name.split('-', 1)
                        # Try splitting by underscore if hyphen fails (common hallucination)
                        elif '_' in tool_name:
                            app_id, skill_id = tool_name.split('_', 1)
                        else:
                            raise ValueError("No separator found")
                    except ValueError as e:
                        logger.error(f"{log_prefix} Invalid tool name format '{tool_name}': expected 'app_id-skill_id' format. Error: {e}")
                        raise ValueError(f"Invalid tool name format '{tool_name}': expected 'app_id-skill_id' format") from e
                
                # Validate that app_id and skill_id are non-empty after split
                # This ensures we have valid identifiers before proceeding with skill execution and billing
                if not app_id or not app_id.strip():
                    logger.error(f"{log_prefix} Empty app_id extracted from tool name '{tool_name}'. Cannot proceed with skill execution.")
                    raise ValueError(f"Empty app_id in tool name '{tool_name}'")
                
                if not skill_id or not skill_id.strip():
                    logger.error(f"{log_prefix} Empty skill_id extracted from tool name '{tool_name}'. Cannot proceed with skill execution.")
                    raise ValueError(f"Empty skill_id in tool name '{tool_name}'")
                
                # Normalize by stripping whitespace
                app_id = app_id.strip()
                skill_id = skill_id.strip()
                
                # === SKILL CALL BUDGET CHECK ===
                # Count requests in this tool call and check against hard limit.
                # If we've already reached the limit, skip this tool call entirely.
                # User won't see any indication that the tool call was skipped.
                requests_in_this_call = 1  # Default: single request
                requests_list_for_budget = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                if isinstance(requests_list_for_budget, list) and len(requests_list_for_budget) > 0:
                    requests_in_this_call = len(requests_list_for_budget)
                
                # Skip this tool call if we've already reached or would exceed the hard limit
                # We don't count system tools (focus mode) against the budget
                # CRITICAL: Also check if this call WOULD exceed the limit (not just if limit is already reached)
                # This prevents a single tool call with multiple requests from exceeding the budget
                if app_id != "system" and (total_skill_calls >= HARD_LIMIT_SKILL_CALLS or total_skill_calls + requests_in_this_call > HARD_LIMIT_SKILL_CALLS):
                    logger.info(
                        f"{log_prefix} [SKILL_BUDGET] Skipping tool call '{tool_name}' with {requests_in_this_call} request(s) - "
                        f"would exceed hard limit (total_skill_calls={total_skill_calls}+{requests_in_this_call}={total_skill_calls + requests_in_this_call}, limit={HARD_LIMIT_SKILL_CALLS})"
                    )
                    # Add a tool response to history so the LLM knows this tool was skipped
                    # but the user won't see any placeholder or error
                    tool_response_message = {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "skipped",
                            "reason": "Research limit reached for this response. Use gathered information to answer."
                        })
                    }
                    current_message_history.append(tool_response_message)
                    # Set force_no_tools to prevent further tool calls
                    force_no_tools = True

                    # === SAFETY NET: Cancel any orphaned placeholder embeds ===
                    # With the streaming-phase budget check, orphaned placeholders should be rare.
                    # This handles edge cases where a placeholder slipped through (e.g., counter
                    # desync between streaming and execution phases). Use "cancelled" instead of
                    # "error" for a cleaner UX — the frontend silently removes cancelled embeds.
                    orphaned_placeholder = inline_placeholder_embeds.get(tool_call_id)
                    if orphaned_placeholder and cache_service and user_vault_key_id and directus_service:
                        try:
                            from backend.core.api.app.services.embed_service import EmbedService
                            _budget_embed_service = EmbedService(
                                cache_service=cache_service,
                                directus_service=directus_service,
                                encryption_service=encryption_service
                            )

                            # Collect embed IDs from both single and multi-request placeholders
                            _orphaned_ids = []
                            if isinstance(orphaned_placeholder, dict) and orphaned_placeholder.get("multiple"):
                                for _p in orphaned_placeholder.get("placeholders", []):
                                    _eid = _p.get("embed_id") if isinstance(_p, dict) else None
                                    if _eid:
                                        _orphaned_ids.append(_eid)
                            elif isinstance(orphaned_placeholder, dict) and "embed_id" in orphaned_placeholder:
                                _orphaned_ids.append(orphaned_placeholder["embed_id"])

                            for _eid in _orphaned_ids:
                                await _budget_embed_service.update_embed_status_to_cancelled(
                                    embed_id=_eid,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                            if _orphaned_ids:
                                logger.warning(
                                    f"{log_prefix} [SKILL_BUDGET] Cancelled {len(_orphaned_ids)} orphaned placeholder(s) "
                                    f"for '{tool_name}' — streaming budget check should have prevented these"
                                )
                        except Exception as _budget_err:
                            logger.warning(
                                f"{log_prefix} [SKILL_BUDGET] Failed to cancel orphaned placeholder: {_budget_err}"
                            )

                    continue  # Skip to next tool call
                
                # === DEDUPLICATION CHECK (EXECUTION PHASE) ===
                # Check if this exact skill call was already executed in a previous iteration.
                # If so, skip execution and return the previous result to the LLM.
                # This prevents duplicate side effects (e.g., multiple reminders) and wasted credits.
                call_hash = _hash_skill_arguments(app_id, skill_id, parsed_args)
                if call_hash in completed_skill_calls:
                    previous_result = completed_skill_calls[call_hash]
                    logger.info(
                        f"{log_prefix} [DEDUP] Skipping duplicate '{app_id}.{skill_id}' (hash={call_hash[:8]}...). "
                        f"Returning cached result from previous iteration."
                    )
                    # Return a synthetic tool result telling the LLM this was already done
                    # This is NOT visible to users - it's only in the LLM message history
                    tool_response_message = {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "already_completed",
                            "message": f"This {skill_id} action was already performed successfully earlier in this response. "
                                       f"No need to call it again with the same parameters.",
                            "previous_embed_id": previous_result.get("embed_id")
                        })
                    }
                    current_message_history.append(tool_response_message)
                    continue  # Skip to next tool call
                
                # Update budget counters (only for non-system tools)
                if app_id != "system":
                    total_skill_calls += requests_in_this_call
                    logger.info(
                        f"{log_prefix} [SKILL_BUDGET] Executing '{tool_name}' with {requests_in_this_call} request(s), "
                        f"total now: {total_skill_calls}/{HARD_LIMIT_SKILL_CALLS}"
                    )
                    
                    # Check if we've reached the soft limit - inject warning for next iteration
                    if total_skill_calls >= SOFT_LIMIT_SKILL_CALLS and not budget_warning_injected:
                        budget_warning_injected = True
                        logger.info(
                            f"{log_prefix} [SKILL_BUDGET] Soft limit reached ({total_skill_calls} >= {SOFT_LIMIT_SKILL_CALLS}). "
                            f"Budget warning will be injected in next iteration."
                        )
                    
                    # Check if we've hit the hard limit - force no tools for next iteration
                    if total_skill_calls >= HARD_LIMIT_SKILL_CALLS:
                        force_no_tools = True
                        logger.info(
                            f"{log_prefix} [SKILL_BUDGET] Hard limit reached ({total_skill_calls} >= {HARD_LIMIT_SKILL_CALLS}). "
                            f"Next iteration will force tool_choice='none' to generate final answer."
                        )
                
                # --- Handle system tools (focus mode activation/deactivation) ---
                # System tools are special tools that modify the chat state rather than executing skills
                # They use app_id="system" to distinguish from regular app skills
                if app_id == "system":
                    if skill_id == "activate_focus_mode":
                        focus_id = parsed_args.get("focus_id")
                        logger.info(f"{log_prefix} [FOCUS_MODE] LLM requested focus mode activation: {focus_id}")
                        
                        # --- DEFERRED ACTIVATION ARCHITECTURE ---
                        # Instead of immediately activating focus mode and re-invoking the LLM,
                        # we store the pending context in Redis and schedule an auto-confirm
                        # Celery task with countdown=6s. This gives the user 4 seconds to reject
                        # (click or ESC on the countdown embed) before focus mode activates.
                        #
                        # Flow:
                        # 1. Create and yield the focus mode embed (user sees countdown)
                        # 2. Store pending activation context in Redis (30s TTL)
                        # 3. Schedule auto-confirm task (fires in 6s)
                        # 4. Yield special marker and return (task exits cleanly)
                        # 5a. If no rejection within 6s → auto-confirm task activates focus mode
                        #     and fires a new Celery task WITH focus prompt
                        # 5b. If user rejects → WebSocket handler consumes pending context (GETDEL)
                        #     and fires a new Celery task WITHOUT focus prompt
                        #
                        # DO NOT: set active_focus_id, update cache/Directus, inject focus prompt,
                        # or re-invoke the LLM here. All of that happens in the continuation task.
                        
                        # --- Create focus mode activation embed ---
                        # This embed is rendered by the frontend as a countdown indicator
                        # (4-3-2-1) that the user can click to reject the focus mode.
                        fm_embed_id = None
                        if cache_service and user_vault_key_id and directus_service:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(
                                    cache_service=cache_service,
                                    directus_service=directus_service,
                                    encryption_service=encryption_service
                                )
                                
                                # Resolve the translated focus mode name for UI display
                                # Load in the user's language (from preprocessing) with English fallback
                                focus_mode_display_name = focus_id  # fallback
                                try:
                                    fm_app_id, fm_mode_id = focus_id.split('-', 1)
                                    user_language = preprocessing_results.output_language or "en"
                                    fm_app_metadata = discovered_apps_metadata.get(fm_app_id)
                                    if fm_app_metadata and fm_app_metadata.focuses:
                                        for fm_def in fm_app_metadata.focuses:
                                            if fm_def.id == fm_mode_id:
                                                # Try user's language first, fallback to English
                                                focus_mode_display_name = translation_service.get_nested_translation(
                                                    fm_def.name_translation_key, lang=user_language
                                                ) or ""
                                                if not focus_mode_display_name and user_language != "en":
                                                    focus_mode_display_name = translation_service.get_nested_translation(
                                                        fm_def.name_translation_key, lang="en"
                                                    ) or fm_def.name_translation_key
                                                elif not focus_mode_display_name:
                                                    focus_mode_display_name = fm_def.name_translation_key
                                                break
                                except Exception:
                                    pass
                                
                                fm_embed_data = await embed_service.create_focus_mode_activation_embed(
                                    focus_id=focus_id,
                                    app_id=focus_id.split('-', 1)[0] if '-' in focus_id else focus_id,
                                    focus_mode_name=focus_mode_display_name,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                                
                                if fm_embed_data:
                                    fm_embed_id = fm_embed_data.get("embed_id")
                                    # Yield the embed reference as a JSON code block so the frontend
                                    # can parse and render it inline in the message
                                    fm_embed_ref = fm_embed_data.get("embed_reference")
                                    if fm_embed_ref:
                                        yield f"```json\n{fm_embed_ref}\n```\n\n"
                                        logger.info(
                                            f"{log_prefix} [FOCUS_MODE] Yielded focus mode activation embed "
                                            f"(embed_id={fm_embed_id})"
                                        )
                            except Exception as embed_error:
                                logger.error(
                                    f"{log_prefix} [FOCUS_MODE] Error creating focus mode embed: {embed_error}",
                                    exc_info=True
                                )
                        
                        # --- Load focus mode prompt from translation service ---
                        # Translation key format: focus_modes.{app_id}_{focus_id}.systemprompt
                        # Load in the user's language (from preprocessing) with English fallback
                        focus_prompt_text = ""
                        try:
                            focus_app_id, focus_mode_id = focus_id.split('-', 1)
                            translation_key = f"focus_modes.{focus_app_id}_{focus_mode_id}.systemprompt"
                            user_language = preprocessing_results.output_language or "en"
                            
                            # Try to load in user's language first
                            focus_prompt_text = translation_service.get_nested_translation(translation_key, lang=user_language) or ""
                            
                            # Fallback to English if not found in user's language
                            if not focus_prompt_text and user_language != "en":
                                focus_prompt_text = translation_service.get_nested_translation(translation_key, lang="en") or ""
                                logger.info(f"{log_prefix} [FOCUS_MODE] Loaded focus prompt in fallback language (en) ({len(focus_prompt_text)} chars)")
                            else:
                                logger.info(f"{log_prefix} [FOCUS_MODE] Loaded focus prompt in user language ({user_language}) ({len(focus_prompt_text)} chars)")
                        except Exception as e:
                            logger.error(f"{log_prefix} [FOCUS_MODE] Error loading focus prompt: {e}", exc_info=True)
                        
                        # --- Store pending activation context in Redis ---
                        # This context is consumed by either the auto-confirm task (happy path)
                        # or the rejection WebSocket handler (user rejects)
                        if cache_service:
                            try:
                                pending_context = {
                                    "focus_id": focus_id,
                                    "focus_prompt": focus_prompt_text,
                                    "embed_id": fm_embed_id,
                                    "chat_id": request_data.chat_id,
                                    "message_id": request_data.message_id,
                                    "user_id": request_data.user_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "mate_id": preprocessing_results.selected_mate_id or request_data.mate_id,  # Use preprocessor-selected mate, not the (typically None) request mate_id
                                    "chat_has_title": request_data.chat_has_title,
                                    "is_incognito": getattr(request_data, 'is_incognito', False),
                                    "task_id": task_id,
                                }
                                await cache_service.store_pending_focus_activation(
                                    chat_id=request_data.chat_id,
                                    context=pending_context,
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Stored pending focus activation context")
                            except Exception as e:
                                logger.error(f"{log_prefix} [FOCUS_MODE] Failed to store pending context: {e}", exc_info=True)
                                # If we can't store, fall through — auto-confirm will no-op
                        
                        # --- Schedule auto-confirm Celery task ---
                        # This task fires in 5 seconds (1s buffer over 4s client countdown).
                        # If the user hasn't rejected by then, it activates focus mode and
                        # fires a continuation task with focus prompt.
                        try:
                            from backend.core.api.app.tasks.celery_config import app as celery_app_instance
                            from backend.apps.ai.tasks.focus_mode_auto_confirm_task import FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN
                            celery_app_instance.send_task(
                                'apps.ai.tasks.focus_mode_auto_confirm',
                                kwargs={
                                    "chat_id": request_data.chat_id,
                                },
                                queue='app_ai',
                                countdown=FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN,
                            )
                            logger.info(
                                f"{log_prefix} [FOCUS_MODE] Scheduled auto-confirm task with "
                                f"countdown={FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN}s"
                            )
                        except Exception as e:
                            logger.error(f"{log_prefix} [FOCUS_MODE] Failed to schedule auto-confirm task: {e}", exc_info=True)
                        
                        # --- Yield special marker and return ---
                        # The stream_consumer detects this marker and treats the empty stream
                        # as expected (not an error). The actual LLM response will come from
                        # the continuation task fired by auto-confirm or rejection handler.
                        logger.info(f"{log_prefix} [FOCUS_MODE] Yielding pending marker and returning — awaiting user decision")
                        yield {"__awaiting_focus_mode_confirmation__": True, "focus_id": focus_id, "chat_id": request_data.chat_id}
                        return
                        
                    elif skill_id == "deactivate_focus_mode":
                        previous_focus_id = request_data.active_focus_id
                        logger.info(f"{log_prefix} [FOCUS_MODE] Deactivating focus mode: {previous_focus_id}")
                        
                        # Clear active_focus_id
                        request_data.active_focus_id = None
                        
                        # Clear focus_id in cache and Directus
                        if cache_service:
                            try:
                                await cache_service.update_chat_active_focus_id(
                                    user_id=request_data.user_id,
                                    chat_id=request_data.chat_id,
                                    encrypted_focus_id=None  # Clear the field
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Cleared focus_id from cache")
                                
                                # Dispatch Celery task to clear in Directus
                                from backend.core.api.app.tasks.celery_config import app as celery_app_instance
                                celery_app_instance.send_task(
                                    'app.tasks.persistence_tasks.persist_chat_active_focus_id',
                                    kwargs={
                                        "chat_id": request_data.chat_id,
                                        "encrypted_active_focus_id": None  # Clear the field
                                    },
                                    queue='persistence'
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Dispatched Celery task to clear focus_id in Directus")
                            except Exception as cache_error:
                                logger.error(f"{log_prefix} [FOCUS_MODE] Error clearing cache: {cache_error}", exc_info=True)
                        
                        tool_result_content_str = json.dumps({
                            "status": "deactivated",
                            "previous_focus_id": previous_focus_id,
                            "message": f"Focus mode '{previous_focus_id}' has been deactivated. Returning to normal assistant behavior."
                        })
                        
                        # Add tool response to history
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        
                        # Remove focus mode from system prompt by rebuilding without it
                        # For simplicity, we'll continue with the current prompt
                        # The focus mode instructions will no longer apply to this response
                        logger.info(f"{log_prefix} [FOCUS_MODE] Deactivated - continuing without focus mode instructions")
                        continue
                    else:
                        logger.warning(f"{log_prefix} Unknown system tool: {skill_id}")
                        tool_result_content_str = json.dumps({"error": f"Unknown system tool: {skill_id}"})
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        continue
                
                # Validate arguments against original schema (with min/max constraints)
                # The schema sent to LLM providers has min/max removed, but we validate against the original
                is_valid, validation_error = _validate_tool_arguments_against_schema(
                    arguments=parsed_args,
                    app_id=app_id,
                    skill_id=skill_id,
                    discovered_apps_metadata=discovered_apps_metadata,
                    task_id=task_id
                )
                
                if not is_valid:
                    logger.warning(
                        f"{log_prefix} Tool call arguments failed validation: {validation_error}. "
                        f"Proceeding anyway, but skill may reject invalid values."
                    )
                    # Optionally: clamp values to valid range or reject the tool call
                    # For now, we'll proceed and let the skill handle validation
                
                logger.debug(f"{log_prefix} Executing skill '{tool_name}' with app_id='{app_id}', skill_id='{skill_id}'")

                # STEP 1: Get placeholder embed (already created during stream processing)
                # The placeholder was created and streamed inline when the tool call was detected
                # This shows the "processing" state to users IMMEDIATELY (not after LLM stream completes)
                placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                
                if placeholder_embed_data:
                    logger.debug(
                        f"{log_prefix} Using inline-created placeholder embed: "
                        f"embed_id={placeholder_embed_data.get('embed_id')}"
                    )
                else:
                    # Fallback: create placeholder if inline creation failed
                    # This can happen if stream processing encountered an error
                    logger.warning(f"{log_prefix} No inline placeholder found for tool_call_id={tool_call_id}, creating now")
                    if cache_service and user_vault_key_id and directus_service:
                        try:
                            from backend.core.api.app.services.embed_service import EmbedService

                            # Use passed-in encryption_service
                            embed_service = EmbedService(
                                cache_service=cache_service,
                                directus_service=directus_service,
                                encryption_service=encryption_service
                            )

                            # Extract metadata from skill arguments for placeholder
                            # Handle both direct args (query) and nested args (requests[0].query)
                            metadata = {}
                            
                            # Direct query (simple skill format)
                            if "query" in parsed_args:
                                metadata["query"] = parsed_args["query"]
                            # Nested query (web search uses requests array)
                            elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                first_request = parsed_args["requests"][0]
                                if isinstance(first_request, dict) and "query" in first_request:
                                    metadata["query"] = first_request["query"]
                            
                            # Extract provider from LLM args (direct or nested), then validate
                            # against the skill's known providers list to prevent hallucination.
                            raw_provider: Optional[str] = None
                            if "provider" in parsed_args:
                                raw_provider = parsed_args["provider"]
                            elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                first_request = parsed_args["requests"][0]
                                if isinstance(first_request, dict) and "provider" in first_request:
                                    raw_provider = first_request["provider"]

                            # Validate provider (covers fallback + hallucination correction)
                            if skill_id == "search" or raw_provider is not None:
                                validated_provider = _validate_skill_provider(
                                    provider=raw_provider,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    discovered_apps_metadata=discovered_apps_metadata,
                                    log_prefix=log_prefix,
                                )
                                if validated_provider is not None:
                                    metadata["provider"] = validated_provider

                            # Create placeholder embed (fallback path)
                            placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                metadata=metadata,
                                log_prefix=log_prefix
                            )

                            if placeholder_embed_data:
                                # Stream embed reference (fallback path)
                                embed_reference_json = placeholder_embed_data.get("embed_reference")
                                embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                yield embed_code_block
                                
                                # Publish "processing" status (fallback path)
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data=metadata
                                )
                                logger.info(
                                    f"{log_prefix} FALLBACK: Created and streamed processing placeholder: "
                                    f"embed_id={placeholder_embed_data.get('embed_id')}"
                                )
                        except Exception as e:
                            logger.error(f"{log_prefix} FALLBACK: Error creating placeholder embed: {e}", exc_info=True)

                # STEP 2: Execute skill with support for multiple parallel requests
                # Pass chat_id and message_id so skills can use them when recording usage
                # Pass skill_task_id for individual skill cancellation (allows user to cancel just this skill)
                
                # Get skill_task_id from placeholder (generated during create_processing_embed_placeholder)
                # This ID is stored in embed content and allows frontend to cancel this specific skill
                # without cancelling the entire AI response
                skill_task_id = None
                if placeholder_embed_data:
                    skill_task_id = placeholder_embed_data.get("skill_task_id")
                    if not skill_task_id:
                        # Handle multiple placeholders case
                        if isinstance(placeholder_embed_data.get("placeholders"), list):
                            # For multiple requests, use first placeholder's skill_task_id
                            # (all requests in a tool call share the same cancellation scope)
                            first_placeholder = placeholder_embed_data.get("placeholders", [{}])[0]
                            skill_task_id = first_placeholder.get("skill_task_id")
                
                # Generate skill_task_id if not found (fallback for legacy placeholders)
                if not skill_task_id:
                    skill_task_id = generate_skill_task_id()
                    logger.debug(f"{log_prefix} Generated fallback skill_task_id: {skill_task_id}")
                
                # Track if skill was cancelled
                skill_was_cancelled = False
                
                try:
                    # ARGUMENT NORMALIZATION:
                    # LLMs sometimes send flat arguments (e.g., {"prompt": "..."}) instead of the
                    # required {"requests": [...]} array format for skills that expect it.
                    # Detect this mismatch using the skill's tool_schema and normalize the arguments.
                    # See: https://github.com/anomalyco/OpenMates/issues/XXX (image generation 422 bug)
                    skill_arguments = _normalize_skill_arguments(
                        arguments=parsed_args,
                        app_id=app_id,
                        skill_id=skill_id,
                        discovered_apps_metadata=discovered_apps_metadata,
                        task_id=task_id,
                        message_history=current_message_history,
                    )

                    # For async skills (e.g., images.generate), thread placeholder embed_ids
                    # so the Celery task can update the existing placeholder instead of creating new embeds.
                    # This enables the in-place "processing" -> "finished" transition.
                    if placeholder_embed_data:
                        # Extract placeholder embed_ids to pass to the skill
                        _placeholder_ids = []
                        if isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                            # Multiple placeholders
                            for p in placeholder_embed_data.get("placeholders", []):
                                _placeholder_ids.append(p.get("embed_id"))
                        elif isinstance(placeholder_embed_data, dict) and "embed_id" in placeholder_embed_data:
                            # Single placeholder
                            _placeholder_ids.append(placeholder_embed_data["embed_id"])
                        
                        if _placeholder_ids:
                            # Inject as metadata field (underscore prefix = stripped before Pydantic validation)
                            # Copy from skill_arguments (not parsed_args) to preserve normalization
                            skill_arguments = skill_arguments.copy()
                            skill_arguments["_placeholder_embed_ids"] = _placeholder_ids
                    
                    # Inject user_vault_key_id as server-side context for skills that need
                    # Vault Transit access (e.g. images-view needs it to look up embed
                    # crypto details from the Redis cache). Underscore prefix ensures it is
                    # stripped before Pydantic validation in base_app.py.
                    if user_vault_key_id:
                        skill_arguments = skill_arguments.copy()
                        skill_arguments["_user_vault_key_id"] = user_vault_key_id

                    # Inject the embed_ref → embed_id mapping so skills like images-view
                    # can resolve a human-readable file_path argument (e.g. "my_photo.jpg")
                    # back to the internal UUID embed_id for Redis/Vault/S3 lookup.
                    # Underscore prefix causes base_app.py to strip it before Pydantic validation.
                    embed_file_path_index = getattr(request_data, "embed_file_path_index", None)
                    if embed_file_path_index:
                        skill_arguments = skill_arguments.copy()
                        skill_arguments["_file_path_index"] = embed_file_path_index

                    # Execute skill with retry logic (20s timeout, 1 retry by default)
                    # On timeout, the request is cancelled and retried with a fresh connection,
                    # which helps when external APIs are slow or proxy IPs need rotation
                    results = await execute_skill_with_multiple_requests(
                        app_id=app_id,
                        skill_id=skill_id,
                        arguments=skill_arguments,
                        timeout=DEFAULT_SKILL_TIMEOUT,  # 20s timeout with retry logic
                        chat_id=request_data.chat_id,
                        message_id=request_data.message_id,
                        user_id=request_data.user_id,
                        skill_task_id=skill_task_id,
                        cache_service=cache_service
                        # max_retries uses default (1 retry = 2 total attempts)
                    )
                    
                    # === RECORD SUCCESSFUL SKILL EXECUTION FOR DEDUPLICATION ===
                    # Store this successful call so subsequent iterations won't re-execute it.
                    # This prevents duplicate side effects (e.g., multiple reminders) when LLMs
                    # repeatedly call the same tool across iterations.
                    # Only record if we got valid results (not cancelled, not error).
                    if results:
                        embed_id_for_dedup = placeholder_embed_data.get("embed_id") if placeholder_embed_data else None
                        completed_skill_calls[call_hash] = {
                            "embed_id": embed_id_for_dedup,
                            "skill_task_id": skill_task_id,
                        }
                        logger.info(
                            f"{log_prefix} [DEDUP] Recorded successful '{app_id}.{skill_id}' call "
                            f"(hash={call_hash[:8]}..., embed_id={embed_id_for_dedup})"
                        )
                        
                except SkillCancelledException:
                    # User cancelled this specific skill - continue with cancelled result
                    # The main AI response will continue, just without this skill's data
                    logger.info(
                        f"{log_prefix} Skill '{app_id}.{skill_id}' was cancelled by user "
                        f"(skill_task_id={skill_task_id}). Main processing will continue."
                    )
                    skill_was_cancelled = True
                    # Create cancelled result that tells the LLM the skill was cancelled
                    results = [{
                        "status": "cancelled",
                        "message": f"The {skill_id} skill was cancelled by the user. Please continue without this information.",
                        "app_id": app_id,
                        "skill_id": skill_id
                    }]
                    
                    # Update embed status to "cancelled" so frontend shows appropriate state
                    if cache_service and placeholder_embed_data:
                        try:
                            embed_id = placeholder_embed_data.get("embed_id")
                            if embed_id:
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="cancelled",
                                    preview_data={"embed_id": embed_id, "cancelled_by_user": True}
                                )
                        except Exception as status_error:
                            logger.error(f"{log_prefix} Error publishing cancelled status: {status_error}")
                except Exception as skill_error:
                    # CRITICAL: Handle skill execution failures gracefully
                    # When a skill fails (HTTP error, timeout, rate limit, etc.), we:
                    # 1. Create an error result that tells the LLM the skill failed
                    # 2. Update the embed status to "error" so frontend shows failure
                    # 3. Continue processing - don't crash the entire AI response
                    # This allows the LLM to interpret results from successful skills
                    # and provide a meaningful response even when some skills fail.
                    error_message = str(skill_error)
                    logger.warning(
                        f"{log_prefix} Skill '{app_id}.{skill_id}' failed with error: {error_message}. "
                        f"Main processing will continue with error result for LLM."
                    )
                    
                    # Create error result that tells the LLM the skill failed
                    # This allows the LLM to acknowledge the failure and continue with other results
                    results = [{
                        "status": "error",
                        "error": error_message,
                        "message": f"The {skill_id} skill failed: {error_message}. Please continue with any other available information.",
                        "app_id": app_id,
                        "skill_id": skill_id
                    }]
                    
                    # Update embed status to "error" so frontend shows failure state
                    if cache_service and placeholder_embed_data:
                        try:
                            embed_id = placeholder_embed_data.get("embed_id")
                            if embed_id:
                                # Use embed_service to properly update the embed status
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(
                                    cache_service=cache_service,
                                    directus_service=directus_service,
                                    encryption_service=encryption_service
                                )
                                await embed_service.update_embed_status_to_error(
                                    embed_id=embed_id,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    error_message=error_message,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                                logger.info(f"{log_prefix} Updated embed {embed_id} status to 'error'")
                                failed_embed_ids.add(embed_id)
                        except Exception as status_error:
                            logger.error(f"{log_prefix} Error updating embed status to error: {status_error}")

                # =====================================================================
                # ASYNC SKILL DETECTION
                # =====================================================================
                # Long-running skills (e.g., images.generate) return immediately with
                # {"status": "processing", "task_id": "...", "embed_id": "..."}
                # and dispatch a Celery task that will update the embed asynchronously.
                #
                # For these skills, we SKIP the normal embed update flow because:
                # 1. The placeholder embed is already in "processing" state
                # 2. The Celery task will update it to "finished" when done
                # 3. The TOON encoding / update_embed_with_results flow doesn't apply
                #
                # We still need to:
                # - Create a minimal tool_result for the LLM (so it knows the task was dispatched)
                # - Publish a "processing" skill status (placeholder already shows this)
                # - Skip TOON encoding, embed updates, and credit charging
                # =====================================================================
                is_async_skill = False
                if results and len(results) == 1 and isinstance(results[0], dict):
                    first_result = results[0]
                    if first_result.get("status") == "processing" and ("task_id" in first_result or "task_ids" in first_result):
                        is_async_skill = True
                        logger.info(
                            f"{log_prefix} Detected async skill '{app_id}.{skill_id}' with status='processing'. "
                            f"Skipping embed update flow - Celery task will handle it. "
                            f"task_id={first_result.get('task_id')}, embed_id={first_result.get('embed_id')}"
                        )
                
                if is_async_skill:
                    # For async skills, provide a clean tool result for the LLM.
                    # IMPORTANT: Only include a human-readable message - do NOT include
                    # embed_id, task_id, or other technical fields that the LLM might
                    # echo back as raw JSON in its response to the user.
                    async_result = results[0]
                    tool_result_content_str = json.dumps({
                        "status": "success",
                        "message": "The image is now being generated and will appear in the chat automatically when ready. Briefly acknowledge this to the user."
                    })
                    
                    # Publish "finished" skill status (the embed itself stays "processing")
                    # This tells the frontend that the skill call completed (dispatched successfully)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="finished",
                        preview_data={
                            "status": "processing",
                            "embed_id": async_result.get("embed_id"),
                            "task_id": async_result.get("task_id"),
                            "prompt": parsed_args.get("requests", [{}])[0].get("prompt", "") if isinstance(parsed_args, dict) else "",
                            "model": parsed_args.get("requests", [{}])[0].get("model", "") if isinstance(parsed_args, dict) else "",
                        }
                    )
                    
                    # Skip everything below (TOON encoding, embed updates, credit charging)
                    # and yield the tool result for the LLM
                    # The tool_result_content_str is used by the LLM iteration loop

                # SKIP normalization, TOON encoding, embed updates, and credit charging for async skills.
                # These skills (e.g., images.generate) dispatch Celery tasks and return immediately.
                # The tool_result_content_str was already set above; we jump directly to tool_call_info tracking.
                
                # Normalize skill responses that wrap actual results in a "results" field (e.g., web search)
                # execute_skill_with_multiple_requests returns one entry per request, but search skills return
                # a response object with its own "results" array.
                # 
                # CRITICAL: Preserve grouped structure for embed creation (multiple requests = multiple embeds)
                # Flatten only for LLM inference (token efficiency)
                response_ignore_fields: Optional[List[str]] = None
                first_response: Optional[Dict[str, Any]] = None  # Initialize to avoid UnboundLocalError
                grouped_results: Optional[List[Dict[str, Any]]] = None  # Preserve grouping for embed creation
                
                # Detect multimodal content block results from view skills (e.g., images.view).
                # These return [[{"type": "text", ...}, {"type": "image_url", ...}]] — a list
                # containing a single list of OpenAI-style content blocks.
                # We must NOT TOON-encode them; instead we pass the inner list directly as
                # tool_result_content_str so the provider adapters can convert the image_url
                # block to the LLM-specific format (Anthropic image source, Gemini inlineData, etc.).
                is_multimodal_result = (
                    not is_async_skill
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], list)
                    and len(results[0]) > 0
                    and all(
                        isinstance(b, dict) and b.get("type") in ("text", "image_url")
                        for b in results[0]
                    )
                )
                if is_multimodal_result:
                    # Bypass all TOON encoding — set tool_result_content_str to the raw content
                    # block list so it arrives at the LLM as a proper multimodal tool result.
                    # preview_data["results_toon"] is set later when is_multimodal_result is False;
                    # for multimodal results we skip both TOON encoding blocks below.
                    tool_result_content_str = results[0]
                    logger.info(
                        f"{log_prefix} Detected multimodal content block result from '{tool_name}' "
                        f"({len(results[0])} blocks). Bypassing TOON encoding — passing raw list to LLM."
                    )

                if not is_async_skill and results and all(isinstance(r, dict) and "results" in r for r in results):
                    first_response = results[0]
                    # Skills no longer provide preview_data - we'll create it in main_processor
                    response_ignore_fields = first_response.get("ignore_fields_for_inference")

                    # PRESERVE GROUPING: Extract the grouped structure from the response
                    # execute_skill_with_multiple_requests returns [response_dict] where response_dict is:
                    # {"results": [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...], "provider": "...", ...}
                    # We need to extract the "results" array from the response dict to get the grouped structure
                    response_results_array = first_response.get("results", [])
                    
                    # Check if response_results_array contains the grouped structure (each item has "id" and "results")
                    if (isinstance(response_results_array, list) and 
                        len(response_results_array) > 0 and 
                        all(isinstance(r, dict) and "id" in r and "results" in r for r in response_results_array)):
                        # This is the grouped structure: [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...]
                        grouped_results = response_results_array
                        logger.debug(f"{log_prefix} Detected grouped results structure with {len(grouped_results)} request groups")
                    else:
                        # Fallback: Not grouped, treat as single request
                        grouped_results = None
                        logger.debug(f"{log_prefix} Results are not in grouped structure format")
                    
                    # Flatten only for LLM inference (token efficiency)
                    flattened_results: List[Dict[str, Any]] = []
                    for response in results:
                        response_results = response.get("results")
                        if isinstance(response_results, list):
                            # Check if response_results is grouped structure or flat list
                            if response_results and isinstance(response_results[0], dict) and "id" in response_results[0] and "results" in response_results[0]:
                                # Grouped structure: extract results from each group
                                for group in response_results:
                                    group_results = group.get("results", [])
                                    if isinstance(group_results, list):
                                        flattened_results.extend(group_results)
                            else:
                                # Flat list: use directly
                                flattened_results.extend(response_results)
                    results = flattened_results  # Use flattened for LLM inference
                
                # Extract ignore_fields_for_inference from skill results (if present)
                # This is a skill-defined list of fields to exclude from LLM inference
                # Skills can define this in their response to control what gets sent to LLM
                ignore_fields_for_inference: Optional[List[str]] = None

                # Prefer ignore_fields_for_inference defined on the skill response wrapper (if provided)
                if response_ignore_fields:
                    ignore_fields_for_inference = response_ignore_fields
                
                # Check if results contain ignore_fields_for_inference (from skill response)
                # This takes precedence over exclude_fields_for_llm from app.yml
                if results and len(results) > 0:
                    # Check first result for ignore_fields_for_inference
                    first_result = results[0]
                    if isinstance(first_result, dict) and "ignore_fields_for_inference" in first_result:
                        ignore_fields_for_inference = first_result.get("ignore_fields_for_inference")
                        logger.debug(
                            f"{log_prefix} Skill '{tool_name}' returned ignore_fields_for_inference: {ignore_fields_for_inference}"
                        )
                
                # Fallback to exclude_fields_for_llm from app.yml if skill didn't provide ignore_fields_for_inference
                if ignore_fields_for_inference is None:
                    if app_id in discovered_apps_metadata:
                        app_metadata = discovered_apps_metadata[app_id]
                        for skill_def in app_metadata.skills:
                            if skill_def.id == skill_id:
                                ignore_fields_for_inference = skill_def.exclude_fields_for_llm
                                logger.debug(
                                    f"{log_prefix} Using exclude_fields_for_llm from app.yml: {ignore_fields_for_inference}"
                                )
                                break
                
                # Create minimal preview_data - only contains results_toon and essential metadata
                # Skills no longer provide preview_data (removed as redundant)
                # We create a minimal preview_data here with:
                # - results_toon: Full TOON-encoded results (added below)
                # - query: Extracted from input arguments if available (for frontend previews)
                # - provider: Extracted from response if available (for frontend previews)
                # NOTE: For async skills, preview_data stays empty - the Celery task handles all data.
                # tool_result_content_str was already set in the async detection block above.
                preview_data: Dict[str, Any] = {}
                
                # Extract query from input arguments if available (for search skills)
                # This is used by frontend for preview display
                if not is_async_skill and parsed_args and isinstance(parsed_args, dict):
                    # Try to extract query from various possible input structures
                    if "query" in parsed_args:
                        preview_data["query"] = parsed_args["query"]
                    elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                        first_request = parsed_args["requests"][0]
                        if isinstance(first_request, dict) and "query" in first_request:
                            preview_data["query"] = first_request["query"]
                
                # Extract provider from response if available
                # This is used by frontend for preview display
                if not is_async_skill and first_response and isinstance(first_response, dict):
                    if "provider" in first_response:
                        preview_data["provider"] = first_response["provider"]
                
                # Add result count (can be derived from results, but useful for frontend)
                if not is_async_skill:
                    preview_data["result_count"] = len(results) if results else 0
                
                # CRITICAL: Add full results in TOON format ONLY (no JSON)
                # The frontend can decode this TOON string to get all fields (page_age, profile.name, url, etc.)
                # This ensures the frontend receives the complete data structure in efficient TOON format
                # The same TOON string is also stored in chat history for persistence
                # We only store TOON - JSON can be generated from TOON when needed
                # 
                # IMPORTANT: Flatten nested objects before encoding to enable TOON tabular format
                # This approach is proven to work in toon_encoding_test.ipynb and saves 25-32% in token usage.
                # TOON tabular format eliminates repeated field names (title:, url:, etc.) by using:
                # results[N]{field1,field2,field3}:
                #   value1,value2,value3
                #   value4,value5,value6
                # Instead of repeating field names for each result (which wastes tokens).
                # 
                # The flattening function converts:
                # - profile: {name: "..."} → profile_name: "..."
                # - meta_url: {favicon: "..."} → meta_url_favicon: "..."
                # - extra_snippets: [...] → extra_snippets: "|".join([...])
                if not is_async_skill and not is_multimodal_result:
                    try:
                        # DEBUG: Log original JSON structure (first 15 lines)
                        json_before = json.dumps(results, indent=2) if len(results) == 1 else json.dumps({"results": results, "count": len(results)}, indent=2)
                        json_lines = json_before.split('\n')
                        if len(results) == 1:
                            # Single result - flatten and encode as TOON
                            # Note: Single result encoded directly (not wrapped in dict) for efficiency
                            flattened_result = _flatten_for_toon_tabular(results[0])
                            results_toon = encode(flattened_result)
                        else:
                            # Multiple results - flatten each result, then combine and encode as TOON
                            # Flattening enables TOON to use tabular format for uniform objects
                            # This matches the proven approach from toon_encoding_test.ipynb
                            flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                            results_toon = encode({"results": flattened_results, "count": len(results)})
                        logger.debug(f"{log_prefix} TOON conversion (preview_data) length={len(results_toon)} chars")
                        
                        # Add TOON-encoded full results to preview_data (this is the ONLY place results are stored)
                        preview_data["results_toon"] = results_toon
                        logger.debug(
                            f"{log_prefix} Added full results in TOON format to preview_data ({len(results_toon)} chars). "
                            f"Frontend can decode TOON to get all fields. No JSON data stored."
                        )
                    except Exception as e:
                        # Fallback to JSON if TOON encoding fails (should rarely happen)
                        logger.warning(f"{log_prefix} TOON encoding failed for preview_data, falling back to JSON: {e}")
                        if len(results) == 1:
                            preview_data["results_toon"] = json.dumps(results[0])
                        else:
                            preview_data["results_toon"] = json.dumps({"results": results, "count": len(results)})
                
                # Inject embed_ref slugs into composite skill results (web search, flights, places, etc.)
                # CRITICAL: Slugs are generated HERE (once) so that:
                #   1. The LLM sees them in the tool result → can write [text](embed:ref) inline refs
                #   2. The SAME slugs are baked into child embed TOON by update_embed_with_results
                #      (which reads embed_ref from the result dict if already present)
                # Generating slugs in two places would produce different random suffixes → ref mismatch.
                # Skills whose results contain text-heavy content worth quoting verbatim.
                # A single source_quote_hint is added at the group level (not per result)
                # to remind the LLM it can use > [exact text](embed:ref) blockquote syntax.
                _QUOTABLE_SKILL_IDS = {"search", "read"}
                # Generate embed_ref slugs for ALL non-async/non-multimodal skills (not just
                # composite ones). Non-composite skills (e.g. web.read) produce a single result
                # that also needs an embed_ref so the LLM can reference it and QUOTE_VERIFY
                # can build its embed_ref→id map. Without this, the LLM invents refs like
                # "embed:1" which fail verification and get stripped.
                if not is_async_skill and not is_multimodal_result:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService as _EmbedSvc
                        _child_type = _EmbedSvc.get_child_embed_type(app_id, skill_id)
                        _seen_refs: Dict[str, int] = {}
                        results_with_refs = []
                        for _r in results:
                            _raw_ref = _EmbedSvc._generate_embed_ref_slug(_child_type, _r)
                            _unique_ref = _EmbedSvc._unique_embed_ref(_raw_ref, _seen_refs)
                            _r_with_ref = dict(_r)
                            _r_with_ref["embed_ref"] = _unique_ref
                            results_with_refs.append(_r_with_ref)
                        logger.debug(
                            f"{log_prefix} Pre-generated embed_ref slugs for {len(results_with_refs)} "
                            f"{_child_type} results (single source of truth for tool result + child TOON)"
                        )
                        # Also annotate grouped_results so per-group embed calls use the same slugs.
                        # We match by position within each group to the flat results_with_refs list.
                        if grouped_results:
                            _ref_iter = iter(results_with_refs)
                            for _gr in grouped_results:
                                _gr_results = _gr.get("results", [])
                                _gr["results"] = []
                                for _grr in _gr_results:
                                    try:
                                        _grr_with_ref = next(_ref_iter)
                                    except StopIteration:
                                        _grr_with_ref = _grr  # safety fallback
                                    _gr["results"].append(_grr_with_ref)
                    except Exception as _slug_err:
                        logger.warning(f"{log_prefix} embed_ref slug pre-generation failed, falling back to per-embed generation: {_slug_err}")
                        results_with_refs = results
                else:
                    results_with_refs = results

                # Filter results WITH embed_refs for current LLM inference
                # Removes non-essential fields (URLs, thumbnails, etc.) to reduce noise
                # and make embed_ref more prominent. Full results are already stored in
                # preview_data["results_toon"] for UI rendering.
                if ignore_fields_for_inference and not is_async_skill:
                    filtered_results_with_refs = _filter_skill_results_for_llm(results_with_refs, ignore_fields_for_inference)
                else:
                    filtered_results_with_refs = results_with_refs

                # CRITICAL: Store FULL results (not filtered) in chat history for persistence
                # This ensures all fields from Brave search (page_age, profile.name, url, etc.) are available
                # for future LLM calls and UI rendering. The filtered version is only used for the current LLM call.
                # Convert FULL results to TOON format for chat history storage
                # TOON format reduces token usage by 30-60% compared to JSON while preserving all fields
                # 
                # IMPORTANT: Flatten nested objects before encoding to enable TOON tabular format
                # This ensures efficient encoding with tabular arrays instead of repeated field names
                if not is_async_skill and not is_multimodal_result:
                    try:
                        # DEBUG: Log original JSON structure (first 15 lines)
                        json_before = json.dumps(results_with_refs, indent=2) if len(results_with_refs) == 1 else json.dumps({"results": results_with_refs, "count": len(results_with_refs)}, indent=2)
                        json_lines = json_before.split('\n')
                        logger.info(f"{log_prefix} === TOON CONVERSION DEBUG (chat history) ===")
                        logger.info(
                            f"{log_prefix} TOON source payload prepared "
                            f"(json_length={len(json_before)}, line_count={len(json_lines)})"
                        )
                        # Source quote hint — added once per tool result group for quotable
                        # skills (web-search, news-search).  Tells the LLM it can use the
                        # > [verbatim text](embed:ref) blockquote syntax to cite sources.
                        # Placed at the wrapper level so it costs ~30 tokens total, not per result.
                        _sq_hint = (
                            "When citing specific facts from these results, quote the exact "
                            "text using: > [verbatim text from title, description, or "
                            "extra_snippets](embed:the_result's_embed_ref)"
                        ) if skill_id in _QUOTABLE_SKILL_IDS else None

                        # Embed ref display-text hint — added once per tool result group
                        # for ALL embed-producing skills.  Reinforces that the display text
                        # in [text](embed:ref) links must be a human-readable description
                        # (e.g. the result's title), NEVER the embed_ref slug or its suffix.
                        # Placed at the wrapper level (~40 tokens total, not per result).
                        _ref_hint = (
                            "IMPORTANT — inline link display text: when writing "
                            "[text](embed:ref), use the result's title or a short "
                            "description as 'text'. NEVER use the embed_ref itself, "
                            "its domain-suffix, or the random code as display text."
                        )

                        if len(filtered_results_with_refs) == 1:
                            # Single result - flatten and encode filtered result as TOON for LLM inference
                            flattened_result = _flatten_for_toon_tabular(filtered_results_with_refs[0])
                            if _sq_hint:
                                flattened_result["source_quote_hint"] = _sq_hint
                            flattened_result["embed_ref_hint"] = _ref_hint
                            tool_result_content_str = encode(flattened_result)
                        else:
                            # Multiple results - flatten each filtered result, then combine and encode as TOON
                            # Flattening enables TOON to use tabular format for uniform objects
                            flattened_results = [_flatten_for_toon_tabular(result) for result in filtered_results_with_refs]
                            toon_wrapper: Dict[str, Any] = {"results": flattened_results, "count": len(filtered_results_with_refs)}
                            if _sq_hint:
                                toon_wrapper["source_quote_hint"] = _sq_hint
                            toon_wrapper["embed_ref_hint"] = _ref_hint
                            tool_result_content_str = encode(toon_wrapper)

                        logger.debug(f"{log_prefix} TOON conversion (LLM inference) length={len(tool_result_content_str)} chars")

                        logger.debug(
                            f"{log_prefix} Skill '{tool_name}' executed successfully, returned {len(results)} result(s). "
                            f"Full results in preview_data (all fields preserved). "
                            f"Filtered to {len(filtered_results_with_refs)} result(s) for LLM call (ignored fields: {ignore_fields_for_inference or 'none'})"
                        )
                    except Exception as e:
                        # Fallback to JSON if TOON encoding fails — still use filtered results
                        logger.warning(f"{log_prefix} TOON encoding failed for skill '{tool_name}', falling back to JSON: {e}")
                        if len(filtered_results_with_refs) == 1:
                            tool_result_content_str = json.dumps(filtered_results_with_refs[0])
                        else:
                            tool_result_content_str = json.dumps({"results": filtered_results_with_refs, "count": len(filtered_results_with_refs)})
                
                # Calculate and charge credits for skill execution
                # NOTE: Skip for async skills - credits are charged by the Celery task
                # Pass grouped_results so _charge_skill_credits can count only successful requests
                if not is_async_skill:
                    await _charge_skill_credits(
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        discovered_apps_metadata=discovered_apps_metadata,
                        results=results,
                        parsed_args=parsed_args,
                        log_prefix=log_prefix,
                        grouped_results=grouped_results,
                    )
                
                # STEP 3: Create embeds from results
                # For multiple requests: Create one app_skill_use embed per request group
                # For single request: Update the existing placeholder embed
                # NOTE: Skip for async skills - the Celery task handles embed updates
                updated_embed_data_list: List[Dict[str, Any]] = []
                if not is_async_skill and not is_multimodal_result and cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService

                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )

                        # Check if we have grouped results (multiple requests)
                        # Grouped results structure: [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...]
                        is_multiple_requests = (
                            grouped_results is not None and 
                            len(grouped_results) > 1 and
                            all(isinstance(r, dict) and "id" in r and "results" in r for r in grouped_results)
                        )
                        
                        if is_multiple_requests:
                            # Multiple requests: Update existing placeholders or create new embeds
                            logger.info(
                                f"{log_prefix} Processing {len(grouped_results)} separate embeds for multiple requests. "
                                f"Grouped results structure: {[{'id': r.get('id'), 'result_count': len(r.get('results', []))} for r in grouped_results]}"
                            )
                            
                            # Check if we have multiple placeholders stored (from inline creation)
                            placeholder_embeds_map = {}
                            if placeholder_embed_data and isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                                # We have multiple placeholders - map them by request_id
                                # Normalize request_id types (int/str) for reliable matching
                                for placeholder in placeholder_embed_data.get("placeholders", []):
                                    placeholder_request_id = placeholder.get("request_id")
                                    if placeholder_request_id is not None:
                                        # Normalize to string for consistent matching (handles int/str mismatches)
                                        placeholder_request_id_key = str(placeholder_request_id)
                                        placeholder_embeds_map[placeholder_request_id_key] = placeholder
                                logger.info(
                                    f"{log_prefix} Found {len(placeholder_embeds_map)} placeholders to update for multiple requests. "
                                    f"Request IDs: {list(placeholder_embeds_map.keys())}"
                                )
                            elif placeholder_embed_data and isinstance(placeholder_embed_data, dict) and "embed_id" in placeholder_embed_data:
                                # Fallback: Single placeholder was created (old behavior)
                                # This shouldn't happen with the new code, but handle gracefully
                                logger.warning(
                                    f"{log_prefix} Multiple requests detected but only single placeholder found. "
                                    f"This indicates the placeholder creation logic didn't detect multiple requests. "
                                    f"Creating new embeds for each request."
                                )
                            
                            # Extract request metadata from parsed_args for each request
                            # CRITICAL: Use the parsed_args stored during placeholder creation (with our modified IDs)
                            # instead of the freshly-parsed parsed_args from line 1568 which has original LLM IDs.
                            # The placeholder phase modifies request["id"] to be 1-indexed (1, 2, 3...) for consistency,
                            # but parsed_args is parsed separately in both phases from the same tool_arguments_str.
                            stored_parsed_args = placeholder_embed_data.get("parsed_args") if isinstance(placeholder_embed_data, dict) else None
                            args_for_metadata = stored_parsed_args if stored_parsed_args else parsed_args
                            requests_list = args_for_metadata.get("requests", []) if isinstance(args_for_metadata, dict) else []
                            request_metadata_map = {}
                            for req in requests_list:
                                if isinstance(req, dict) and "id" in req:
                                    request_metadata_map[req["id"]] = req
                            
                            # Debug: Log whether we used stored or fresh parsed_args
                            logger.debug(
                                f"{log_prefix} Building request_metadata_map: used_stored_parsed_args={stored_parsed_args is not None}, "
                                f"request_count={len(requests_list)}"
                            )
                            
                            # Log all grouped_result request_ids for debugging ID mismatches
                            grouped_result_ids = [str(gr.get("id")) for gr in grouped_results]
                            logger.info(
                                f"{log_prefix} Processing {len(grouped_results)} grouped results. "
                                f"Result request IDs: {grouped_result_ids}, Placeholder request IDs: {list(placeholder_embeds_map.keys())}"
                            )
                            
                            for grouped_result in grouped_results:
                                request_id = grouped_result.get("id")
                                request_results = grouped_result.get("results", [])
                                
                                # Normalize request_id to string for consistent matching with placeholders
                                request_id_key = str(request_id) if request_id is not None else None
                                
                                logger.debug(
                                    f"{log_prefix} Processing grouped result: request_id={request_id} (key={request_id_key}), "
                                    f"result_count={len(request_results)}, has_error={bool(grouped_result.get('error'))}"
                                )
                                
                                # Get request metadata (query, url, etc.) for this specific request
                                # Try both original request_id and normalized key
                                request_metadata = request_metadata_map.get(request_id, request_metadata_map.get(request_id_key, {}))
                                
                                # DEBUG: Log request_metadata_map keys and lookup results
                                logger.info(
                                    f"{log_prefix} [QUERY_DEBUG] request_metadata_map keys: {list(request_metadata_map.keys())}, "
                                    f"request_id={request_id} (type={type(request_id).__name__}), "
                                    f"request_id_key={request_id_key}, "
                                    f"lookup result has query: {'query' in request_metadata}, "
                                    f"query value: {request_metadata.get('query', 'NOT_FOUND')}"
                                )
                                
                                # Include provider info from first_response if available
                                request_metadata_with_provider = request_metadata.copy()
                                if first_response and isinstance(first_response, dict):
                                    if "provider" in first_response:
                                        request_metadata_with_provider["provider"] = first_response["provider"]
                                    if "providers" in first_response:
                                        request_metadata_with_provider["providers"] = first_response["providers"]
                                
                                # CRITICAL: Ensure query is present for UI rendering, even if request metadata is missing
                                # Some LLMs omit "query" in requests array; fall back to grouped_result fields if needed.
                                if isinstance(grouped_result, dict):
                                    if "query" not in request_metadata_with_provider:
                                        logger.warning(
                                            f"{log_prefix} [QUERY_DEBUG] query NOT in request_metadata_with_provider, "
                                            f"checking grouped_result. grouped_result keys: {list(grouped_result.keys())}"
                                        )
                                        for fallback_key in ["query", "search_query", "q", "input", "url"]:
                                            fallback_value = grouped_result.get(fallback_key)
                                            if isinstance(fallback_value, str) and fallback_value.strip():
                                                request_metadata_with_provider["query"] = fallback_value
                                                logger.info(f"{log_prefix} [QUERY_DEBUG] Found query via fallback key '{fallback_key}': {fallback_value}")
                                                break
                                        else:
                                            logger.warning(f"{log_prefix} [QUERY_DEBUG] No query found in grouped_result via any fallback key!")
                                    else:
                                        logger.info(
                                            f"{log_prefix} [QUERY_DEBUG] query found in request_metadata_with_provider: "
                                            f"{request_metadata_with_provider.get('query')}"
                                        )
                                
                                # Check if this request failed (no results)
                                if not request_results:
                                    # Request failed - update placeholder to error or create error embed
                                    error_message = grouped_result.get("error") or "Request failed with no results"
                                    logger.warning(
                                        f"{log_prefix} Request {request_id} failed: {error_message}."
                                    )
                                    
                                    # Check if we have a placeholder for this request (use normalized key)
                                    matching_placeholder = placeholder_embeds_map.get(request_id_key) if request_id_key else None
                                    if matching_placeholder:
                                        # Update existing placeholder to error status
                                        placeholder_embed_id = matching_placeholder.get("embed_id")
                                        logger.info(
                                            f"{log_prefix} Found matching placeholder for failed request {request_id}: "
                                            f"embed_id={placeholder_embed_id}, key={request_id_key}"
                                        )
                                        try:
                                            updated_error_embed = await embed_service.update_embed_status_to_error(
                                                embed_id=placeholder_embed_id,
                                                app_id=app_id,
                                                skill_id=skill_id,
                                                error_message=error_message,
                                                chat_id=request_data.chat_id,
                                                message_id=request_data.message_id,
                                                user_id=request_data.user_id,
                                                user_id_hash=request_data.user_id_hash,
                                                user_vault_key_id=user_vault_key_id,
                                                task_id=task_id,
                                                log_prefix=f"{log_prefix}[request_id={request_id}]"
                                            )
                                            
                                            if updated_error_embed:
                                                # Generate embed_reference for the error embed
                                                # CRITICAL: Include app_id and skill_id so frontend can properly group embeds
                                                # by app+skill type (e.g., web.search embeds grouped separately from code.get_docs).
                                                # ALSO include query/provider when available so the UI can render the query
                                                # even when the embed is in error status.
                                                embed_reference_payload = {
                                                    "type": "app_skill_use",
                                                    "embed_id": placeholder_embed_id,
                                                    "app_id": app_id,
                                                    "skill_id": skill_id
                                                }
                                                # Include query and provider from request_metadata for UI rendering
                                                if request_metadata_with_provider.get("query"):
                                                    embed_reference_payload["query"] = request_metadata_with_provider["query"]
                                                if request_metadata_with_provider.get("provider"):
                                                    embed_reference_payload["provider"] = request_metadata_with_provider["provider"]
                                                if request_metadata_with_provider.get("providers"):
                                                    embed_reference_payload["providers"] = request_metadata_with_provider["providers"]
                                                updated_error_embed["embed_reference"] = json.dumps(embed_reference_payload)
                                                updated_error_embed["request_id"] = request_id
                                                updated_error_embed["request_metadata"] = request_metadata
                                                updated_embed_data_list.append(updated_error_embed)
                                                logger.info(
                                                    f"{log_prefix} Updated placeholder {placeholder_embed_id} to error for request {request_id}"
                                                )
                                                failed_embed_ids.add(placeholder_embed_id)
                                        except Exception as error_update_error:
                                            logger.warning(
                                                f"{log_prefix} Failed to update placeholder to error status: {error_update_error}"
                                            )
                                    else:
                                        # No placeholder found - create new error embed
                                        # This may indicate a request_id mismatch between placeholder creation and skill result
                                        logger.warning(
                                            f"{log_prefix} No placeholder found for failed request {request_id} (key={request_id_key}). "
                                            f"Available placeholder keys: {list(placeholder_embeds_map.keys())}. Creating new error embed."
                                        )
                                        error_embed_data = await embed_service.create_processing_embed_placeholder(
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            chat_id=request_data.chat_id,
                                            message_id=request_data.message_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            task_id=task_id,
                                            metadata=request_metadata_with_provider,
                                            log_prefix=f"{log_prefix}[request_id={request_id}]"
                                        )
                                        
                                        if error_embed_data:
                                            error_embed_id = error_embed_data.get("embed_id")
                                            updated_error_embed = await embed_service.update_embed_status_to_error(
                                                embed_id=error_embed_id,
                                                app_id=app_id,
                                                skill_id=skill_id,
                                                error_message=error_message,
                                                chat_id=request_data.chat_id,
                                                message_id=request_data.message_id,
                                                user_id=request_data.user_id,
                                                user_id_hash=request_data.user_id_hash,
                                                user_vault_key_id=user_vault_key_id,
                                                task_id=task_id,
                                                log_prefix=f"{log_prefix}[request_id={request_id}]"
                                            )
                                            
                                            if updated_error_embed:
                                                updated_error_embed["request_id"] = request_id
                                                updated_error_embed["request_metadata"] = request_metadata
                                                updated_embed_data_list.append(updated_error_embed)
                                                failed_embed_ids.add(error_embed_id)
                                    continue
                                
                                # Request succeeded - update placeholder or create new embed (use normalized key)
                                matching_placeholder = placeholder_embeds_map.get(request_id_key) if request_id_key else None
                                if matching_placeholder:
                                    # Update existing placeholder with results
                                    placeholder_embed_id = matching_placeholder.get("embed_id")
                                    logger.info(
                                        f"{log_prefix} Updating placeholder {placeholder_embed_id} with results for request {request_id}"
                                    )
                                    
                                    # CRITICAL: Pass request_results directly — for grouped multi-request
                                    # skills, grouped_results[i]["results"] was already annotated with
                                    # pre-generated embed_ref slugs in the results_with_refs block above
                                    # (via in-place patch of grouped_results). So request_results here
                                    # already carries embed_ref → embed_service will reuse it, not regenerate.
                                    updated_embed_data = await embed_service.update_embed_with_results(
                                        embed_id=placeholder_embed_id,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=request_results,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=f"{log_prefix}[request_id={request_id}]",
                                        request_metadata=request_metadata_with_provider
                                    )
                                    
                                    if updated_embed_data:
                                        # Generate embed_reference for the updated embed (same embed_id, so same reference)
                                        # Note: Placeholder embeds were already yielded at creation time (line ~949)
                                        # Mark as "from_placeholder" so we don't yield duplicates later
                                        # CRITICAL: Include app_id and skill_id so frontend can properly group embeds
                                        # by app+skill type (e.g., web.search embeds grouped separately from code.get_docs).
                                        # ALSO include query/provider when available so the UI can render the query
                                        # even if the parent embed content is missing metadata.
                                        embed_reference_payload = {
                                            "type": "app_skill_use",
                                            "embed_id": placeholder_embed_id,
                                            "app_id": app_id,
                                            "skill_id": skill_id
                                        }
                                        # Include query and provider from request_metadata for UI rendering
                                        if request_metadata_with_provider.get("query"):
                                            embed_reference_payload["query"] = request_metadata_with_provider["query"]
                                        if request_metadata_with_provider.get("provider"):
                                            embed_reference_payload["provider"] = request_metadata_with_provider["provider"]
                                        if request_metadata_with_provider.get("providers"):
                                            embed_reference_payload["providers"] = request_metadata_with_provider["providers"]
                                        updated_embed_data["embed_reference"] = json.dumps(embed_reference_payload)
                                        updated_embed_data["request_id"] = request_id
                                        updated_embed_data["request_metadata"] = request_metadata
                                        updated_embed_data["from_placeholder"] = True  # Flag: already yielded
                                        updated_embed_data_list.append(updated_embed_data)
                                        logger.info(
                                            f"{log_prefix} Updated placeholder {placeholder_embed_id} with results for request {request_id}: "
                                            f"child_count={len(updated_embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to update placeholder for request {request_id}")
                                else:
                                    # No placeholder found - create new embed
                                    # This is a NEW embed, not from a placeholder, so we'll need to yield it
                                    logger.info(
                                        f"{log_prefix} No placeholder found for request {request_id}, creating new embed"
                                    )
                                    embed_data = await embed_service.create_embeds_from_skill_results(
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=request_results,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=f"{log_prefix}[request_id={request_id}]",
                                        request_metadata=request_metadata_with_provider
                                    )
                                    
                                    if embed_data:
                                        embed_data["request_id"] = request_id
                                        embed_data["request_metadata"] = request_metadata
                                        embed_data["from_placeholder"] = False  # Flag: newly created, needs yielding
                                        updated_embed_data_list.append(embed_data)
                                        logger.info(
                                            f"{log_prefix} Created embed {embed_data.get('parent_embed_id')} for request {request_id}: "
                                            f"child_count={len(embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to create embed for request {request_id}")
                            
                            # Stream embed references ONLY for newly created embeds (not from placeholders)
                            # Placeholder embed references were already yielded at creation time (line ~949)
                            # to allow the frontend to show "loading" state immediately.
                            # Yielding them again would cause duplicate embed references in the message.
                            for embed_data in updated_embed_data_list:
                                # Skip embeds that came from placeholders - they were already yielded
                                if embed_data.get("from_placeholder"):
                                    logger.debug(
                                        f"{log_prefix} Skipping duplicate yield for placeholder embed: "
                                        f"request_id={embed_data.get('request_id')}"
                                    )
                                    continue
                                    
                                embed_reference = embed_data.get("embed_reference")
                                if embed_reference:
                                    embed_code_block = f"```json\n{embed_reference}\n```\n\n"
                                    yield embed_code_block
                                    logger.debug(f"{log_prefix} Streamed embed reference for request {embed_data.get('request_id')}")
                        else:
                            # Single request: Update the existing placeholder embed
                            if placeholder_embed_data:
                                # CRITICAL: Check if placeholder_embed_data has "multiple" structure but we fell here
                                # because is_multiple_requests was False (e.g., skill returned non-grouped results)
                                # In this case, we need to update each placeholder with the same results
                                if isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                                    # Multiple placeholders exist but results aren't grouped - update all with combined results
                                    placeholders_list = placeholder_embed_data.get("placeholders", [])
                                    logger.warning(
                                        f"{log_prefix} Multiple placeholders ({len(placeholders_list)}) but results not grouped. "
                                        f"Will update each placeholder with combined results."
                                    )
                                    
                                    for idx, placeholder in enumerate(placeholders_list):
                                        embed_id = placeholder.get("embed_id")
                                        if not embed_id:
                                            continue
                                        
                                        # Use placeholder's request_metadata if available
                                        placeholder_metadata = {
                                            "query": placeholder.get("query"),
                                            "provider": placeholder.get("provider", "Brave Search" if skill_id == "search" and app_id != "maps" else None)
                                        }
                                        # Filter out None values
                                        placeholder_metadata = {k: v for k, v in placeholder_metadata.items() if v is not None}
                                        
                                        # CRITICAL: Pass results_with_refs (pre-generated embed_ref slugs)
                                        updated_embed_data = await embed_service.update_embed_with_results(
                                            embed_id=embed_id,
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            results=results_with_refs,  # Pre-annotated with embed_ref
                                            chat_id=request_data.chat_id,
                                            message_id=request_data.message_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            task_id=task_id,
                                            log_prefix=f"{log_prefix}[placeholder_{idx}]",
                                            request_metadata=placeholder_metadata
                                        )
                                        
                                        if updated_embed_data:
                                            updated_embed_data_list.append(updated_embed_data)
                                            logger.info(
                                                f"{log_prefix} Updated placeholder {idx}/{len(placeholders_list)} "
                                                f"(embed_id={embed_id}) with combined results"
                                            )
                                else:
                                    # Standard single placeholder - extract its embed_id directly
                                    single_embed_id = placeholder_embed_data.get('embed_id')
                                    
                                    # Extract metadata from parsed_args for single request
                                    # This preserves input parameters (query, url, provider, etc.) in the embed
                                    single_request_metadata = {}
                                    if parsed_args and isinstance(parsed_args, dict):
                                        # Copy all input parameters except internal fields
                                        for key, value in parsed_args.items():
                                            if key not in ['requests']:  # Skip requests array for single request
                                                single_request_metadata[key] = value
                                        
                                        # If we have a requests array with one item, extract from that
                                        if "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                            first_request = parsed_args["requests"][0]
                                            if isinstance(first_request, dict):
                                                # Copy all fields from the first request
                                                for key, value in first_request.items():
                                                    if key != "id":  # Skip id field
                                                        single_request_metadata[key] = value
                                    
                                    # Validate/set provider for search skills against skill's known
                                    # providers list to prevent LLM hallucination.
                                    if skill_id == "search" or "provider" in single_request_metadata:
                                        validated_provider = _validate_skill_provider(
                                            provider=single_request_metadata.get("provider"),
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            discovered_apps_metadata=discovered_apps_metadata,
                                            log_prefix=log_prefix,
                                        )
                                        if validated_provider is not None:
                                            single_request_metadata["provider"] = validated_provider
                                    
                                    # DEBUG: Log what's being passed to update_embed_with_results
                                    if results and len(results) > 0:
                                        first_result = results[0]
                                        # Guard against non-dict results (e.g. images-view returns
                                        # a list of content blocks, not a dict)
                                        if isinstance(first_result, dict):
                                            logger.info(
                                                f"{log_prefix} [EMBED_DEBUG] BEFORE update_embed_with_results - "
                                                f"results[0] keys: {list(first_result.keys())}, "
                                                f"has_thumbnail={'thumbnail' in first_result}, "
                                                f"has_meta_url={'meta_url' in first_result}, "
                                                f"thumbnail={first_result.get('thumbnail')}, "
                                                f"meta_url={first_result.get('meta_url')}"
                                            )
                                        else:
                                            logger.info(
                                                f"{log_prefix} [EMBED_DEBUG] BEFORE update_embed_with_results - "
                                                f"results[0] type: {type(first_result).__name__}, "
                                                f"len: {len(first_result) if hasattr(first_result, '__len__') else 'N/A'}"
                                            )
                                    
                                    # CRITICAL: Pass results_with_refs so embed_service receives the
                                    # pre-generated embed_ref slugs (same slugs the LLM saw in the
                                    # tool_result_content_str). This prevents the slug-mismatch bug.
                                    updated_embed_data = await embed_service.update_embed_with_results(
                                        embed_id=single_embed_id,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=results_with_refs,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=log_prefix,
                                        request_metadata=single_request_metadata
                                    )

                                if updated_embed_data:
                                    updated_embed_data_list.append(updated_embed_data)
                                    logger.info(
                                        f"{log_prefix} Updated embed {updated_embed_data.get('embed_id')} with results: "
                                        f"child_count={len(updated_embed_data.get('child_embed_ids', []))}, "
                                        f"status={updated_embed_data.get('status')}"
                                    )
                                else:
                                    logger.warning(f"{log_prefix} Failed to update embed for '{tool_name}'")
                            else:
                                # No placeholder, create new embed
                                # CRITICAL: Pass results_with_refs (pre-generated embed_ref slugs)
                                embed_data = await embed_service.create_embeds_from_skill_results(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    results=results_with_refs,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                                
                                if embed_data:
                                    updated_embed_data_list.append(embed_data)
                                    # Stream embed reference
                                    embed_reference = embed_data.get("embed_reference")
                                    if embed_reference:
                                        embed_code_block = f"```json\n{embed_reference}\n```\n\n"
                                        yield embed_code_block
                    except Exception as e:
                        logger.error(f"{log_prefix} Error creating/updating embeds for '{tool_name}': {e}", exc_info=True)
                        # Continue without embed update - don't fail the entire skill execution

                # For multimodal results (e.g. images.view), the embed update block was skipped above.
                # If a placeholder embed was created for this tool call, mark it as "finished"
                # using only the text block (strip image bytes — we don't want to cache MBs of
                # base64 image data in the embed content).
                if is_multimodal_result and placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService
                        embed_service_mm = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        mm_embed_id = placeholder_embed_data.get("embed_id")
                        if mm_embed_id:
                            # Extract only the text blocks — skip image_url blocks to avoid
                            # storing large base64 blobs in the embed cache.
                            text_only_results = [
                                block for block in results[0]
                                if isinstance(block, dict) and block.get("type") == "text"
                            ]
                            if not text_only_results:
                                text_only_results = [{"type": "text", "text": f"[{tool_name}]"}]

                            # For images.view (and similar multimodal skills that reference an
                            # original upload embed), resolve file_path → original upload embed_id
                            # via the file_path_index so the finished TOON content includes
                            # embed_id. The frontend uses this to fetch S3/AES data from the
                            # original upload embed and display the decrypted image preview.
                            mm_request_metadata: dict[str, Any] | None = None
                            _mm_file_path_index = getattr(request_data, "embed_file_path_index", None) or {}
                            _mm_file_path = skill_arguments.get("file_path", "")
                            if _mm_file_path and _mm_file_path_index:
                                _mm_original_embed_id = _mm_file_path_index.get(_mm_file_path)
                                if _mm_original_embed_id:
                                    mm_request_metadata = {
                                        "embed_id": _mm_original_embed_id,
                                        "file_path": _mm_file_path,
                                    }
                                    logger.info(
                                        f"{log_prefix} Multimodal embed {mm_embed_id}: resolved "
                                        f"file_path='{_mm_file_path}' → original embed_id={_mm_original_embed_id}"
                                    )
                                else:
                                    logger.warning(
                                        f"{log_prefix} Multimodal embed {mm_embed_id}: file_path "
                                        f"'{_mm_file_path}' not found in file_path_index "
                                        f"(keys: {list(_mm_file_path_index.keys())})"
                                    )

                            logger.info(
                                f"{log_prefix} Updating multimodal placeholder embed {mm_embed_id} "
                                f"to finished (text-only, {len(text_only_results)} block(s))"
                            )
                            await embed_service_mm.update_embed_with_results(
                                embed_id=mm_embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                results=text_only_results,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix,
                                request_metadata=mm_request_metadata,
                            )
                    except Exception as e:
                        logger.warning(f"{log_prefix} Failed to finalize multimodal placeholder embed: {e}", exc_info=True)

                # Publish "finished" status with preview data
                # This triggers WebSocket event to update the frontend embed preview
                # NOTE: Skip for async skills - status was already published in the async detection block above
                if not is_async_skill:
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="finished",
                        preview_data=preview_data if preview_data else None
                    )

                # Publish embed_update events to notify frontend that embeds have been updated
                # For multiple requests, publish one event per embed
                # NOTE: Skip for async skills - the Celery task handles WebSocket notifications
                # CRITICAL FIX: Skip embeds that already had send_embed_data published inside
                # update_embed_with_results() (flagged as from_placeholder=True). Publishing both
                # send_embed_data and embed_update for the same embed causes duplicate processing
                # on the frontend, resulting in "DUPLICATE DETECTED" warnings and wasted work.
                if not is_async_skill and updated_embed_data_list and cache_service:
                    try:
                        client = await cache_service.client
                        if client:
                            import json as json_lib
                            channel_key = f"websocket:user:{request_data.user_id_hash}"
                            
                            for embed_data in updated_embed_data_list:
                                # Skip embeds that were already sent via send_embed_data_to_client()
                                # inside update_embed_with_results() - sending embed_update would be
                                # redundant and cause the frontend to process the same embed twice
                                if embed_data.get("from_placeholder"):
                                    embed_id = embed_data.get("parent_embed_id") or embed_data.get("embed_id")
                                    logger.debug(
                                        f"{log_prefix} Skipping embed_update for {embed_id} - already sent via send_embed_data in update_embed_with_results"
                                    )
                                    continue

                                embed_id = embed_data.get("parent_embed_id") or embed_data.get("embed_id")
                                if not embed_id:
                                    continue
                                
                                embed_update_payload = {
                                    "type": "embed_update",
                                    "event_for_client": "embed_update",
                                    "embed_id": embed_id,
                                    "chat_id": request_data.chat_id,
                                    "message_id": request_data.message_id,
                                    "user_id_uuid": request_data.user_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "status": "finished",
                                    "child_embed_ids": embed_data.get("child_embed_ids", [])
                                }

                                await client.publish(channel_key, json_lib.dumps(embed_update_payload))
                                logger.debug(f"{log_prefix} Published embed_update event for embed {embed_id}")
                        else:
                            logger.warning(f"{log_prefix} Redis client not available, skipping embed_update events")
                    except Exception as e:
                        logger.error(f"{log_prefix} Error publishing embed_update events: {e}", exc_info=True)
                        # Don't fail if event publish fails
                
                # Track tool call info for code block generation
                # NOTE: With new embeds architecture, embed references are streamed as chunks
                # We still track tool_call_info for TOON code block (for backward compatibility and follow-up questions)
                # For multiple requests, track all embed references
                embed_references = []
                embed_ids = []
                if updated_embed_data_list:
                    for embed_data in updated_embed_data_list:
                        embed_ref = embed_data.get("embed_reference")
                        embed_id = embed_data.get("parent_embed_id") or embed_data.get("embed_id")
                        if embed_ref:
                            embed_references.append(embed_ref)
                        if embed_id:
                            embed_ids.append(embed_id)
                elif placeholder_embed_data:
                    # Fallback to placeholder for single request
                    embed_ref = placeholder_embed_data.get("embed_reference")
                    embed_id = placeholder_embed_data.get("embed_id")
                    if embed_ref:
                        embed_references.append(embed_ref)
                    if embed_id:
                        embed_ids.append(embed_id)
                
                tool_call_info = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "input": parsed_args,  # Tool input arguments
                    "preview_data": preview_data,  # Metadata + results_toon (contains full TOON-encoded results)
                    "ignore_fields_for_inference": ignore_fields_for_inference,  # Fields excluded from LLM inference
                    "embed_reference": embed_references[0] if embed_references else None,  # First embed reference (for backward compatibility)
                    "embed_references": embed_references if len(embed_references) > 1 else None,  # All embed references (for multiple requests)
                    "embed_id": embed_ids[0] if embed_ids else None,  # First embed ID (for backward compatibility)
                    "embed_ids": embed_ids if len(embed_ids) > 1 else None  # All embed IDs (for multiple requests)
                }
                tool_calls_info.append(tool_call_info)
                logger.debug(
                    f"{log_prefix} Tracked tool call info for '{tool_name}': "
                    f"app_id={app_id}, skill_id={skill_id}, embed_count={len(embed_ids)}, "
                    f"results_toon_length={len(preview_data.get('results_toon', ''))}"
                )

                # Track images-search execution so we can inject embed preview instructions
                if app_id == "images" and skill_id == "search":
                    images_search_executed = True

            except json.JSONDecodeError as e:
                logger.error(f"{log_prefix} Invalid JSON in tool arguments for '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid JSON in function arguments.", "details": str(e)})
                # Set ignore_fields_for_inference to None since JSON parsing failed
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    tool_call_info = {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "input": tool_arguments_str,  # Raw string since parsing failed
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": "Invalid JSON in function arguments"
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        error_eid = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message="Invalid JSON in function arguments",
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid:
                            failed_embed_ids.add(error_eid)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid JSON in function arguments"
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            except ValueError as e:
                # Invalid tool name format - include available tools in error message
                # so the LLM can self-correct on the next iteration
                available_tool_names = [t["function"]["name"] for t in available_tools_for_llm] if available_tools_for_llm else []
                logger.error(f"{log_prefix} Invalid tool name format '{tool_name}': {e}")
                tool_result_content_str = json.dumps({
                    "error": f"Tool '{tool_name}' does not exist.",
                    "available_tools": available_tool_names,
                    "hint": "Use one of the available tools listed above, or respond with text if no suitable tool exists."
                })
                # Set ignore_fields_for_inference to None since invalid tool name format
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    tool_call_info = {
                        "app_id": "unknown",
                        "skill_id": "unknown",
                        "input": tool_arguments_str,
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": f"Invalid tool name format: {str(e)}"
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        # Try to extract app_id and skill_id, fallback to unknown
                        try:
                            app_id, skill_id = tool_name.split('-', 1)
                        except ValueError:
                            app_id = "unknown"
                            skill_id = "unknown"
                        error_eid2 = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid2,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message="Invalid tool name format",
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid2:
                            failed_embed_ids.add(error_eid2)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid tool name format"
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            except Exception as e:
                logger.error(f"{log_prefix} Error executing tool '{tool_name}': {e}", exc_info=True)
                tool_result_content_str = json.dumps({"error": "Skill execution failed.", "details": str(e)})
                # Set ignore_fields_for_inference to None since skill execution failed
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    tool_call_info = {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "input": parsed_args if 'parsed_args' in locals() else tool_arguments_str,
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": str(e)
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        error_eid3 = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid3,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message=str(e),
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid3:
                            failed_embed_ids.add(error_eid3)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error=str(e)
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            
            # Add tool response to message history
            # Store full results as TOON in content, and include ignore_fields_for_inference metadata
            # This allows follow-up requests to filter tool results correctly when reading from history
            tool_response_message = {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": tool_result_content_str,  # TOON-encoded full results (all fields preserved)
                "ignore_fields_for_inference": ignore_fields_for_inference  # Store for follow-up requests
            }
            current_message_history.append(tool_response_message)

        # === MAX ITERATIONS HANDLING ===
        # If we're on the second-to-last iteration and the LLM is still requesting tools,
        # force the next (final) iteration to generate an answer without tools.
        # This ensures the user ALWAYS gets an answer based on gathered information.
        if iteration == MAX_TOOL_CALL_ITERATIONS - 2:
            # We're on the second-to-last iteration - force the final iteration to answer
            force_no_tools = True
            if not budget_warning_injected:
                budget_warning_injected = True  # Also inject budget warning
            logger.info(
                f"{log_prefix} [MAX_ITERATIONS] Approaching max iterations ({iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}). "
                f"Next iteration will force tool_choice='none' to generate final answer."
            )
        elif iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            # We're on the last iteration - if we still have tool calls, that's unexpected
            # (because we should have forced no tools in the previous iteration)
            # Log this as a warning but don't show error to user - we already have tool results
            logger.warning(
                f"{log_prefix} [MAX_ITERATIONS] Final iteration reached with tool calls still pending. "
                f"This shouldn't happen if force_no_tools was set correctly. Breaking loop."
            )
            break

    if usage:
        # Yield cumulative token totals as a sentinel dict BEFORE the usage object.
        # stream_consumer.py reads this to bill for ALL LLM calls in this turn rather
        # than only the last one.  The sentinel is always emitted when we have usage
        # data — when no tools were used there is exactly one iteration so the
        # cumulative totals equal the single-iteration totals (zero-overhead path).
        #
        # Fields:
        #   total_input_tokens  — sum of input tokens across every LLM call in this turn
        #   total_output_tokens — sum of output tokens across every LLM call in this turn
        #   tool_inference_iterations — number of extra LLM calls triggered by tool use
        #                               (0 = no tools used, 1 = one tool round, etc.)
        #
        # A future FAQ link can explain why input_tokens may be higher than expected:
        # each tool result is injected back into the context, making the next call's
        # input larger.  See docs/billing.md (TODO: create) for the full explanation.
        yield {
            "__cumulative_llm_usage__": True,
            "total_input_tokens": cumulative_input_tokens,
            "total_output_tokens": cumulative_output_tokens,
            "tool_inference_iterations": tool_inference_iterations,
        }
        logger.info(
            f"{log_prefix} [CUMULATIVE_TOKENS] Final totals: "
            f"{cumulative_input_tokens} input tokens, {cumulative_output_tokens} output tokens, "
            f"{tool_inference_iterations} tool inference iteration(s)."
        )
        yield usage

    # Yield tool calls info as a special marker at the end of the stream
    # The stream consumer will extract this and format it as a code block
    if tool_calls_info:
        # Use a special dict marker that the stream consumer can detect
        yield {"__tool_calls_info__": tool_calls_info}
        logger.debug(f"{log_prefix} Yielding tool calls info for {len(tool_calls_info)} tool call(s)")

    # Yield failed embed IDs so the stream consumer can strip their references
    # from the final message content before persisting. Without this, the message
    # would contain embed references for embeds that no longer exist, causing
    # the client to re-request them on every page load.
    if failed_embed_ids:
        yield {"__failed_embed_ids__": failed_embed_ids}
        logger.info(
            f"{log_prefix} Yielding {len(failed_embed_ids)} failed embed ID(s) for content cleanup: "
            f"{failed_embed_ids}"
        )

    logger.info(f"{log_prefix} Main processing stream finished.")


def _normalize_skill_arguments(
    arguments: Dict[str, Any],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, Any],
    task_id: str,
    message_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Normalizes LLM-generated skill arguments to match the expected schema format.
    
    LLMs sometimes send flat arguments (e.g., {"prompt": "a cat", "aspect_ratio": "1:1"})
    instead of the required wrapped format (e.g., {"requests": [{"prompt": "a cat", "aspect_ratio": "1:1"}]}).
    This function detects the mismatch using the skill's tool_schema and wraps the arguments
    into the correct format.
    
    This handles the case where:
    - The tool_schema declares "requests" as a required top-level property of type "array"
    - The LLM sends flat arguments without a "requests" key
    - The flat arguments match the items schema of the "requests" array
    
    Special recovery case — empty arguments (LLM sends "{}"):
    - When the LLM provides completely empty arguments AND the skill requires a "requests"
      array with a "query" field (e.g. web-search), the last user message from message_history
      is used as the query. This covers a known bug where some LLM providers (e.g. Qwen via
      Cerebras) emit an empty tool-call arguments string for the web-search tool.
    
    Args:
        arguments: The parsed tool call arguments from the LLM
        app_id: The app ID
        skill_id: The skill ID
        discovered_apps_metadata: The full app metadata (contains tool_schema)
        task_id: Task ID for logging
        message_history: Optional conversation history used to recover a query when the LLM
            sends empty arguments. Each entry is a dict with at least "role" and "content".
        
    Returns:
        Normalized arguments dict. Returns the original arguments unchanged if no
        normalization is needed or if the schema can't be determined.
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    # Look up the skill's tool_schema FIRST — we need to know whether this skill
    # expects a "requests" array before we can decide how to handle incoming args.
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata or not app_metadata.skills:
        return arguments
    
    skill_def = None
    for skill in app_metadata.skills:
        if skill.id == skill_id:
            skill_def = skill
            break
    
    if not skill_def or not skill_def.tool_schema:
        return arguments
    
    schema = skill_def.tool_schema
    schema_properties = schema.get("properties", {})
    schema_required = schema.get("required", [])
    
    schema_expects_requests = (
        "requests" in schema_properties
        and schema_properties["requests"].get("type") == "array"
        and "requests" in schema_required
    )
    
    if "requests" in arguments:
        # The LLM sent a "requests" key.
        if schema_expects_requests:
            # Schema also wants "requests" — no normalization needed.
            return arguments
        else:
            # Schema does NOT have "requests" (flat-schema skill like pdf.read/view/search).
            # The LLM mis-wrapped flat args as {"requests": [{"file_path": "x.pdf", ...}]}.
            # Extract the first item and flatten it so the skill receives the expected kwargs.
            requests_list = arguments.get("requests")
            if isinstance(requests_list, list) and len(requests_list) > 0:
                if len(requests_list) > 1:
                    logger.warning(
                        f"{log_prefix} [NORMALIZE] LLM sent {len(requests_list)} items in "
                        f"'requests' for flat-schema skill '{app_id}.{skill_id}' (schema has "
                        f"no 'requests' property). Using first item only and discarding the rest."
                    )
                flat_item = requests_list[0]
                if isinstance(flat_item, dict):
                    # Merge flat item with underscore-prefixed metadata keys from the outer dict.
                    normalized = {k: v for k, v in arguments.items() if k.startswith("_")}
                    normalized.update({k: v for k, v in flat_item.items() if not k.startswith("_")})
                    logger.warning(
                        f"{log_prefix} [NORMALIZE] Unwrapped 'requests[0]' into flat args for "
                        f"'{app_id}.{skill_id}'. Flat keys: {list(flat_item.keys())}. "
                        f"LLM incorrectly wrapped flat-schema skill args in a 'requests' array."
                    )
                    return normalized
            # Unexpected shape — return as-is and let validation raise a clear error.
            logger.warning(
                f"{log_prefix} [NORMALIZE] LLM sent 'requests' for flat-schema skill "
                f"'{app_id}.{skill_id}' but 'requests' value is not a non-empty list "
                f"(type={type(arguments.get('requests')).__name__}). Passing through as-is."
            )
            return arguments
    
    # No "requests" key in arguments.
    if not schema_expects_requests:
        # Flat args for flat-schema skill — no normalization needed.
        return arguments
    
    # The schema requires a "requests" array but the LLM sent flat arguments.
    # Extract non-metadata keys (keys that don't start with "_") as the request object.
    flat_request = {k: v for k, v in arguments.items() if not k.startswith("_")}
    
    if not flat_request:
        # LLM sent completely empty arguments (e.g. arguments="{}").
        # Attempt recovery: check if the "requests" items schema requires a "query" field.
        # If so, extract the last user message from history and use it as the query.
        # This covers a known Qwen/Cerebras bug where web-search is called with no args.
        items_schema = schema_properties["requests"].get("items", {})
        items_required = items_schema.get("required", [])
        
        if "query" in items_required and message_history:
            # Find the last user message in history (most recent first)
            last_user_text: Optional[str] = None
            for msg in reversed(message_history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        last_user_text = content.strip()
                        break
                    elif isinstance(content, list):
                        # Some providers use content arrays (e.g. [{type: text, text: "..."}])
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text", "").strip()
                                if text:
                                    last_user_text = text
                                    break
                        if last_user_text:
                            break
            
            if last_user_text:
                # Preserve metadata keys (underscore-prefixed) at the top level
                normalized = {k: v for k, v in arguments.items() if k.startswith("_")}
                normalized["requests"] = [{"query": last_user_text}]
                logger.warning(
                    f"{log_prefix} [NORMALIZE] LLM sent empty arguments ('{{}}') for "
                    f"'{app_id}.{skill_id}' which requires a 'requests' array. "
                    f"Recovered query from last user message: '{last_user_text[:100]}{'...' if len(last_user_text) > 100 else ''}'. "
                    f"This is a known LLM bug (Qwen/Cerebras emitting empty tool-call args)."
                )
                return normalized
        
        # No recovery possible — return as-is and let validation raise a clear error
        logger.warning(
            f"{log_prefix} [NORMALIZE] LLM sent empty arguments ('{{}}') for "
            f"'{app_id}.{skill_id}' which requires a 'requests' array. "
            f"Cannot recover (no query field in items schema or no message history). "
            f"Skill will fail with a validation error."
        )
        return arguments
    
    # Preserve metadata keys (underscore-prefixed) at the top level
    normalized = {k: v for k, v in arguments.items() if k.startswith("_")}

    # Handle common LLM mistake: sending plural array field (e.g. "urls": ["a", "b"])
    # when the schema expects singular field per request item (e.g. "url": "a").
    # Unpack the array into individual request items so each gets its own request.
    # Known case: Gemini sends {"urls": ["https://..."]} for web-read which expects
    # {"requests": [{"url": "https://..."}]}.
    items_schema = schema_properties.get("requests", {}).get("items", {})
    items_props = items_schema.get("properties", {})
    unpacked = False
    for key, value in list(flat_request.items()):
        singular_key = key.rstrip("s")  # "urls" → "url", "queries" → "query"
        if (isinstance(value, list) and len(value) > 0
                and singular_key != key  # Only if key is actually plural
                and singular_key in items_props  # Schema has the singular form
                and key not in items_props):  # Schema does NOT have the plural form
            # Unpack: each array element becomes a separate request item
            normalized["requests"] = [{singular_key: item} for item in value]
            logger.info(
                f"{log_prefix} [NORMALIZE] Unpacked plural field '{key}' ({len(value)} items) "
                f"into individual request items with singular field '{singular_key}' for "
                f"'{app_id}.{skill_id}'. LLM sent array instead of per-item format."
            )
            unpacked = True
            break

    if not unpacked:
        normalized["requests"] = [flat_request]
        logger.info(
            f"{log_prefix} [NORMALIZE] Wrapped flat arguments into 'requests' array for "
            f"'{app_id}.{skill_id}'. Original keys: {list(flat_request.keys())}. "
            f"LLM sent flat args instead of {{\"requests\": [...]}} format."
        )

    return normalized


def _validate_tool_arguments_against_schema(
    arguments: Dict[str, Any],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    task_id: str
) -> tuple[bool, Optional[str]]:
    """
    Validates tool call arguments against the original skill schema (with min/max constraints).
    
    The schema sent to LLM providers has minimum/maximum fields removed for compatibility,
    but we validate against the original schema from app.yml to ensure values are within
    acceptable ranges.
    
    Args:
        arguments: The parsed tool call arguments from the LLM
        app_id: The app ID
        skill_id: The skill ID
        discovered_apps_metadata: The full app metadata (contains original schemas with min/max)
        task_id: Task ID for logging
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    # Get the skill definition from metadata
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata or not app_metadata.skills:
        # Can't validate if metadata not available - allow through
        logger.debug(f"{log_prefix} App '{app_id}' not found in discovered apps metadata. Skipping validation.")
        return True, None
    
    skill_def = None
    for skill in app_metadata.skills:
        if skill.id == skill_id:
            skill_def = skill
            break
    
    if not skill_def or not skill_def.tool_schema:
        # Can't validate if schema not available - allow through
        logger.debug(f"{log_prefix} Skill '{skill_id}' in app '{app_id}' has no tool_schema. Skipping validation.")
        return True, None
    
    # Validate arguments against schema (recursively check min/max for integers)
    return _validate_value_against_schema(
        value=arguments,
        schema=skill_def.tool_schema,
        path="arguments"
    )


def _validate_value_against_schema(
    value: Any,
    schema: Dict[str, Any],
    path: str = ""
) -> tuple[bool, Optional[str]]:
    """
    Recursively validates a value against a JSON schema, checking minimum/maximum constraints.
    
    This function validates integer values against minimum/maximum constraints defined
    in the original schema (from app.yml). The schema sent to LLM providers has these
    fields removed, but we use the original schema for validation.
    
    Args:
        value: The value to validate
        schema: The JSON schema to validate against (from app.yml, with min/max intact)
        path: Current path in the schema (for error messages)
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not isinstance(schema, dict):
        return True, None
    
    schema_type = schema.get("type")
    
    # Validate integer constraints
    if schema_type == "integer" and isinstance(value, int):
        if "minimum" in schema and value < schema["minimum"]:
            return False, f"Value at '{path}' ({value}) is less than minimum ({schema['minimum']})"
        if "maximum" in schema and value > schema["maximum"]:
            return False, f"Value at '{path}' ({value}) is greater than maximum ({schema['maximum']})"
    
    # Recursively validate nested objects
    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in value:
                is_valid, error = _validate_value_against_schema(
                    value[prop_name],
                    prop_schema,
                    f"{path}.{prop_name}" if path else prop_name
                )
                if not is_valid:
                    return False, error
    
    # Recursively validate arrays
    if schema_type == "array" and isinstance(value, list):
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(value):
                is_valid, error = _validate_value_against_schema(
                    item,
                    items_schema,
                    f"{path}[{i}]" if path else f"[{i}]"
                )
                if not is_valid:
                    return False, error
    
    return True, None
