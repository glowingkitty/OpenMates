# backend/apps/ai/processing/main_processor.py
# Handles the main processing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import json
import httpx
import datetime
import os
from toon_format import encode

# Import Pydantic models for type hinting
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.utils.llm_utils import call_main_llm_stream
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.apps.ai.llm_providers.mistral_client import ParsedMistralToolCall, MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata, ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import ParsedAnthropicToolCall, AnthropicUsageMetadata
from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.translations import TranslationService

# Import tool generator
from backend.apps.ai.processing.tool_generator import generate_tools_from_apps
# Import skill executor
from backend.apps.ai.processing.skill_executor import execute_skill_with_multiple_requests
# Import billing utilities
from backend.shared.python_utils.billing_utils import calculate_total_credits, MINIMUM_CREDITS_CHARGED


logger = logging.getLogger(__name__)

# Max iterations for tool calling to prevent infinite loops
MAX_TOOL_CALL_ITERATIONS = 5


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
        filtered_result = result.copy()
        
        # Handle both single result dict and result dict with "previews" array
        if "previews" in filtered_result:
            # Result has a "previews" array - filter each preview
            filtered_previews = []
            for preview in filtered_result.get("previews", []):
                filtered_preview = preview.copy()
                
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
APPROX_MAX_CONVERSATION_TOKENS = 80000
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


