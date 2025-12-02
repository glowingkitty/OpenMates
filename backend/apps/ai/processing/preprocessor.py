# backend/apps/ai/processing/preprocessor.py
# Handles the preprocessing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional
import unicodedata # For Unicode normalization
import re # For removing non-printable characters
import datetime # For current date/time in system prompt

from backend.core.api.app.services.cache import CacheService # Corrected import path
 
# Import the new LLM utility
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager
# Import Mate utilities
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
# Import AskSkillDefaultConfig and AskSkillRequest
from backend.apps.ai.skills.ask_skill import AskSkillRequest, AskSkillDefaultConfig
from pydantic import BaseModel, Field # For PreprocessingResult model
from backend.shared.python_schemas.app_metadata_schemas import AppYAML  # For type hinting

logger = logging.getLogger(__name__)

class PreprocessingResult(BaseModel):
    """
    Defines the Pydantic model for the output structure of the preprocessing step.
    """
    can_proceed: bool = False # Renamed from is_safe_to_proceed
    rejection_reason: Optional[str] = None # This will serve as error_type

    harmful_or_illegal_score: Optional[float] = Field(None, description="Harmfulness score (1-10).")
    category: Optional[str] = Field(None, description="Identified category/topic of the request.")
    llm_response_temp: Optional[float] = Field(None, description="Suggested temperature for the main LLM response.")
    complexity: Optional[str] = Field(None, description="Assessed complexity of the request (e.g., simple, complex).")
    misuse_risk_score: Optional[float] = Field(None, description="Risk score for misuse/scam (1-10).")
    load_app_settings_and_memories: Optional[List[str]] = Field(None, description="List of app settings and memories keys to load (e.g., ['app_id-item_key']).")
    relevant_embedded_previews: Optional[List[str]] = Field(None, description="List of embedded preview types to generate (e.g., ['code', 'math', 'music']).")
    title: Optional[str] = Field(None, description="Generated title for the chat, if applicable.")
    icon_names: Optional[List[str]] = Field(None, description="List of 1-3 relevant Lucide icon names for the request topic.")
    chat_summary: Optional[str] = Field(None, description="2-3 sentence summary of the full conversation so far.")
    chat_tags: Optional[List[str]] = Field(None, description="Up to 10 tags for categorization and search.")
    relevant_app_skills: Optional[List[str]] = Field(None, description="List of relevant app skill identifiers (format: 'app_id-skill_id') for tool preselection.")

    selected_mate_id: Optional[str] = None
    selected_main_llm_model_id: Optional[str] = None
    selected_main_llm_model_name: Optional[str] = None # Added

    raw_llm_response: Optional[Dict[str, Any]] = Field(None, description="Raw arguments from the LLM tool call.")
    error_message: Optional[str] = None


def _sanitize_text_content(text: str) -> str:
    """
    Sanitizes text content by:
    1. Normalizing Unicode to NFC form.
    2. Removing non-printable characters (excluding common whitespace like space, tab, newline).
    """
    if not isinstance(text, str):
        return text # Return as is if not a string

    # Normalize Unicode
    normalized_text = unicodedata.normalize('NFC', text)

    # Remove non-printable characters, allowing common whitespace (space, tab, newline, carriage return)
    # \x00-\x08: Null to Backspace
    # \x0B-\x0C: Vertical Tab, Form Feed
    # \x0E-\x1F: Shift Out to Unit Separator
    # \x7F: Delete
    # We keep \t (tab), \n (newline), \r (carriage return)
    sanitized_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', normalized_text)
    
    return sanitized_text


