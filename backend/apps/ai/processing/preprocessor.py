# backend/apps/ai/processing/preprocessor.py
# Handles the preprocessing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional
import unicodedata # For Unicode normalization
import re # For removing non-printable characters
 
from backend.core.api.app.services.cache import CacheService # Corrected import path
 
# Import the new LLM utility
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager
# Import Mate utilities
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
# Import AskSkillDefaultConfig and AskSkillRequest
from backend.apps.ai.skills.ask_skill import AskSkillRequest, AskSkillDefaultConfig
from pydantic import BaseModel, Field # For PreprocessingResult model

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
    load_app_settings_and_memories: Optional[List[str]] = Field(None, description="List of app settings and memories keys to load (e.g., ['app_id.item_key']).")
    title: Optional[str] = Field(None, description="Generated title for the chat, if applicable.")
    icon_names: Optional[List[str]] = Field(None, description="List of 1-3 relevant Lucide icon names for the request topic.")
    
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
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None
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

    # Conditionally remove title and icon_names generation if this is NOT the first message
    # Icon/category are generated only once with the title (first message only)
    # Check if this is the first message by examining message history length
    # First message = only 1 message in history (the current user message)
    is_first_message = len(request_data.message_history) <= 1
    
    if not is_first_message:
        logger.info(f"{log_prefix} This is a follow-up message (history length: {len(request_data.message_history)}). Omitting title and icon_names generation from LLM tool call.")
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
        logger.info(f"{log_prefix} This is the first message (history length: {len(request_data.message_history)}). Including title and icon_names generation in LLM tool call.")

    logger.info(f"{log_prefix} Loaded and potentially modified instruction tool (preprocess_request_tool).")
    
    all_mates: List[MateConfig] = load_mates_config()
    if not all_mates:
        logger.critical(f"{log_prefix} CRITICAL: No mates were loaded from mates.yml. Cannot proceed with mate selection or determine available categories.")
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
 
    logger.info(f"{log_prefix} Preparing for LLM call. Using {len(available_categories_list)} categories from mates.yml: {available_categories_list}")
    logger.info(f"  - User Message History Length: {len(request_data.message_history)}")
    logger.info(f"  - Tool to call by LLM: {tool_definition_for_llm.get('function', {}).get('name')}")
    logger.info(f"  - Dynamic context for LLM prompt:")
    logger.info(f"    - CATEGORIES_LIST: {available_categories_list}")
    logger.info(f"    - AVAILABLE_APP_SETTINGS_AND_MEMORIES (from direct param): {user_app_settings_and_memories_metadata}")

    preprocessing_model = skill_config.default_llms.preprocessing_model # Changed variable name and attribute accessed
    logger.info(f"{log_prefix} Using preprocessing_model: {preprocessing_model} from skill_config.") # Updated log message

    llm_call_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
        task_id=f"{request_data.chat_id}_{request_data.message_id}",
        model_id=preprocessing_model,
        message_history=sanitized_message_history,
        tool_definition=tool_definition_for_llm, # Use the (potentially modified) tool definition
        secrets_manager=secrets_manager, # Pass SecretsManager
        user_app_settings_and_memories_metadata=user_app_settings_and_memories_metadata,
        dynamic_context={"CATEGORIES_LIST": available_categories_list}
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
    logger.info(f"{log_prefix} Received LLM analysis args: {llm_analysis_args}")
    if llm_call_result.raw_provider_response_summary:
        logger.debug(f"{log_prefix} Raw provider response summary: {llm_call_result.raw_provider_response_summary}")
    
    HARM_THRESHOLD = skill_config.preprocessing_thresholds.harmful_content_score # Corrected attribute name
    MISUSE_THRESHOLD = skill_config.preprocessing_thresholds.misuse_risk_score
    logger.info(f"{log_prefix} Using HARM_THRESHOLD={HARM_THRESHOLD}, MISUSE_THRESHOLD={MISUSE_THRESHOLD} from skill_config.")

    harmful_or_illegal_val = llm_analysis_args.get("harmful_or_illegal")
    misuse_risk_val = llm_analysis_args.get("misuse_risk")

    # Convert to float to handle both integer and float values
    try:
        harmful_or_illegal_val = float(harmful_or_illegal_val)
    except (ValueError, TypeError):
        logger.warning(f"{log_prefix} 'harmful_or_illegal_score' is not a valid number: {harmful_or_illegal_val}. Defaulting to 0.")
        harmful_or_illegal_val = 0
    
    try:
        misuse_risk_val = float(misuse_risk_val)
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
            title=llm_analysis_args.get("title"), # Also pass title here for consistency in rejection cases
            icon_names=llm_analysis_args.get("icon_names", []) # Also pass icon names for consistency
        )

    else:
        logger.info(f"{log_prefix} Request passed harmful content and misuse risk checks. Scores: Harmful={harmful_or_illegal_val}, Misuse={misuse_risk_val}.")
    
    complexity_val = llm_analysis_args.get("complexity", "simple")
    selected_llm_for_main_id = skill_config.default_llms.main_processing_simple
    selected_llm_for_main_name = skill_config.default_llms.main_processing_simple_name
    if complexity_val == "complex":
        selected_llm_for_main_id = skill_config.default_llms.main_processing_complex
        selected_llm_for_main_name = skill_config.default_llms.main_processing_complex_name
    
    logger.info(f"{log_prefix} Selected LLM for main processing: {selected_llm_for_main_id} (Name: {selected_llm_for_main_name}) based on complexity '{complexity_val}'.")
    
    selected_mate_id: Optional[str] = None
    llm_category = llm_analysis_args.get("category")

    if llm_category:
        if not all_mates:
            logger.error(f"{log_prefix} Mates list is unexpectedly empty during mate selection for category '{llm_category}'.")
        else:
            matched_mate = next((mate for mate in all_mates if mate.category == llm_category), None)
            if matched_mate:
                selected_mate_id = matched_mate.id
                logger.info(f"{log_prefix} Selected Mate ID '{selected_mate_id}' based on LLM category '{llm_category}'.")
            else:
                logger.warning(f"{log_prefix} No mate found for LLM category '{llm_category}'. 'selected_mate_id' will be None. Main processing must handle this.")
    elif "category" in llm_analysis_args:
        logger.warning(f"{log_prefix} LLM provided an empty or null category. Mate selection based on category skipped.")
    else:
        logger.warning(f"{log_prefix} LLM did not provide a 'category' in its response. Mate selection based on category skipped.")
    
    final_result = PreprocessingResult(
        can_proceed=True,
        rejection_reason=None,
        harmful_or_illegal_score=harmful_or_illegal_val,
        category=llm_analysis_args.get("category", "general_knowledge"),
        llm_response_temp=llm_analysis_args.get("llm_response_temp", 0.4),
        complexity=complexity_val,
        misuse_risk_score=misuse_risk_val,
        load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories", []),
        title=llm_analysis_args.get("title"), # Get the title from LLM args
        icon_names=llm_analysis_args.get("icon_names", []), # Get icon names from LLM args
        selected_main_llm_model_id=selected_llm_for_main_id,
        selected_main_llm_model_name=selected_llm_for_main_name,
        selected_mate_id=selected_mate_id,
        raw_llm_response=llm_analysis_args,
        error_message=None
    )
    
    logger.info(f"{log_prefix} Preprocessing finished.")
    return final_result