async def _charge_skill_credits(
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    results: List[Dict[str, Any]],
    parsed_args: Dict[str, Any],
    log_prefix: str
) -> None:
    """
    Calculate and charge credits for a skill execution.
    Creates usage entry automatically via BillingService.
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
        elif skill_def.providers and len(skill_def.providers) > 0:
            # Skill doesn't have explicit pricing, but has providers - try to get provider-level pricing
            # Use the first provider (most skills will have one primary provider)
            provider_name = skill_def.providers[0]
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
        
        # Calculate credits based on skill execution
        # All skills use 'requests' array format - charge per request (units_processed)
        units_processed = None
        if "requests" in parsed_args and isinstance(parsed_args["requests"], list):
            # Count number of requests in the requests array
            units_processed = len(parsed_args["requests"])
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' executed with {units_processed} request(s) in requests array")
        else:
            # Fallback: if no requests array found, charge for single execution
            # This handles edge cases where a skill might not use the requests pattern yet
            units_processed = 1
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' has no 'requests' array, charging for single execution")
        
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
        
        # Prepare usage details
        # Include chat_id and message_id when skill is triggered in a chat context
        # These fields are important for linking usage entries to chat sessions
        # The billing service will validate and only include non-empty values
        usage_details = {
            "chat_id": request_data.chat_id,  # Always available in AskSkillRequest
            "message_id": request_data.message_id,  # Always available in AskSkillRequest
            "units_processed": units_processed
        }
        
        # Charge credits via internal API (this will also create usage entry)
        # app_id and skill_id are required and must be non-empty - they come from tool call parsing
        # The billing service will validate these fields before creating the usage entry
        charge_payload = {
            "user_id": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "credits": credits_charged,
            "skill_id": skill_id,  # Required: ID of the skill that was executed
            "app_id": app_id,  # Required: ID of the app that contains the skill
            "usage_details": usage_details  # Contains chat_id, message_id, and other optional metadata
        }
        
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        
        async with httpx.AsyncClient() as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            logger.info(f"{log_prefix} Charging {credits_charged} credits for skill '{app_id}.{skill_id}'. Payload: {charge_payload}")
            response = await client.post(url, json=charge_payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            logger.info(f"{log_prefix} Successfully charged {credits_charged} credits for skill '{app_id}.{skill_id}'. Response: {response.json()}")
            
    except httpx.HTTPStatusError as e:
        logger.error(f"{log_prefix} HTTP error charging credits for skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits for skill '{app_id}.{skill_id}': {e}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution


async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    secrets_manager: Optional[SecretsManager] = None,
    cache_service: Optional[CacheService] = None
) -> AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]]:
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")
    
    # --- Request app settings/memories from client (zero-knowledge architecture) ---
    # The server NEVER decrypts app settings/memories - client decrypts using crypto API
    # App settings/memories are stored in cache (similar to embeds) when client confirms
    # Cache key format: app_settings_memories:{user_id}:{app_id}:{item_key}
    # This is more efficient than extracting from YAML in chat history
    loaded_app_settings_and_memories_content: Dict[str, Any] = {}
    if preprocessing_results.load_app_settings_and_memories and cache_service:
        try:
            # Import helper function for creating requests
            from backend.core.api.app.utils.app_settings_memories_request import (
                create_app_settings_memories_request_message
            )
            
            requested_keys = preprocessing_results.load_app_settings_and_memories
            
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
                loaded_app_settings_and_memories_content = cached_data
            
            # Check if we need to create a new request for missing keys
            missing_keys = [key for key in requested_keys if key not in cached_data]
            
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
                    device_fingerprint_hash=None  # Will use first available device connection
                )
                
                if request_id:
                    logger.info(f"{log_prefix} Created app settings/memories request {request_id} - client will respond when ready (may be hours/days later)")
                else:
                    logger.warning(f"{log_prefix} Failed to create app settings/memories request message")
            else:
                logger.info(f"{log_prefix} All requested app settings/memories keys found in cache")
            
            # Continue processing immediately (no waiting)
            # If data is missing, the conversation continues without it
            # User can respond hours/days later, and the data will be available for the next message
            
        except Exception as e:
            logger.error(f"{log_prefix} Error handling app settings/memories requests: {e}", exc_info=True)
            # Continue without app settings/memories - don't fail the entire request

    prompt_parts = []
    now = datetime.datetime.now(datetime.timezone.utc)
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    prompt_parts.append(f"Current date and time: {date_time_str}")
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
                or (selected_model_id.split("/", 1)[-1] if selected_model_id else "AI")
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
    prompt_parts.append(base_instructions.get("base_url_sourcing_instruction", ""))
    # Add code block formatting instruction to ensure proper language and filename syntax
    # This helps with consistent parsing and rendering of code embeds
    prompt_parts.append(base_instructions.get("base_code_block_instruction", ""))
    if loaded_app_settings_and_memories_content:
        settings_and_memories_prompt_section = ["\n--- Relevant Information from Your App Settings and Memories ---"]
        for key, value in loaded_app_settings_and_memories_content.items():
            value_str = json.dumps(value) if not isinstance(value, str) else value
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
                        active_focus_prompt_text = focus_def.systemprompt
                        break
        except Exception as e:
            logger.error(f"{log_prefix} Error processing active_focus_id '{request_data.active_focus_id}': {e}", exc_info=True)
    if active_focus_prompt_text:
        prompt_parts.insert(0, f"--- Active Focus: {request_data.active_focus_id} ---\n{active_focus_prompt_text}\n--- End Active Focus ---")

    full_system_prompt = "\n\n".join(filter(None, prompt_parts))
    
    # Generate tool definitions from discovered apps using the tool generator
    # Filter by preselected skills from preprocessing (architecture: only preselected skills are forwarded)
    # Note: Empty list means no skills preselected (valid case), None should not occur
    preselected_skills = None
    if hasattr(preprocessing_results, 'relevant_app_skills'):
        if preprocessing_results.relevant_app_skills is not None:
            # Convert list to set for efficient lookup
            preselected_skills = set(preprocessing_results.relevant_app_skills)
            if preselected_skills:
                logger.debug(f"{log_prefix} Using preselected skills: {preselected_skills}")
            else:
                logger.debug(f"{log_prefix} No skills preselected (empty list) - no tools will be provided to main processing LLM")
        else:
            # None should not occur, but handle gracefully
            logger.warning(f"{log_prefix} relevant_app_skills is None (should be list or empty list). Treating as empty list.")
            preselected_skills = set()  # Empty set means no skills
    
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
    
    # Log available tools for debugging
    tool_names = [tool["function"]["name"] for tool in available_tools_for_llm]
    logger.info(f"{log_prefix} Available tools for main processing LLM ({len(available_tools_for_llm)} total): {', '.join(tool_names) if tool_names else 'None'}")
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
    
    # Track all tool calls for code block generation
    # This will be used to prepend a code block with skill input/output/metadata to the assistant response
    tool_calls_info: List[Dict[str, Any]] = []
    
    # --- End of existing logic ---

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

    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None
    
    for iteration in range(MAX_TOOL_CALL_ITERATIONS):
        logger.info(f"{log_prefix} LLM call iteration {iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}")

        llm_stream = call_main_llm_stream(
            task_id=task_id,
            system_prompt=full_system_prompt,
            message_history=current_message_history,
            model_id=preprocessing_results.selected_main_llm_model_id,
            temperature=preprocessing_results.llm_response_temp,
            secrets_manager=secrets_manager,
            tools=available_tools_for_llm if available_tools_for_llm else None,
            tool_choice="auto"
        )

        current_turn_text_buffer = []
        tool_calls_for_this_turn: List[Union[ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedOpenAIToolCall]] = []
        llm_turn_had_content = False
        
        # Dictionary to store placeholder embeds created for tool calls during stream processing
        # Key: tool_call_id, Value: placeholder_embed_data dict
        # This allows us to create placeholders IMMEDIATELY when tool calls are detected,
        # showing the "processing" state to users before skill execution starts
        inline_placeholder_embeds: Dict[str, Dict[str, Any]] = {}
        
        async for chunk in aggregate_paragraphs(llm_stream):
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                continue
            if isinstance(chunk, (ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedOpenAIToolCall)):
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
                    
                    # Create placeholder embed IMMEDIATELY (before skill execution)
                    if cache_service and user_vault_key_id and directus_service and app_id != "unknown":
                        from backend.core.api.app.services.embed_service import EmbedService
                        from backend.core.api.app.utils.encryption import EncryptionService
                        
                        encryption_service = EncryptionService()
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
                                
                                # Provider from request or fallback (for search skills)
                                if "provider" not in request_metadata and skill_id == "search":
                                    if app_id == "maps":
                                        request_metadata["provider"] = "Google Maps"
                                    else:
                                        request_metadata["provider"] = "Brave Search"
                                
                                # Add request ID for later matching (use id if present, otherwise use index)
                                request_id = request.get("id", request_idx)
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
                                            f"query={request_metadata.get('query', 'N/A')}"
                                        )
                            
                            # Store list of placeholders for later matching
                            if placeholder_embeds_list:
                                inline_placeholder_embeds[tool_call_id] = {
                                    "multiple": True,
                                    "placeholders": placeholder_embeds_list
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
                            
                            # Provider fallback for search skills
                            if "provider" not in metadata and skill_id == "search":
                                if app_id == "maps":
                                    metadata["provider"] = "Google Maps"
                                elif app_id == "web":
                                    metadata["provider"] = "Brave Search"
                                elif app_id == "news":
                                    metadata["provider"] = "Brave Search"
                                elif app_id == "videos":
                                    metadata["provider"] = "Brave Search"
                                else:
                                    metadata["provider"] = "Brave Search"  # Default fallback
                            
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
                            else:
                                logger.warning(f"{log_prefix} INLINE: Failed to create placeholder embed for '{tool_name}'")
                except Exception as e:
                    # Don't fail the stream processing if inline placeholder creation fails
                    logger.error(f"{log_prefix} INLINE: Error creating placeholder during stream: {e}", exc_info=True)
                
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

        final_buffered_text_for_turn = "".join(current_turn_text_buffer)

        if not tool_calls_for_this_turn:
            break

        logger.info(f"{log_prefix} Processing {len(tool_calls_for_this_turn)} tool call(s).")
        
        assistant_message_content_for_history = final_buffered_text_for_turn
        assistant_message_tool_calls_formatted = [{"id": tc.tool_call_id, "type": "function", "function": {"name": tc.function_name, "arguments": tc.function_arguments_raw}} for tc in tool_calls_for_this_turn]
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
                            from backend.core.api.app.utils.encryption import EncryptionService

                            encryption_service = EncryptionService()
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
                            
                            # Direct provider
                            if "provider" in parsed_args:
                                metadata["provider"] = parsed_args["provider"]
                            # Nested provider
                            elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                first_request = parsed_args["requests"][0]
                                if isinstance(first_request, dict) and "provider" in first_request:
                                    metadata["provider"] = first_request["provider"]
                            
                            # Default provider for web search
                            if skill_id == "search" and "provider" not in metadata:
                                metadata["provider"] = "Brave Search"

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
                results = await execute_skill_with_multiple_requests(
                    app_id=app_id,
                    skill_id=skill_id,
                    arguments=parsed_args,
                    timeout=30.0,
                    chat_id=request_data.chat_id,
                    message_id=request_data.message_id
                )

                # Normalize skill responses that wrap actual results in a "results" field (e.g., web search)
                # execute_skill_with_multiple_requests returns one entry per request, but search skills return
                # a response object with its own "results" array.
                # 
                # CRITICAL: Preserve grouped structure for embed creation (multiple requests = multiple embeds)
                # Flatten only for LLM inference (token efficiency)
                response_ignore_fields: Optional[List[str]] = None
                first_response: Optional[Dict[str, Any]] = None  # Initialize to avoid UnboundLocalError
                grouped_results: Optional[List[Dict[str, Any]]] = None  # Preserve grouping for embed creation
                
                if results and all(isinstance(r, dict) and "results" in r for r in results):
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
                preview_data: Dict[str, Any] = {}
                
                # Extract query from input arguments if available (for search skills)
                # This is used by frontend for preview display
                if parsed_args and isinstance(parsed_args, dict):
                    # Try to extract query from various possible input structures
                    if "query" in parsed_args:
                        preview_data["query"] = parsed_args["query"]
                    elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                        first_request = parsed_args["requests"][0]
                        if isinstance(first_request, dict) and "query" in first_request:
                            preview_data["query"] = first_request["query"]
                
                # Extract provider from response if available
                # This is used by frontend for preview display
                if first_response and isinstance(first_response, dict):
                    if "provider" in first_response:
                        preview_data["provider"] = first_response["provider"]
                
                # Add result count (can be derived from results, but useful for frontend)
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
                
                # Filter results for current LLM inference (removes non-essential fields to reduce tokens)
                # Full results are kept in preview_data for UI rendering and will be stored in chat history
                filtered_results = _filter_skill_results_for_llm(results, ignore_fields_for_inference)
                
                # CRITICAL: Store FULL results (not filtered) in chat history for persistence
                # This ensures all fields from Brave search (page_age, profile.name, url, etc.) are available
                # for future LLM calls and UI rendering. The filtered version is only used for the current LLM call.
                # Convert FULL results to TOON format for chat history storage
                # TOON format reduces token usage by 30-60% compared to JSON while preserving all fields
                # 
                # IMPORTANT: Flatten nested objects before encoding to enable TOON tabular format
                # This ensures efficient encoding with tabular arrays instead of repeated field names
                try:
                    # DEBUG: Log original JSON structure (first 15 lines)
                    json_before = json.dumps(results, indent=2) if len(results) == 1 else json.dumps({"results": results, "count": len(results)}, indent=2)
                    json_lines = json_before.split('\n')
                    logger.info(f"{log_prefix} === TOON CONVERSION DEBUG (chat history) ===")
                    logger.info(f"{log_prefix} Original JSON structure (first 15 lines, {len(json_before)} chars total):")
                    if len(results) == 1:
                        # Single result - flatten and encode full result as TOON for chat history
                        flattened_result = _flatten_for_toon_tabular(results[0])
                        tool_result_content_str = encode(flattened_result)
                    else:
                        # Multiple results - flatten each result, then combine and encode as TOON
                        # Flattening enables TOON to use tabular format for uniform objects
                        flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                        tool_result_content_str = encode({"results": flattened_results, "count": len(results)})
                    
                    logger.debug(f"{log_prefix} TOON conversion (chat history) length={len(tool_result_content_str)} chars")
                    
                    logger.debug(
                        f"{log_prefix} Skill '{tool_name}' executed successfully, returned {len(results)} result(s). "
                        f"Full results stored in chat history (all fields preserved). "
                        f"Filtered {len(filtered_results)} result(s) used for current LLM call (ignored fields: {ignore_fields_for_inference or 'none'})"
                    )
                except Exception as e:
                    # Fallback to JSON if TOON encoding fails
                    logger.warning(f"{log_prefix} TOON encoding failed for skill '{tool_name}', falling back to JSON: {e}")
                    if len(results) == 1:
                        tool_result_content_str = json.dumps(results[0])
                    else:
                        tool_result_content_str = json.dumps({"results": results, "count": len(results)})
                
                # Calculate and charge credits for skill execution
                await _charge_skill_credits(
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    discovered_apps_metadata=discovered_apps_metadata,
                    results=results,
                    parsed_args=parsed_args,
                    log_prefix=log_prefix
                )
                
                # STEP 3: Create embeds from results
                # For multiple requests: Create one app_skill_use embed per request group
                # For single request: Update the existing placeholder embed
                updated_embed_data_list: List[Dict[str, Any]] = []
                if cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService
                        from backend.core.api.app.utils.encryption import EncryptionService

                        encryption_service = EncryptionService()
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
                            requests_list = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                            request_metadata_map = {}
                            for req in requests_list:
                                if isinstance(req, dict) and "id" in req:
                                    request_metadata_map[req["id"]] = req
                            
                            for grouped_result in grouped_results:
                                request_id = grouped_result.get("id")
                                request_results = grouped_result.get("results", [])
                                
                                # Normalize request_id to string for consistent matching with placeholders
                                request_id_key = str(request_id) if request_id is not None else None
                                
                                logger.debug(
                                    f"{log_prefix} Processing grouped result: request_id={request_id} (key={request_id_key}), "
                                    f"result_count={len(request_results)}"
                                )
                                
                                # Get request metadata (query, url, etc.) for this specific request
                                # Try both original request_id and normalized key
                                request_metadata = request_metadata_map.get(request_id, request_metadata_map.get(request_id_key, {}))
                                
                                # Include provider from first_response if available
                                request_metadata_with_provider = request_metadata.copy()
                                if first_response and isinstance(first_response, dict) and "provider" in first_response:
                                    request_metadata_with_provider["provider"] = first_response["provider"]
                                
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
                                            f"{log_prefix} Updating placeholder {placeholder_embed_id} to error status for failed request {request_id}"
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
                                                updated_error_embed["embed_reference"] = json.dumps({
                                                    "type": "app_skill_use",
                                                    "embed_id": placeholder_embed_id
                                                })
                                                updated_error_embed["request_id"] = request_id
                                                updated_error_embed["request_metadata"] = request_metadata
                                                updated_embed_data_list.append(updated_error_embed)
                                                logger.info(
                                                    f"{log_prefix} Updated placeholder {placeholder_embed_id} to error for request {request_id}"
                                                )
                                        except Exception as error_update_error:
                                            logger.warning(
                                                f"{log_prefix} Failed to update placeholder to error status: {error_update_error}"
                                            )
                                    else:
                                        # No placeholder found - create new error embed
                                        logger.warning(
                                            f"{log_prefix} No placeholder found for request {request_id}, creating new error embed"
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
                                    continue
                                
                                # Request succeeded - update placeholder or create new embed (use normalized key)
                                matching_placeholder = placeholder_embeds_map.get(request_id_key) if request_id_key else None
                                if matching_placeholder:
                                    # Update existing placeholder with results
                                    placeholder_embed_id = matching_placeholder.get("embed_id")
                                    logger.info(
                                        f"{log_prefix} Updating placeholder {placeholder_embed_id} with results for request {request_id}"
                                    )
                                    
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
                                        updated_embed_data["embed_reference"] = json.dumps({
                                            "type": "app_skill_use",
                                            "embed_id": placeholder_embed_id
                                        })
                                        updated_embed_data["request_id"] = request_id
                                        updated_embed_data["request_metadata"] = request_metadata
                                        updated_embed_data_list.append(updated_embed_data)
                                        logger.info(
                                            f"{log_prefix} Updated placeholder {placeholder_embed_id} with results for request {request_id}: "
                                            f"child_count={len(updated_embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to update placeholder for request {request_id}")
                                else:
                                    # No placeholder found - create new embed
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
                                        updated_embed_data_list.append(embed_data)
                                        logger.info(
                                            f"{log_prefix} Created embed {embed_data.get('parent_embed_id')} for request {request_id}: "
                                            f"child_count={len(embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to create embed for request {request_id}")
                            
                            # Stream all embed references as separate JSON code blocks
                            for embed_data in updated_embed_data_list:
                                embed_reference = embed_data.get("embed_reference")
                                if embed_reference:
                                    embed_code_block = f"```json\n{embed_reference}\n```\n\n"
                                    yield embed_code_block
                                    logger.debug(f"{log_prefix} Streamed embed reference for request {embed_data.get('request_id')}")
                        else:
                            # Single request: Update the existing placeholder embed
                            if placeholder_embed_data:
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
                                
                                # Add provider fallback for search skills
                                if "provider" not in single_request_metadata and skill_id == "search":
                                    if app_id == "maps":
                                        single_request_metadata["provider"] = "Google Maps"
                                    else:
                                        single_request_metadata["provider"] = "Brave Search"
                                
                                updated_embed_data = await embed_service.update_embed_with_results(
                                    embed_id=placeholder_embed_data.get('embed_id'),
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    results=results,
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
                                embed_data = await embed_service.create_embeds_from_skill_results(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    results=results,
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

                # Publish "finished" status with preview data
                # This triggers WebSocket event to update the frontend embed preview
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
                if updated_embed_data_list and cache_service:
                    try:
                        client = await cache_service.client
                        if client:
                            import json as json_lib
                            channel_key = f"websocket:user:{request_data.user_id_hash}"
                            
                            for embed_data in updated_embed_data_list:
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
                
            except json.JSONDecodeError as e:
                logger.error(f"{log_prefix} Invalid JSON in tool arguments for '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid JSON in function arguments.", "details": str(e)})
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
                except:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        from backend.core.api.app.utils.encryption import EncryptionService
                        encryption_service = EncryptionService()
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        await embed_service.update_embed_status_to_error(
                            embed_id=placeholder_embed_data.get('embed_id'),
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
                except:
                    pass  # Don't fail if status publish fails
            except ValueError as e:
                # Invalid tool name format
                logger.error(f"{log_prefix} Invalid tool name format '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid tool name format.", "details": str(e)})
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
                except:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        from backend.core.api.app.utils.encryption import EncryptionService
                        encryption_service = EncryptionService()
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        # Try to extract app_id and skill_id, fallback to unknown
                        try:
                            app_id, skill_id = tool_name.split('-', 1)
                        except:
                            app_id = "unknown"
                            skill_id = "unknown"
                        await embed_service.update_embed_status_to_error(
                            embed_id=placeholder_embed_data.get('embed_id'),
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
                except:
                    pass  # Don't fail if status publish fails
            except Exception as e:
                logger.error(f"{log_prefix} Error executing tool '{tool_name}': {e}", exc_info=True)
                tool_result_content_str = json.dumps({"error": "Skill execution failed.", "details": str(e)})
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
                except:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        from backend.core.api.app.utils.encryption import EncryptionService
                        encryption_service = EncryptionService()
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        await embed_service.update_embed_status_to_error(
                            embed_id=placeholder_embed_data.get('embed_id'),
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
                except:
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

        if iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            yield "\n[Max tool call iterations reached.]"
            break

    if usage:
        yield usage

    # Yield tool calls info as a special marker at the end of the stream
    # The stream consumer will extract this and format it as a code block
    if tool_calls_info:
        # Use a special dict marker that the stream consumer can detect
        yield {"__tool_calls_info__": tool_calls_info}
        logger.debug(f"{log_prefix} Yielding tool calls info for {len(tool_calls_info)} tool call(s)")

    logger.info(f"{log_prefix} Main processing stream finished.")


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
