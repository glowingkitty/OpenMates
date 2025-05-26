# backend/apps/ai/processing/preprocessor.py
# Handles the preprocessing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional
import unicodedata # For Unicode normalization
import re # For removing non-printable characters
 
from backend.core.api.app.services.cache import CacheService # Corrected import path
 
# Import the new LLM utility
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMToolCallResult # Assuming LLMToolCallResult is defined in llm_utils
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
    
    harmful_or_illegal_score: Optional[int] = Field(None, description="Harmfulness score (1-10).")
    category: Optional[str] = Field(None, description="Identified category/topic of the request.")
    llm_response_temp: Optional[float] = Field(None, description="Suggested temperature for the main LLM response.")
    complexity: Optional[str] = Field(None, description="Assessed complexity of the request (e.g., simple, complex).")
    misuse_risk_score: Optional[int] = Field(None, description="Risk score for misuse/scam (1-10).")
    load_app_settings_and_memories: Optional[List[str]] = Field(None, description="List of app settings and memories keys to load (e.g., ['app_id.item_key']).")
    
    selected_mate_id: Optional[str] = None
    selected_main_llm_model_id: Optional[str] = None
    
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
    cache_service: CacheService, # Moved before optional arguments
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
    logger.info(f"{log_prefix} Performing credit check for user_id_hash: {request_data.user_id_hash}. Minimum cost: {MINIMUM_REQUEST_COST}")
    
    if not request_data.user_id_hash:
        logger.error(f"{log_prefix} user_id_hash is missing in request_data. Cannot perform credit check.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_missing_user_id",
            error_message="User identification is missing. Cannot proceed."
        )

    cached_user = await cache_service.get_user_by_id(request_data.user_id_hash)

    if not cached_user:
        logger.error(f"{log_prefix} Could not retrieve cached user data for user_id_hash: {request_data.user_id_hash}.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_user_data_not_found",
            error_message="Could not retrieve user information. Please try again later."
        )

    user_credits = cached_user.get("credits", 0)
    if not isinstance(user_credits, int): # Ensure credits is an int
        logger.error(f"{log_prefix} User credits for {request_data.user_id_hash} is not an integer: {user_credits}. Treating as 0.")
        user_credits = 0
    
    logger.info(f"{log_prefix} User {request_data.user_id_hash} has {user_credits} credits.")

    if user_credits < MINIMUM_REQUEST_COST:
        logger.warning(f"{log_prefix} User {request_data.user_id_hash} has insufficient credits ({user_credits}) for minimum cost ({MINIMUM_REQUEST_COST}).")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="insufficient_credits",
            error_message=f"You have {user_credits} credits, but this action requires at least {MINIMUM_REQUEST_COST}. Please add more credits to continue.",
            harmful_or_illegal_score=None,
            category=None,
            llm_response_temp=None,
            complexity=None,
            misuse_risk_score=None,
            load_app_settings_and_memories=None,
            selected_mate_id=None,
            selected_main_llm_model_id=None,
            raw_llm_response=None
        )
    logger.info(f"{log_prefix} Credit check passed for user {request_data.user_id_hash}.")
    # --- End Credit Check ---
 
    # Sanitize user messages in the history
    sanitized_message_history = []
    for msg in request_data.message_history:
        if msg.get("role") == "user":
            original_content = msg.get("content")
            if isinstance(original_content, str):
                sanitized_content = _sanitize_text_content(original_content)
                if original_content != sanitized_content:
                    logger.debug(f"{log_prefix} Sanitized user message content. Original length: {len(original_content)}, Sanitized length: {len(sanitized_content)}")
                sanitized_message_history.append({**msg, "content": sanitized_content})
            else:
                sanitized_message_history.append(msg)
        else:
            sanitized_message_history.append(msg)
    
    if "preprocess_request_tool" not in base_instructions:
        logger.error(f"{log_prefix} Missing 'preprocess_request_tool' in base_instructions.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_missing_instructions",
            error_message="Critical preprocessing instructions are missing."
        )

    safety_instruction_tool = base_instructions["preprocess_request_tool"]
    logger.info(f"{log_prefix} Loaded Safety Instruction (preprocess_request_tool).")

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
    logger.info(f"  - Tool to call by LLM: {safety_instruction_tool.get('function', {}).get('name')}")
    logger.info(f"  - Dynamic context for LLM prompt:")
    logger.info(f"    - CATEGORIES_LIST: {available_categories_list}")
    logger.info(f"    - AVAILABLE_APP_SETTINGS_AND_MEMORIES (from direct param): {user_app_settings_and_memories_metadata}")

    preprocessing_model_id = skill_config.default_llms.preprocessing_model_id
    logger.info(f"{log_prefix} Using preprocessing_model_id: {preprocessing_model_id} from skill_config.")

    llm_tool_call_result: Optional[LLMToolCallResult] = await call_preprocessing_llm(
        system_prompt=base_instructions.get("safety_instruction",""),
        model_id=preprocessing_model_id,
        message_history=sanitized_message_history,
        tool_config=safety_instruction_tool,
        user_app_settings_and_memories_metadata=user_app_settings_and_memories_metadata
    )

    if not llm_tool_call_result or not llm_tool_call_result.tool_arguments:
        err_msg = "Preprocessing LLM failed to analyze the request or returned no arguments."
        if llm_tool_call_result and llm_tool_call_result.error:
            err_msg = f"Preprocessing LLM error: {llm_tool_call_result.error}"
        logger.error(f"{log_prefix} {err_msg} Model: {preprocessing_model_id}.")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="internal_error_llm_preprocessing_failed",
            error_message=err_msg,
            raw_llm_response={"tool_name": llm_tool_call_result.tool_name if llm_tool_call_result else None, "error": llm_tool_call_result.error if llm_tool_call_result else "No tool call result"}
        )
    
    llm_analysis_args = llm_tool_call_result.tool_arguments
    logger.info(f"{log_prefix} Received LLM analysis args: {llm_analysis_args}")
    
    HARM_THRESHOLD = skill_config.preprocessing_thresholds.harmful_content_threshold
    MISUSE_THRESHOLD = skill_config.preprocessing_thresholds.misuse_risk_threshold
    logger.info(f"{log_prefix} Using HARM_THRESHOLD={HARM_THRESHOLD}, MISUSE_THRESHOLD={MISUSE_THRESHOLD} from skill_config.")

    harmful_score_val = llm_analysis_args.get("harmful_or_illegal_score", 0)
    misuse_score_val = llm_analysis_args.get("misuse_risk_score", 0)

    if not isinstance(harmful_score_val, int):
        logger.warning(f"{log_prefix} 'harmful_or_illegal_score' is not an int: {harmful_score_val}. Defaulting to 0.")
        harmful_score_val = 0
    if not isinstance(misuse_score_val, int):
        logger.warning(f"{log_prefix} 'misuse_risk_score' is not an int: {misuse_score_val}. Defaulting to 0.")
        misuse_score_val = 0

    if harmful_score_val >= HARM_THRESHOLD:
        logger.warning(f"{log_prefix} Request flagged for harmful content. Score: {harmful_score_val}")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="harmful_content_detected",
            error_message=f"Request flagged as potentially harmful or illegal (score: {harmful_score_val}).",
            raw_llm_response=llm_analysis_args,
            harmful_or_illegal_score=harmful_score_val,
            category=llm_analysis_args.get("category"),
            llm_response_temp=llm_analysis_args.get("llm_response_temp"),
            complexity=llm_analysis_args.get("complexity"),
            misuse_risk_score=misuse_score_val,
            load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories")
        )
    
    if misuse_score_val >= MISUSE_THRESHOLD:
        logger.warning(f"{log_prefix} Request flagged for high misuse risk. Score: {misuse_score_val}")
        return PreprocessingResult(
            can_proceed=False,
            rejection_reason="high_misuse_risk",
            error_message=f"Request flagged for high misuse risk (score: {misuse_score_val}).",
            raw_llm_response=llm_analysis_args,
            harmful_or_illegal_score=harmful_score_val,
            category=llm_analysis_args.get("category"),
            llm_response_temp=llm_analysis_args.get("llm_response_temp"),
            complexity=llm_analysis_args.get("complexity"),
            misuse_risk_score=misuse_score_val,
            load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories")
        )

    logger.info(f"{log_prefix} Harmful content and misuse risk checks passed.")
    
    complexity_val = llm_analysis_args.get("complexity", "simple")
    selected_llm_for_main = skill_config.default_llms.main_llm_simple_model_id
    if complexity_val == "complex":
        selected_llm_for_main = skill_config.default_llms.main_llm_complex_model_id
    
    logger.info(f"{log_prefix} Selected LLM for main processing: {selected_llm_for_main} based on complexity '{complexity_val}'.")
    
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
        harmful_or_illegal_score=harmful_score_val,
        category=llm_analysis_args.get("category", "general_knowledge"),
        llm_response_temp=llm_analysis_args.get("llm_response_temp", 0.4),
        complexity=complexity_val,
        misuse_risk_score=misuse_score_val,
        load_app_settings_and_memories=llm_analysis_args.get("load_app_settings_and_memories", []),
        selected_main_llm_model_id=selected_llm_for_main,
        selected_mate_id=selected_mate_id,
        raw_llm_response=llm_analysis_args,
        error_message=None
    )
    
    logger.info(f"{log_prefix} Preprocessing finished. Output: {final_result.model_dump_json(indent=2)}")
    return final_result