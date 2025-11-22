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
            
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' has no explicit pricing, attempting to fetch provider-level pricing from '{provider_id}'")
            
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
    prompt_parts.append(base_instructions.get("base_capabilities_instruction", ""))
    prompt_parts.append(base_instructions.get("follow_up_instruction", ""))
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
    # Filter by preselected skills from preprocessing if available
    preselected_skills = None
    if hasattr(preprocessing_results, 'relevant_app_skills') and preprocessing_results.relevant_app_skills:
        preselected_skills = set(preprocessing_results.relevant_app_skills)
        logger.debug(f"{log_prefix} Using preselected skills: {preselected_skills}")
    
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
        
        async for chunk in aggregate_paragraphs(llm_stream):
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                continue
            if isinstance(chunk, (ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedOpenAIToolCall)):
                tool_calls_for_this_turn.append(chunk)
            elif isinstance(chunk, str):
                llm_turn_had_content = True
                if not tool_calls_for_this_turn:
                    yield chunk
                else:
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
                
                # Extract app_id and skill_id from tool name (format: "app_id-skill_id")
                # Use hyphen separator for LLM provider compatibility (Cerebras and others don't allow dots in function names)
                try:
                    app_id, skill_id = tool_name.split('-', 1)
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
                
                # Publish "processing" status when skill starts
                await _publish_skill_status(
                    cache_service=cache_service,
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    status="processing"
                )
                
                # Execute skill with support for multiple parallel requests
                results = await execute_skill_with_multiple_requests(
                    app_id=app_id,
                    skill_id=skill_id,
                    arguments=parsed_args,
                    timeout=30.0
                )
                
                # Extract ignore_fields_for_inference from skill results (if present)
                # This is a skill-defined list of fields to exclude from LLM inference
                # Skills can define this in their response to control what gets sent to LLM
                ignore_fields_for_inference: Optional[List[str]] = None
                
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
                
                # Extract preview_data from skill response (if present)
                # Skills can define their own preview_data structure for frontend rendering
                # This makes the architecture scalable - no skill-specific logic needed here
                # Each skill is responsible for populating preview_data with its own metadata
                # NOTE: Skills should NOT include actual results in preview_data - they will be converted to TOON
                preview_data: Dict[str, Any] = {}
                
                if results and len(results) > 0:
                    first_result = results[0]
                    if isinstance(first_result, dict):
                        # Check if skill returned preview_data directly in the response
                        if "preview_data" in first_result:
                            preview_data = first_result.get("preview_data", {}).copy()
                            # Remove any JSON results from preview_data - we'll add TOON instead
                            # Skills should only include metadata (query, provider, counts, etc.)
                            preview_data.pop("results", None)
                            preview_data.pop("previews", None)
                            logger.debug(
                                f"{log_prefix} Skill '{tool_name}' returned preview_data with keys: {list(preview_data.keys())}"
                            )
                        else:
                            # Fallback: create minimal preview_data (for backward compatibility)
                            # This handles skills that haven't been updated to use preview_data yet
                            preview_data = {
                                "result_count": len(results)
                            }
                            logger.debug(
                                f"{log_prefix} Skill '{tool_name}' did not return preview_data, using minimal fallback"
                            )
                    else:
                        # Non-dict result - create minimal preview_data
                        preview_data = {
                            "result_count": len(results)
                        }
                else:
                    # No results
                    preview_data = {
                        "result_count": 0
                    }
                
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
                    logger.info(f"{log_prefix} === TOON CONVERSION DEBUG (preview_data) ===")
                    logger.info(f"{log_prefix} Original JSON structure (first 15 lines, {len(json_before)} chars total):")
                    for i, line in enumerate(json_lines[:15], 1):
                        logger.info(f"{log_prefix}   {i:2d}: {line}")
                    if len(json_lines) > 15:
                        logger.info(f"{log_prefix}   ... ({len(json_lines) - 15} more lines)")
                    
                    if len(results) == 1:
                        # Single result - flatten and encode as TOON
                        # Note: Single result encoded directly (not wrapped in dict) for efficiency
                        flattened_result = _flatten_for_toon_tabular(results[0])
                        # DEBUG: Log flattened structure
                        flattened_json = json.dumps(flattened_result, indent=2)
                        flattened_lines = flattened_json.split('\n')
                        logger.info(f"{log_prefix} Flattened structure (first 15 lines, {len(flattened_json)} chars):")
                        for i, line in enumerate(flattened_lines[:15], 1):
                            logger.info(f"{log_prefix}   {i:2d}: {line}")
                        if len(flattened_lines) > 15:
                            logger.info(f"{log_prefix}   ... ({len(flattened_lines) - 15} more lines)")
                        
                        results_toon = encode(flattened_result)
                    else:
                        # Multiple results - flatten each result, then combine and encode as TOON
                        # Flattening enables TOON to use tabular format for uniform objects
                        # This matches the proven approach from toon_encoding_test.ipynb
                        flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                        # DEBUG: Log flattened structure
                        flattened_json = json.dumps({"results": flattened_results, "count": len(results)}, indent=2)
                        flattened_lines = flattened_json.split('\n')
                        logger.info(f"{log_prefix} Flattened structure (first 15 lines, {len(flattened_json)} chars):")
                        for i, line in enumerate(flattened_lines[:15], 1):
                            logger.info(f"{log_prefix}   {i:2d}: {line}")
                        if len(flattened_lines) > 15:
                            logger.info(f"{log_prefix}   ... ({len(flattened_lines) - 15} more lines)")
                        
                        results_toon = encode({"results": flattened_results, "count": len(results)})
                    
                    # DEBUG: Log TOON output (first 15 lines)
                    toon_lines = results_toon.split('\n')
                    logger.info(f"{log_prefix} TOON output (first 15 lines, {len(results_toon)} chars total):")
                    for i, line in enumerate(toon_lines[:15], 1):
                        logger.info(f"{log_prefix}   {i:2d}: {line}")
                    if len(toon_lines) > 15:
                        logger.info(f"{log_prefix}   ... ({len(toon_lines) - 15} more lines)")
                    
                    # DEBUG: Calculate and log savings
                    json_size = len(json_before)
                    toon_size = len(results_toon)
                    savings = json_size - toon_size
                    savings_percent = (savings / json_size * 100) if json_size > 0 else 0
                    logger.info(f"{log_prefix} Character savings: {json_size} → {toon_size} chars ({savings} saved, {savings_percent:.1f}% reduction)")
                    logger.info(f"{log_prefix} === END TOON CONVERSION DEBUG ===")
                    
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
                    for i, line in enumerate(json_lines[:15], 1):
                        logger.info(f"{log_prefix}   {i:2d}: {line}")
                    if len(json_lines) > 15:
                        logger.info(f"{log_prefix}   ... ({len(json_lines) - 15} more lines)")
                    
                    if len(results) == 1:
                        # Single result - flatten and encode full result as TOON for chat history
                        flattened_result = _flatten_for_toon_tabular(results[0])
                        # DEBUG: Log flattened structure
                        flattened_json = json.dumps(flattened_result, indent=2)
                        flattened_lines = flattened_json.split('\n')
                        logger.info(f"{log_prefix} Flattened structure (first 15 lines, {len(flattened_json)} chars):")
                        for i, line in enumerate(flattened_lines[:15], 1):
                            logger.info(f"{log_prefix}   {i:2d}: {line}")
                        if len(flattened_lines) > 15:
                            logger.info(f"{log_prefix}   ... ({len(flattened_lines) - 15} more lines)")
                        
                        tool_result_content_str = encode(flattened_result)
                    else:
                        # Multiple results - flatten each result, then combine and encode as TOON
                        # Flattening enables TOON to use tabular format for uniform objects
                        flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                        # DEBUG: Log flattened structure
                        flattened_json = json.dumps({"results": flattened_results, "count": len(results)}, indent=2)
                        flattened_lines = flattened_json.split('\n')
                        logger.info(f"{log_prefix} Flattened structure (first 15 lines, {len(flattened_json)} chars):")
                        for i, line in enumerate(flattened_lines[:15], 1):
                            logger.info(f"{log_prefix}   {i:2d}: {line}")
                        if len(flattened_lines) > 15:
                            logger.info(f"{log_prefix}   ... ({len(flattened_lines) - 15} more lines)")
                        
                        tool_result_content_str = encode({"results": flattened_results, "count": len(results)})
                    
                    # DEBUG: Log TOON output (first 15 lines)
                    toon_lines = tool_result_content_str.split('\n')
                    logger.info(f"{log_prefix} TOON output (first 15 lines, {len(tool_result_content_str)} chars total):")
                    for i, line in enumerate(toon_lines[:15], 1):
                        logger.info(f"{log_prefix}   {i:2d}: {line}")
                    if len(toon_lines) > 15:
                        logger.info(f"{log_prefix}   ... ({len(toon_lines) - 15} more lines)")
                    
                    # DEBUG: Calculate and log savings
                    json_size = len(json_before)
                    toon_size = len(tool_result_content_str)
                    savings = json_size - toon_size
                    savings_percent = (savings / json_size * 100) if json_size > 0 else 0
                    logger.info(f"{log_prefix} Character savings: {json_size} → {toon_size} chars ({savings} saved, {savings_percent:.1f}% reduction)")
                    logger.info(f"{log_prefix} === END TOON CONVERSION DEBUG ===")
                    
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
                
                # Publish "finished" status with preview data
                await _publish_skill_status(
                    cache_service=cache_service,
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    status="finished",
                    preview_data=preview_data if preview_data else None
                )
                
                # Create embeds from skill results (immediately after skill execution)
                # This enables immediate rendering of results while LLM continues processing
                embed_reference_data = None
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
                        
                        # Create embeds from skill results
                        embed_reference_data = await embed_service.create_embeds_from_skill_results(
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
                        
                        if embed_reference_data:
                            logger.info(
                                f"{log_prefix} Created embeds for skill '{tool_name}': "
                                f"parent_embed_id={embed_reference_data.get('parent_embed_id')}, "
                                f"child_count={len(embed_reference_data.get('child_embed_ids', []))}"
                            )
                        else:
                            logger.warning(f"{log_prefix} Failed to create embeds for skill '{tool_name}'")
                    except Exception as e:
                        logger.error(f"{log_prefix} Error creating embeds for skill '{tool_name}': {e}", exc_info=True)
                        # Continue without embeds - don't fail the entire skill execution
                
                # Stream embed reference immediately after skill execution (flexible placement)
                # This allows the embed to appear early in the response, before LLM interpretation
                if embed_reference_data and embed_reference_data.get("embed_reference"):
                    embed_reference_json = embed_reference_data.get("embed_reference")
                    # Yield embed reference as a JSON code block chunk
                    embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                    yield embed_code_block
                    logger.debug(
                        f"{log_prefix} Streamed embed reference chunk for '{tool_name}': "
                        f"embed_id={embed_reference_data.get('parent_embed_id')}"
                    )
                
                # Track tool call info for code block generation
                # NOTE: With new embeds architecture, embed references are streamed as chunks
                # We still track tool_call_info for TOON code block (for backward compatibility and follow-up questions)
                tool_call_info = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "input": parsed_args,  # Tool input arguments
                    "preview_data": preview_data,  # Metadata + results_toon (contains full TOON-encoded results)
                    "ignore_fields_for_inference": ignore_fields_for_inference,  # Fields excluded from LLM inference
                    "embed_reference": embed_reference_data.get("embed_reference") if embed_reference_data else None  # Embed reference JSON (already streamed)
                }
                tool_calls_info.append(tool_call_info)
                logger.debug(
                    f"{log_prefix} Tracked tool call info for '{tool_name}': "
                    f"app_id={app_id}, skill_id={skill_id}, results_toon_length={len(preview_data.get('results_toon', ''))}"
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