async def handle_preprocessing(
    request_data: AskSkillRequest,
    base_instructions: Dict[str, Any],
    skill_config: AskSkillDefaultConfig,
    cache_service: CacheService,
    secrets_manager: SecretsManager, # Added SecretsManager
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None,
    discovered_apps_metadata: Optional[Dict[str, AppYAML]] = None  # AppYAML metadata for tool preselection
) -> PreprocessingResult:
    """
    Handles the preprocessing of an AI skill request.

    Args:
        request_data: The AskSkillRequest Pydantic model.
        base_instructions: Loaded content from base_instructions.yml.
        skill_config: The parsed default_config for the specific skill (e.g., AskSkill).
        user_app_settings_and_memories_metadata: Metadata about available user app settings/memories (app_id -> list of item_keys).
        cache_service: Instance of CacheService for fetching user credits.

    Returns:
        PreprocessingResult: A Pydantic model containing the results of the preprocessing.
    """
    log_prefix = f"Preprocessor (ChatID: {request_data.chat_id}, MsgID: {request_data.message_id}):"
    logger.info(f"{log_prefix} Starting preprocessing.")

    # --- Credit Check ---
    MINIMUM_REQUEST_COST = 1 # TODO: Make this configurable, perhaps in skill_config.preprocessing_thresholds
    logger.info(f"{log_prefix} Performing credit check for user_id: {request_data.user_id}. Minimum cost: {MINIMUM_REQUEST_COST}") # Log actual user_id
    
    if not request_data.user_id: # Check for actual user_id
        logger.error(f"{log_prefix} user_id is missing in request_data. Cannot perform credit check.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_missing_user_id",
            error_message="User identification is missing. Cannot proceed."
        )

    cached_user = await cache_service.get_user_by_id(request_data.user_id) # Use user_id

    if not cached_user:
        logger.error(f"{log_prefix} Could not retrieve cached user data for user_id: {request_data.user_id}.") # Log actual user_id
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_user_data_not_found",
            error_message="Could not retrieve user information. Please try again later."
        )

    user_credits = cached_user.get("credits", 0)
    if not isinstance(user_credits, int): # Ensure credits is an int
        logger.error(f"{log_prefix} User credits for {request_data.user_id} is not an integer: {user_credits}. Treating as 0.") # Log actual user_id
        user_credits = 0
    
    logger.info(f"{log_prefix} User {request_data.user_id} has {user_credits} credits.") # Log actual user_id

    if user_credits < MINIMUM_REQUEST_COST:
        logger.warning(f"{log_prefix} User {request_data.user_id} has insufficient credits ({user_credits}) for minimum cost ({MINIMUM_REQUEST_COST}).") # Log actual user_id
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="insufficient_credits",
            error_message=f"You have {user_credits} credits, but this action requires at least {MINIMUM_REQUEST_COST}. Please buy more credits and then try again.",
            harmful_or_illegal_score=None,
            category=None,
            llm_response_temp=None,
            complexity=None,
            misuse_risk_score=None,
            load_app_settings_and_memories=None,
            selected_mate_id=None,
            selected_main_llm_model_id=None,
            selected_main_llm_model_name=None,
            raw_llm_response=None
        )
    logger.info(f"{log_prefix} Credit check passed for user {request_data.user_id}.") # Log actual user_id
    # --- End Credit Check ---
 
    # Sanitize user messages in the history
    sanitized_message_history = []
    for msg in request_data.message_history: # msg is AIHistoryMessage
        msg_dict = msg.model_dump() # Convert Pydantic model to dict
        if msg.role == "user":
            original_content = msg.content # Accessing attribute from original msg Pydantic object
            if isinstance(original_content, str):
                sanitized_content = _sanitize_text_content(original_content)
                # Update the 'content' in the dictionary representation
                msg_dict["content"] = sanitized_content
                if original_content != sanitized_content: # Log only if changed
                    logger.debug(f"{log_prefix} Sanitized user message content. Original length: {len(original_content)}, Sanitized length: {len(sanitized_content)}")
                sanitized_message_history.append(msg_dict)
            else:
                # If content is not str (e.g. already a dict from Tiptap), append the dict representation of original msg
                # The content in msg_dict is already correct from model_dump()
                sanitized_message_history.append(msg_dict)
        else:
            # For non-user messages, append the dict representation
            sanitized_message_history.append(msg_dict)
    
    if "preprocess_request_tool" not in base_instructions:
        logger.error(f"{log_prefix} Missing 'preprocess_request_tool' in base_instructions.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_missing_instructions",
            error_message="Critical preprocessing instructions are missing."
        )

    # Deepcopy the tool definition to allow modification
    import copy
    tool_definition_for_llm = copy.deepcopy(base_instructions["preprocess_request_tool"])

    # Conditionally remove title and icon_names generation if chat already has a title
    # Icon/category are generated only once with the title (first message only)
    # CRITICAL: Use chat_has_title flag from client, NOT message_history length
    # (message_history can be empty on first request when cache is used)
    is_first_message = not request_data.chat_has_title
    
    if not is_first_message:
        logger.info(f"{log_prefix} Chat already has a title (follow-up message). Omitting title, icon_names, and category generation from LLM tool call.")
        # Remove title field
        if 'title' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('properties', {}):
            del tool_definition_for_llm['function']['parameters']['properties']['title']
        if 'title' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('required', []):
            tool_definition_for_llm['function']['parameters']['required'].remove('title')
        # Remove icon_names field (icon and category are set once with the title)
        if 'icon_names' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('properties', {}):
            del tool_definition_for_llm['function']['parameters']['properties']['icon_names']
        if 'icon_names' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('required', []):
            tool_definition_for_llm['function']['parameters']['required'].remove('icon_names')
        # Remove category field
        if 'category' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('properties', {}):
            del tool_definition_for_llm['function']['parameters']['properties']['category']
        if 'category' in tool_definition_for_llm.get('function', {}).get('parameters', {}).get('required', []):
            tool_definition_for_llm['function']['parameters']['required'].remove('category')
    else:
        logger.info(f"{log_prefix} This is the first message (chat has no title yet). Including title, icon_names, and category generation in LLM tool call.")

    logger.info(f"{log_prefix} Loaded and potentially modified instruction tool (preprocess_request_tool).")
    
    # Load mates_configs from cache (preloaded by main API server at startup)
    # The main API server preloads these into the shared Dragonfly cache during startup.
    # Task workers read from cache to avoid disk I/O and ensure consistency across containers.
    # Fallback to disk loading if cache is empty (e.g., cache expired or server restarted).
    all_mates: List[MateConfig] = []
    try:
        if cache_service:
            cached_mates = await cache_service.get_mates_configs()
            if cached_mates:
                all_mates = cached_mates
                logger.debug(f"{log_prefix} Successfully loaded {len(all_mates)} mates_configs from cache (preloaded by main API server).")
            else:
                # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                logger.warning(f"{log_prefix} mates_configs not found in cache. Loading from disk and re-caching...")
                all_mates = load_mates_config()
                if all_mates:
                    try:
                        await cache_service.set_mates_configs(all_mates)
                        logger.debug(f"{log_prefix} Re-cached {len(all_mates)} mates_configs after disk load.")
                    except Exception as e:
                        logger.warning(f"{log_prefix} Failed to re-cache mates_configs: {e}")
        else:
            # No cache service available, load from disk
            logger.warning(f"{log_prefix} CacheService not available. Loading mates_configs from disk...")
            all_mates = load_mates_config()
    except Exception as e:
        logger.error(f"{log_prefix} Error loading mates_configs: {e}", exc_info=True)
        # Fallback to disk loading
        all_mates = load_mates_config()
    
    if not all_mates:
        logger.critical(f"{log_prefix} CRITICAL: No mates were loaded from cache or disk. Cannot proceed with mate selection or determine available categories.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_missing_mates_config",
            error_message="Mate configuration is missing or empty, cannot determine categories for LLM."
        )
    
    available_categories_list = sorted(list(set(mate.category for mate in all_mates if mate.category)))
    if not available_categories_list:
        logger.critical(f"{log_prefix} CRITICAL: No categories could be derived from the loaded mates. Mates.yml might be misconfigured or all mates lack categories.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_no_mate_categories",
            error_message="No categories found in mate configurations, cannot guide LLM for mate selection."
        )
    
    # Ensure 'general_knowledge' is always available as a fallback category
    # This is critical for category validation fallback logic
    if "general_knowledge" not in available_categories_list:
        logger.warning(
            f"{log_prefix} 'general_knowledge' category not found in available categories list. "
            f"Adding it as a fallback option. Available categories: {available_categories_list}"
        )
        available_categories_list.append("general_knowledge")
        available_categories_list = sorted(available_categories_list)  # Re-sort after adding
 
    # Extract and log available app skills for tool preselection
    # Note: Exclude ai.ask from available skills - it's the main processing entry point, not a tool
    # Note: No stage filtering needed here - discovered_apps_metadata already contains only apps
    # with valid stages (filtered during server startup). All skills in these apps are valid.
    available_skills_list: List[str] = []

    if discovered_apps_metadata:
        for app_id, app_metadata in discovered_apps_metadata.items():
            if app_metadata and app_metadata.skills:
                for skill in app_metadata.skills:
                    # Exclude ai.ask - it's the main processing entry point, not a tool
                    if app_id == "ai" and skill.id == "ask":
                        logger.debug(f"{log_prefix} Skipping skill '{skill.id}' from app '{app_id}' - this is the main processing entry point, not a tool")
                        continue

                    # No stage filtering needed - discovered_apps_metadata already contains only apps
                    # with valid stages (filtered during server startup via should_include_app_by_stage)
                    # Use hyphen format for skill identifiers (consistent with tool names)
                    skill_identifier = f"{app_id}-{skill.id}"
                    available_skills_list.append(skill_identifier)
    
    logger.info(f"{log_prefix} Preparing for LLM call. Using {len(available_categories_list)} categories from mates.yml: {available_categories_list}")
    logger.info(f"  - User Message History Length: {len(request_data.message_history)}")
    logger.info(f"  - Tool to call by LLM: {tool_definition_for_llm.get('function', {}).get('name')}")
    logger.info(f"  - Available app skills for tool preselection ({len(available_skills_list)} total): {', '.join(available_skills_list) if available_skills_list else 'None'}")
    logger.info(f"  - Dynamic context for LLM prompt:")
    logger.info(f"    - CATEGORIES_LIST: {available_categories_list}")
    logger.info(f"    - AVAILABLE_APP_SKILLS: {available_skills_list if available_skills_list else 'None'}")
    logger.info(f"    - AVAILABLE_APP_SETTINGS_AND_MEMORIES (from direct param): {user_app_settings_and_memories_metadata}")

    preprocessing_model = skill_config.default_llms.preprocessing_model # Changed variable name and attribute accessed
    
    # Resolve fallback servers from provider config instead of hardcoded list in app.yml
    # This allows fallback servers to be configured in provider YAML files (e.g., mistral.yml)
    from backend.apps.ai.utils.llm_utils import resolve_fallback_servers_from_provider_config
    preprocessing_fallbacks = resolve_fallback_servers_from_provider_config(preprocessing_model)
    
    logger.info(f"{log_prefix} Using preprocessing_model: {preprocessing_model} from skill_config.") # Updated log message
    if preprocessing_fallbacks:
        logger.info(f"{log_prefix} Resolved {len(preprocessing_fallbacks)} fallback server(s) for preprocessing: {preprocessing_fallbacks}")

    # Build dynamic context with categories and available app skills (with descriptions)
    # Include current date/time so preprocessing LLM knows temporal context
    now = datetime.datetime.now(datetime.timezone.utc)
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    dynamic_context = {
        "CATEGORIES_LIST": available_categories_list,
        "AVAILABLE_APP_SKILLS": available_skills_list if available_skills_list else [],
        "CURRENT_DATE_TIME": date_time_str
    }

    llm_call_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
        task_id=f"{request_data.chat_id}_{request_data.message_id}",
        model_id=preprocessing_model,
        fallback_models=preprocessing_fallbacks,  # Pass fallback providers
        message_history=sanitized_message_history,
        tool_definition=tool_definition_for_llm, # Use the (potentially modified) tool definition
        secrets_manager=secrets_manager, # Pass SecretsManager
        user_app_settings_and_memories_metadata=user_app_settings_and_memories_metadata,
        dynamic_context=dynamic_context
    )

    if llm_call_result.error_message or not llm_call_result.arguments:
        default_err_msg = "Preprocessing LLM failed to analyze the request or returned no arguments."
        final_err_msg = llm_call_result.error_message or default_err_msg
        
        # Log the specific error if available, otherwise the generic one
        logger.error(f"{log_prefix} Preprocessing LLM call failed. Model: {preprocessing_model}. Error: {final_err_msg}")
        
        raw_response_data = {"error": final_err_msg}
        if llm_call_result.raw_provider_response_summary:
            raw_response_data["provider_response_summary"] = llm_call_result.raw_provider_response_summary

        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_llm_preprocessing_failed",
            error_message=final_err_msg, # Use the more specific error message
            raw_llm_response=raw_response_data
        )
    
    llm_analysis_args = llm_call_result.arguments # Arguments are now guaranteed to be non-None
    
    # Sanitize llm_analysis_args for logging: show only metadata for chat_summary and chat_tags
    sanitized_args = llm_analysis_args.copy()
    if "chat_summary" in sanitized_args and isinstance(sanitized_args["chat_summary"], str):
        sanitized_args["chat_summary"] = {"length": len(sanitized_args["chat_summary"]), "content": "[REDACTED_CONTENT]"}
    if "chat_tags" in sanitized_args and isinstance(sanitized_args["chat_tags"], list):
        sanitized_args["chat_tags"] = {"count": len(sanitized_args["chat_tags"]), "content": "[REDACTED_CONTENT]"}
    
    logger.info(f"{log_prefix} Received LLM analysis args: {sanitized_args}")
    if llm_call_result.raw_provider_response_summary:
        logger.debug(f"{log_prefix} Raw provider response summary: {llm_call_result.raw_provider_response_summary}")
    
    HARM_THRESHOLD = skill_config.preprocessing_thresholds.harmful_content_score # Corrected attribute name
    MISUSE_THRESHOLD = skill_config.preprocessing_thresholds.misuse_risk_score
    logger.info(f"{log_prefix} Using HARM_THRESHOLD={HARM_THRESHOLD}, MISUSE_THRESHOLD={MISUSE_THRESHOLD} from skill_config.")

    harmful_or_illegal_val = llm_analysis_args.get("harmful_or_illegal")
    misuse_risk_val = llm_analysis_args.get("misuse_risk")

    # Convert to float to handle both integer and float values, and validate ranges
    try:
        harmful_or_illegal_val = float(harmful_or_illegal_val)
        # Clamp to valid range 0.0-10.0
        if harmful_or_illegal_val < 0.0:
            logger.warning(f"{log_prefix} 'harmful_or_illegal_score' is below minimum (0.0): {harmful_or_illegal_val}. Clamping to 0.0.")
            harmful_or_illegal_val = 0.0
        elif harmful_or_illegal_val > 10.0:
            logger.warning(f"{log_prefix} 'harmful_or_illegal_score' is above maximum (10.0): {harmful_or_illegal_val}. Clamping to 10.0.")
            harmful_or_illegal_val = 10.0
    except (ValueError, TypeError):
        logger.warning(f"{log_prefix} 'harmful_or_illegal_score' is not a valid number: {harmful_or_illegal_val}. Defaulting to 0.")
        harmful_or_illegal_val = 0.0
    
    try:
        misuse_risk_val = float(misuse_risk_val)
        # Clamp to valid range 0-10
        if misuse_risk_val < 0:
            logger.warning(f"{log_prefix} 'misuse_risk_score' is below minimum (0): {misuse_risk_val}. Clamping to 0.")
            misuse_risk_val = 0
        elif misuse_risk_val > 10:
            logger.warning(f"{log_prefix} 'misuse_risk_score' is above maximum (10): {misuse_risk_val}. Clamping to 10.")
            misuse_risk_val = 10
    except (ValueError, TypeError):
        logger.warning(f"{log_prefix} 'misuse_risk_score' is not a valid number: {misuse_risk_val}. Defaulting to 0.")
        misuse_risk_val = 0

    # Values are already converted to float above
    if harmful_or_illegal_val >= float(HARM_THRESHOLD):
        logger.warning(f"{log_prefix} Request flagged for harmful content. Score: {harmful_or_illegal_val}, Threshold: {HARM_THRESHOLD}")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="harmful_or_illegal_detected",
            error_message=f"Request flagged as potentially harmful or illegal (score: {harmful_or_illegal_val}).",
            raw_llm_response=llm_analysis_args,
            harmful_or_illegal_score=harmful_or_illegal_val,
            category=llm_analysis_args.get("category"),
            llm_response_temp=llm_analysis_args.get("llm_response_temp"),
            complexity=llm_analysis_args.get("complexity"),
            misuse_risk_score=misuse_risk_val,
            load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories"),
            relevant_embedded_previews=llm_analysis_args.get("relevant_embedded_previews"),
            title=llm_analysis_args.get("title"), # Also pass title here for consistency in rejection cases
            icon_names=llm_analysis_args.get("icon_names", []) # Also pass icon names for consistency
        )

    elif misuse_risk_val >= float(MISUSE_THRESHOLD):
        logger.warning(f"{log_prefix} Request flagged for high misuse risk. Score: {misuse_risk_val}, Threshold: {MISUSE_THRESHOLD}")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="misuse_detected",
            error_message=f"Request flagged for high misuse risk (score: {misuse_risk_val}).",
            raw_llm_response=llm_analysis_args,
            harmful_or_illegal_score=harmful_or_illegal_val,
            category=llm_analysis_args.get("category"),
            llm_response_temp=llm_analysis_args.get("llm_response_temp"),
            complexity=llm_analysis_args.get("complexity"),
            misuse_risk_score=misuse_risk_val,
            load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories"),
            relevant_embedded_previews=llm_analysis_args.get("relevant_embedded_previews"),
            title=llm_analysis_args.get("title"), # Also pass title here for consistency in rejection cases
            icon_names=llm_analysis_args.get("icon_names", []) # Also pass icon names for consistency
        )

    else:
        logger.info(f"{log_prefix} Request passed harmful content and misuse risk checks. Scores: Harmful={harmful_or_illegal_val}, Misuse={misuse_risk_val}.")
    
    # --- Validate complexity field (enum: ["simple", "complex"]) ---
    # CRITICAL: Invalid complexity values could break model selection logic
    complexity_val = llm_analysis_args.get("complexity", "simple")
    valid_complexity_values = ["simple", "complex"]
    if complexity_val not in valid_complexity_values:
        logger.warning(
            f"{log_prefix} LLM returned invalid complexity value '{complexity_val}'. "
            f"Valid values are: {valid_complexity_values}. Defaulting to 'complex' (safer default)."
        )
        complexity_val = "complex"  # Use 'complex' as safer default (better model, more capable)
        # Update llm_analysis_args for consistency
        llm_analysis_args["complexity"] = complexity_val
    
    selected_llm_for_main_id = skill_config.default_llms.main_processing_simple
    selected_llm_for_main_name = skill_config.default_llms.main_processing_simple_name
    if complexity_val == "complex":
        selected_llm_for_main_id = skill_config.default_llms.main_processing_complex
        selected_llm_for_main_name = skill_config.default_llms.main_processing_complex_name
    
    logger.info(f"{log_prefix} Selected LLM for main processing: {selected_llm_for_main_id} (Name: {selected_llm_for_main_name}) based on complexity '{complexity_val}'.")
    
    # --- Validate llm_response_temp field (range: 0.0-2.0) ---
    llm_response_temp_val = llm_analysis_args.get("llm_response_temp", 0.4)
    try:
        llm_response_temp_val = float(llm_response_temp_val)
        # Clamp to valid range 0.0-2.0
        if llm_response_temp_val < 0.0:
            logger.warning(f"{log_prefix} 'llm_response_temp' is below minimum (0.0): {llm_response_temp_val}. Clamping to 0.0.")
            llm_response_temp_val = 0.0
            llm_analysis_args["llm_response_temp"] = llm_response_temp_val
        elif llm_response_temp_val > 2.0:
            logger.warning(f"{log_prefix} 'llm_response_temp' is above maximum (2.0): {llm_response_temp_val}. Clamping to 2.0.")
            llm_response_temp_val = 2.0
            llm_analysis_args["llm_response_temp"] = llm_response_temp_val
    except (ValueError, TypeError):
        logger.warning(f"{log_prefix} 'llm_response_temp' is not a valid number: {llm_response_temp_val}. Defaulting to 0.4.")
        llm_response_temp_val = 0.4
        llm_analysis_args["llm_response_temp"] = llm_response_temp_val
    
    # --- Validate and potentially retry category selection ---
    # The LLM should select a category from available_categories_list, but sometimes it makes up a non-existent category.
    # We validate the category and retry preprocessing once if invalid, then fallback to 'general_knowledge' if retry also fails.
    llm_category = llm_analysis_args.get("category")
    validated_category = llm_category
    category_was_retried = False
    
    # Validate category against available categories list
    if llm_category and llm_category not in available_categories_list:
        logger.warning(
            f"{log_prefix} LLM returned invalid category '{llm_category}' which is not in available categories list: {available_categories_list}. "
            f"Attempting retry..."
        )
        
        # Retry preprocessing once with a more explicit instruction about category validation
        try:
            # Create a modified tool definition that emphasizes category validation
            retry_tool_definition = copy.deepcopy(tool_definition_for_llm)
            # Add a note in the category description emphasizing it MUST be from the list
            category_desc = retry_tool_definition.get('function', {}).get('parameters', {}).get('properties', {}).get('category', {}).get('description', '')
            retry_tool_definition['function']['parameters']['properties']['category']['description'] = (
                f"{category_desc} **CRITICAL: You MUST select EXACTLY one category from this list: {available_categories_list}. "
                f"DO NOT invent new categories. If unsure, use 'general_knowledge'."
            )
            
            logger.info(f"{log_prefix} Retrying preprocessing LLM call with explicit category validation instructions...")
            retry_llm_call_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"{request_data.chat_id}_{request_data.message_id}_retry",
                model_id=preprocessing_model,
                fallback_models=preprocessing_fallbacks,
                message_history=sanitized_message_history,
                tool_definition=retry_tool_definition,
                secrets_manager=secrets_manager,
                user_app_settings_and_memories_metadata=user_app_settings_and_memories_metadata,
                dynamic_context={"CATEGORIES_LIST": available_categories_list}
            )
            
            if retry_llm_call_result.error_message or not retry_llm_call_result.arguments:
                logger.warning(
                    f"{log_prefix} Retry preprocessing LLM call failed or returned no arguments. "
                    f"Error: {retry_llm_call_result.error_message or 'No arguments returned'}. "
                    f"Using 'general_knowledge' as fallback category."
                )
                validated_category = "general_knowledge"
            else:
                retry_category = retry_llm_call_result.arguments.get("category")
                if retry_category and retry_category in available_categories_list:
                    logger.info(f"{log_prefix} Retry successful! LLM returned valid category '{retry_category}'.")
                    validated_category = retry_category
                    category_was_retried = True
                    # Update llm_analysis_args with the validated category for consistency
                    llm_analysis_args["category"] = validated_category
                else:
                    # Retry also returned an invalid category (either None, empty, or not in available_categories_list)
                    logger.warning(
                        f"{log_prefix} Retry preprocessing also returned invalid category '{retry_category}' "
                        f"(original invalid category was '{llm_category}'). "
                        f"Category '{retry_category if retry_category else 'None/empty'}' is not in available categories list: {available_categories_list}. "
                        f"Using 'general_knowledge' as fallback category."
                    )
                    validated_category = "general_knowledge"
                    # Update llm_analysis_args with fallback category
                    llm_analysis_args["category"] = validated_category
        except Exception as retry_exc:
            logger.error(
                f"{log_prefix} Exception during category validation retry: {retry_exc}. "
                f"Using 'general_knowledge' as fallback category.",
                exc_info=True
            )
            validated_category = "general_knowledge"
            # Update llm_analysis_args with fallback category
            llm_analysis_args["category"] = validated_category
    elif not llm_category:
        # Category is None or empty - use fallback
        logger.warning(
            f"{log_prefix} LLM did not provide a category in its response. "
            f"Using 'general_knowledge' as fallback category."
        )
        validated_category = "general_knowledge"
        # Update llm_analysis_args with fallback category
        llm_analysis_args["category"] = validated_category
    else:
        # Category is valid
        logger.debug(f"{log_prefix} Category '{validated_category}' is valid (exists in available categories list).")
    
    # --- Mate selection based on validated category ---
    selected_mate_id: Optional[str] = None
    
    if validated_category:
        if not all_mates:
            logger.error(f"{log_prefix} Mates list is unexpectedly empty during mate selection for category '{validated_category}'.")
        else:
            matched_mate = next((mate for mate in all_mates if mate.category == validated_category), None)
            if matched_mate:
                selected_mate_id = matched_mate.id
                logger.info(f"{log_prefix} Selected Mate ID '{selected_mate_id}' based on validated category '{validated_category}'.")
            else:
                logger.warning(
                    f"{log_prefix} No mate found for validated category '{validated_category}'. "
                    f"'selected_mate_id' will be None. Main processing must handle this."
                )
    
    # --- Validate load_app_settings_and_memories field ---
    # Filter out any keys that don't exist in the available metadata
    load_app_settings_and_memories_val = llm_analysis_args.get("load_app_settings_and_memories", [])
    if not isinstance(load_app_settings_and_memories_val, list):
        logger.warning(f"{log_prefix} 'load_app_settings_and_memories' is not a list: {load_app_settings_and_memories_val}. Defaulting to empty list.")
        load_app_settings_and_memories_val = []
        llm_analysis_args["load_app_settings_and_memories"] = load_app_settings_and_memories_val
    else:
        # Validate each key against available metadata
        if user_app_settings_and_memories_metadata:
            # Build a set of all available keys (format: "app_id-item_key" using hyphen for consistency)
            available_keys = set()
            for app_id, item_keys in user_app_settings_and_memories_metadata.items():
                for item_key in item_keys:
                    available_keys.add(f"{app_id}-{item_key}")

            # Filter out invalid keys
            validated_keys = [key for key in load_app_settings_and_memories_val if key in available_keys]
            invalid_keys = [key for key in load_app_settings_and_memories_val if key not in available_keys]

            if invalid_keys:
                logger.warning(
                    f"{log_prefix} LLM requested {len(invalid_keys)} invalid app_settings_and_memories key(s) that don't exist: {invalid_keys}. "
                    f"Filtered out. Valid keys: {validated_keys}."
                )
                load_app_settings_and_memories_val = validated_keys
                llm_analysis_args["load_app_settings_and_memories"] = load_app_settings_and_memories_val
        # If user_app_settings_and_memories_metadata is None/empty, we can't validate, so keep as-is
        # (The system will handle missing keys gracefully)

    # --- Validate relevant_embedded_previews field ---
    # This list specifies which types of embedded previews to prepare for in the main LLM response
    relevant_embedded_previews_val = llm_analysis_args.get("relevant_embedded_previews", [])
    if not isinstance(relevant_embedded_previews_val, list):
        logger.warning(f"{log_prefix} 'relevant_embedded_previews' is not a list: {relevant_embedded_previews_val}. Defaulting to empty list.")
        relevant_embedded_previews_val = []
        llm_analysis_args["relevant_embedded_previews"] = relevant_embedded_previews_val
    else:
        # Validate preview types are strings and log them
        if relevant_embedded_previews_val:
            logger.info(f"{log_prefix} LLM identified relevant embedded preview types for this request: {relevant_embedded_previews_val}. "
                       f"The main LLM will be instructed to generate appropriate YAML structures for: {', '.join(relevant_embedded_previews_val)}.")

    # Note: icon_names validation is handled client-side, so we pass through the LLM value as-is
    
    # --- Validate chat_summary field (required field) ---
    # CRITICAL: chat_summary is required for post-processing suggestions generation
    # If missing, we need to understand why and log detailed information for debugging
    chat_summary_val = llm_analysis_args.get("chat_summary")
    if not chat_summary_val:
        # chat_summary is missing or empty - this is a critical issue that needs investigation
        logger.error(
            f"{log_prefix} CRITICAL: 'chat_summary' is missing or empty from LLM response! "
            f"This field is REQUIRED in the tool definition. "
            f"LLM response keys: {list(llm_analysis_args.keys())}. "
            f"Raw LLM response summary: {llm_call_result.raw_provider_response_summary}. "
            f"This will cause post-processing to fail. "
            f"Message history length: {len(sanitized_message_history)}. "
            f"Preprocessing model: {preprocessing_model}."
        )
        # Log the full sanitized args to see what the LLM actually returned
        logger.error(
            f"{log_prefix} Full LLM analysis args (sanitized): {sanitized_args}. "
            f"This will help identify if the LLM is not following the tool definition correctly."
        )
        # Set to None explicitly so we can track this issue
        chat_summary_val = None
    elif not isinstance(chat_summary_val, str):
        logger.error(
            f"{log_prefix} CRITICAL: 'chat_summary' is not a string: {type(chat_summary_val)} = {chat_summary_val}. "
            f"Expected a string. This will cause post-processing to fail."
        )
        chat_summary_val = None
    elif not chat_summary_val.strip():
        logger.error(
            f"{log_prefix} CRITICAL: 'chat_summary' is an empty or whitespace-only string. "
            f"This will cause post-processing to fail."
        )
        chat_summary_val = None
    else:
        # chat_summary is valid - log its length for debugging
        logger.debug(f"{log_prefix} 'chat_summary' is valid (length: {len(chat_summary_val)} characters)")
    
    # --- Validate chat_tags field (maxItems: 10) ---
    chat_tags_val = llm_analysis_args.get("chat_tags", [])
    if not isinstance(chat_tags_val, list):
        logger.warning(f"{log_prefix} 'chat_tags' is not a list: {chat_tags_val}. Defaulting to empty list.")
        chat_tags_val = []
        llm_analysis_args["chat_tags"] = chat_tags_val
    elif len(chat_tags_val) > 10:
        logger.warning(
            f"{log_prefix} 'chat_tags' has {len(chat_tags_val)} items (maxItems: 10). "
            f"Truncating to first 10: {chat_tags_val[:10]}."
        )
        chat_tags_val = chat_tags_val[:10]
        llm_analysis_args["chat_tags"] = chat_tags_val
    
    # Extract relevant_app_skills from LLM response if present (for tool preselection)
    # For now, if not provided by LLM, we'll set to None (meaning all skills available)
    relevant_app_skills_val = llm_analysis_args.get("relevant_app_skills")
    if relevant_app_skills_val and isinstance(relevant_app_skills_val, list):
        # Validate that all skill identifiers exist in available_skills_list
        validated_relevant_skills = [skill for skill in relevant_app_skills_val if skill in available_skills_list]
        invalid_skills = [skill for skill in relevant_app_skills_val if skill not in available_skills_list]
        if invalid_skills:
            logger.warning(
                f"{log_prefix} LLM returned {len(invalid_skills)} invalid skill identifier(s) that don't exist: {invalid_skills}. "
                f"Filtered out. Available skills: {available_skills_list if available_skills_list else 'None'}. "
                f"This may indicate that the app for these skills is not discovered or the skill identifier format is incorrect."
            )
        if validated_relevant_skills:
            logger.info(f"{log_prefix} Preprocessing selected {len(validated_relevant_skills)} relevant skill(s) for main processing: {', '.join(validated_relevant_skills)}")
        else:
            # Empty list means no skills are relevant - this is valid per architecture
            # We should NOT include all skills, only the preselected ones (which is empty)
            logger.info(f"{log_prefix} Preprocessing selected no relevant skills (or all were invalid). No skills will be provided to main processing (architecture: only preselected skills are forwarded).")
            validated_relevant_skills = []  # Keep as empty list, not None - this ensures only preselected skills are forwarded
    else:
        # No preselection provided by LLM - treat as empty list (no skills preselected)
        # Architecture requires only preselected skills to be forwarded, so empty list means no skills
        validated_relevant_skills = []  # Keep as empty list, not None - this ensures only preselected skills are forwarded
        logger.info(f"{log_prefix} No skill preselection from preprocessing. No skills will be provided to main processing (architecture: only preselected skills are forwarded).")
    
    # Use validated values instead of raw llm_analysis_args values
    # This ensures all fields meet their constraints and prevents downstream errors
    final_result = PreprocessingResult(
        can_proceed=True,
        rejection_reason=None,
        harmful_or_illegal_score=harmful_or_illegal_val,
        category=validated_category or "general_knowledge",  # Use validated category, fallback to general_knowledge if None
        llm_response_temp=llm_response_temp_val,  # Use validated temperature (clamped to 0.0-2.0)
        complexity=complexity_val,  # Use validated complexity (enum: ["simple", "complex"])
        misuse_risk_score=misuse_risk_val,
        load_app_settings_and_memories=load_app_settings_and_memories_val,  # Use validated keys (filtered against available metadata)
        relevant_embedded_previews=relevant_embedded_previews_val,  # Use relevant embedded preview types for main LLM instruction
        title=llm_analysis_args.get("title"), # Get the title from LLM args (no strict validation needed, just length check in schema)
        icon_names=llm_analysis_args.get("icon_names", []), # Get icon names from LLM args (validation handled client-side)
        chat_summary=chat_summary_val,  # Use validated chat_summary (validated above - may be None if LLM didn't provide it)
        chat_tags=chat_tags_val,  # Use validated chat tags (maxItems: 10)
        relevant_app_skills=validated_relevant_skills,  # Use validated relevant skills (filtered against available skills)
        selected_main_llm_model_id=selected_llm_for_main_id,
        selected_main_llm_model_name=selected_llm_for_main_name,
        selected_mate_id=selected_mate_id,
        raw_llm_response=llm_analysis_args,
        error_message=None
    )
    
    logger.info(f"{log_prefix} Preprocessing finished.")
    return final_result
