# backend/apps/ai/processing/preprocessor.py
# Handles the preprocessing stage of AI skill requests.
#
# SECURITY: This module includes ASCII smuggling protection via the text_sanitization module.
# ASCII smuggling attacks use invisible Unicode characters to embed hidden instructions
# that bypass prompt injection detection but are processed by LLMs.
# See: docs/architecture/prompt_injection_protection.md

import logging
from typing import Dict, Any, List, Optional
import datetime # For current date/time in system prompt

from backend.core.api.app.services.cache import CacheService # Corrected import path
from backend.core.api.app.services.directus.directus import DirectusService # Added for type hinting and reuse
from backend.core.api.app.utils.encryption import EncryptionService # Added for type hinting and reuse
from backend.core.api.app.services.translations import TranslationService # For loading translations

# Import the new LLM utility
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager
# Import Mate utilities
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
# Import AskSkillDefaultConfig and AskSkillRequest
from backend.apps.ai.skills.ask_skill import AskSkillRequest, AskSkillDefaultConfig
from pydantic import BaseModel, Field # For PreprocessingResult model
from backend.shared.python_schemas.app_metadata_schemas import AppYAML  # For type hinting

# Import UserOverrides for @ mentioning syntax support
from backend.core.api.app.utils.override_parser import UserOverrides

# China sensitivity detection is now handled by the preprocessing LLM via the china_model_sensitive field
# This replaces the previous hardcoded keyword-based detection in china_sensitivity.py

# Import model selector for intelligent model selection based on leaderboard rankings
from backend.apps.ai.utils.model_selector import ModelSelector

# Import comprehensive ASCII smuggling sanitization
# This module protects against invisible Unicode characters used to embed hidden instructions
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple

# Import ConfigManager for model provider resolution
from backend.core.api.app.utils.config_manager import config_manager

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
    load_app_settings_and_memories: Optional[List[str]] = Field(None, description="List of app settings and memories keys to load (e.g., ['app_id:item_key']).")
    relevant_embedded_previews: Optional[List[str]] = Field(None, description="List of embedded preview types to generate (e.g., ['code', 'math', 'music']).")
    title: Optional[str] = Field(None, description="Generated title for the chat, if applicable.")
    icon_names: Optional[List[str]] = Field(None, description="List of 1-3 relevant Lucide icon names for the request topic.")
    chat_summary: Optional[str] = Field(None, description="Concise summary (max 20 words) of the full conversation so far.")
    chat_tags: Optional[List[str]] = Field(None, description="Up to 10 tags for categorization and search.")
    relevant_app_skills: Optional[List[str]] = Field(None, description="List of relevant app skill identifiers (format: 'app_id-skill_id') for tool preselection.")
    relevant_focus_modes: Optional[List[str]] = Field(None, description="List of relevant focus mode identifiers (format: 'app_id-focus_id') that could help with this request.")

    selected_mate_id: Optional[str] = None
    selected_main_llm_model_id: Optional[str] = None
    selected_main_llm_model_name: Optional[str] = None # Added

    # Model selection with fallbacks (from intelligent model selector)
    selected_secondary_model_id: Optional[str] = None
    selected_fallback_model_id: Optional[str] = None
    model_selection_reason: Optional[str] = Field(None, description="Explanation of why these models were selected (for debugging/logging).")
    filtered_cn_models: bool = Field(False, description="True if China-origin models were excluded due to sensitive content.")

    # Detected language of the user's request (ISO 639-1 two-letter code)
    # Used for loading disclaimers and other user-facing messages in the correct language
    output_language: str = Field(
        "en",
        description="ISO 639-1 two-letter language code of the user's core request/instruction. Detected by preprocessing LLM."
    )

    # Hardcoded disclaimer injection - ensures legal disclaimers are always shown for sensitive topics
    # This is NOT LLM-dependent; the disclaimer will be appended by stream_consumer after response completes
    requires_advice_disclaimer: Optional[str] = Field(
        None, 
        description="Disclaimer type to inject: 'financial', 'medical', 'legal', or 'mental_health'. Set if category is sensitive AND no disclaimer was recently shown."
    )

    raw_llm_response: Optional[Dict[str, Any]] = Field(None, description="Raw arguments from the LLM tool call.")
    error_message: Optional[str] = None


def _sanitize_text_content(text: str, log_prefix: str = "") -> str:
    """
    Sanitizes text content to protect against ASCII smuggling attacks.
    
    This function is a wrapper around the comprehensive text_sanitization module.
    It removes all invisible Unicode characters that could be used to embed hidden
    instructions, including:
    
    1. Unicode Tags (U+E0000-U+E007F) - Primary ASCII smuggling vector
    2. Variant Selectors (U+FE00-U+FE0F, U+E0100-U+E01EF)
    3. Zero-Width Characters (ZWSP, ZWNJ, ZWJ, Word Joiner, etc.)
    4. Bidirectional Text Controls (LRO, RLO, LRE, RLE, etc.)
    5. Other invisible/formatting characters
    6. ASCII control characters (except common whitespace)
    7. Unicode NFC normalization
    
    SECURITY: This sanitization runs BEFORE LLM-based prompt injection detection.
    The LLM detection handles semantic attacks; this handles character-level attacks.
    
    See: docs/architecture/prompt_injection_protection.md
    See: backend/core/api/app/utils/text_sanitization.py for full implementation details
    
    Args:
        text: The input text to sanitize
        log_prefix: Optional prefix for log messages (e.g., task_id)
    
    Returns:
        Sanitized text with all invisible characters removed
    """
    return sanitize_text_simple(text, log_prefix=log_prefix)


# Mapping from category (Mate categories) to disclaimer types
# These categories trigger hardcoded disclaimer injection to ensure legal compliance
SENSITIVE_CATEGORY_TO_DISCLAIMER = {
    "finance": "financial",
    "medical_health": "medical",
    "legal_law": "legal",
    "life_coach_psychology": "mental_health"
}

# Minimum time (in seconds) before showing the same disclaimer type again
# Even if talking about the same topic, we re-show every 30 minutes
DISCLAIMER_COOLDOWN_SECONDS = 30 * 60  # 30 minutes


async def _check_if_disclaimer_needed(
    chat_id: str,
    disclaimer_type: str,
    cache_service: CacheService,
    log_prefix: str
) -> bool:
    """
    Check if a disclaimer of the given type should be injected.
    
    We inject a disclaimer if:
    1. No disclaimer of this type was shown recently, OR
    2. The cooldown period (30 minutes) has passed since the last disclaimer
    
    This prevents spamming disclaimers while ensuring legal compliance.
    
    Args:
        chat_id: The chat ID to check
        disclaimer_type: The disclaimer type ("financial", "medical", "legal", "mental_health")
        cache_service: Cache service for reading chat metadata
        log_prefix: Logging prefix for debug messages
        
    Returns:
        True if a disclaimer should be injected, False otherwise
    """
    import time
    
    try:
        # Try to get the chat's cached list item data which contains disclaimer tracking
        cache_key = f"chat:{chat_id}:list_item_data"
        cached_data = await cache_service.get(cache_key)
        
        if not cached_data:
            logger.debug(f"{log_prefix} No cached chat data found for {chat_id}, disclaimer needed")
            return True
        
        # Parse the cached data
        import json
        if isinstance(cached_data, str):
            cached_data = json.loads(cached_data)
        
        last_disclaimer_type = cached_data.get("last_disclaimer_type")
        last_disclaimer_timestamp = cached_data.get("last_disclaimer_timestamp")
        
        # If different disclaimer type, we need to show it
        if last_disclaimer_type != disclaimer_type:
            logger.info(
                f"{log_prefix} Different disclaimer type needed. "
                f"Last: {last_disclaimer_type}, Current: {disclaimer_type}"
            )
            return True
        
        # Same type - check if cooldown period has passed
        if last_disclaimer_timestamp:
            current_time = int(time.time())
            time_since_last = current_time - last_disclaimer_timestamp
            
            if time_since_last >= DISCLAIMER_COOLDOWN_SECONDS:
                logger.info(
                    f"{log_prefix} Disclaimer cooldown expired. "
                    f"Last shown {time_since_last}s ago, cooldown is {DISCLAIMER_COOLDOWN_SECONDS}s"
                )
                return True
            else:
                logger.debug(
                    f"{log_prefix} Disclaimer {disclaimer_type} was shown recently "
                    f"({time_since_last}s ago), skipping"
                )
                return False
        
        # No timestamp but same type - shouldn't happen, but inject to be safe
        logger.warning(
            f"{log_prefix} Same disclaimer type but no timestamp - injecting for safety"
        )
        return True
        
    except Exception as e:
        # On any error, default to showing the disclaimer (fail-safe for legal compliance)
        logger.warning(
            f"{log_prefix} Error checking disclaimer state: {e}. "
            f"Defaulting to inject disclaimer for legal compliance."
        )
        return True


def _get_insufficient_credits_error_message() -> str:
    """
    Get the insufficient credits error message from translations.
    Uses TranslationService which loads translations from cache (pre-loaded on server startup).
    Falls back to English hardcoded message if translation service fails.
    
    Translation structure: settings -> billing -> insufficient_credits_error -> { text: "..." }
    
    Returns:
        Translated error message string
    """
    try:
        # TranslationService uses class-level cache, so it's safe to create a new instance
        # Translations are pre-loaded on server startup into shared cache
        translation_service = TranslationService()
        translations = translation_service.get_translations(lang="en")
        
        # Navigate to settings.billing.insufficient_credits_error.text
        # Translation structure: settings -> billing -> insufficient_credits_error -> { text: "..." }
        if translations and "settings" in translations:
            settings = translations["settings"]
            if settings and isinstance(settings, dict) and "billing" in settings:
                billing = settings["billing"]
                if billing and isinstance(billing, dict) and "insufficient_credits_error" in billing:
                    error_msg = billing["insufficient_credits_error"]
                    # Translation is stored as a dict with "text" key per _convert_yaml_to_json_structure
                    if isinstance(error_msg, dict) and "text" in error_msg:
                        return error_msg["text"]
                    elif isinstance(error_msg, str):
                        # Fallback in case structure is different
                        return error_msg
    except Exception as e:
        logger.warning(f"Failed to load insufficient_credits_error translation: {e}. Using fallback message.")
    
    # Fallback to English message if translation lookup fails
    return "You don't have enough credits to complete this request. Please buy more credits or activate auto top-up with a valid payment method."


async def handle_preprocessing(
    request_data: AskSkillRequest,
    base_instructions: Dict[str, Any],
    skill_config: AskSkillDefaultConfig,
    cache_service: CacheService,
    secrets_manager: SecretsManager, # Added SecretsManager
    directus_service: DirectusService, # Added DirectusService for reuse
    encryption_service: EncryptionService, # Added EncryptionService for reuse
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None,
    discovered_apps_metadata: Optional[Dict[str, AppYAML]] = None,  # AppYAML metadata for tool preselection
    user_overrides: Optional[UserOverrides] = None  # User overrides from @ mentioning syntax
) -> PreprocessingResult:
    """
    Handles the preprocessing of an AI skill request.

    Args:
        request_data: The AskSkillRequest Pydantic model.
        base_instructions: Loaded content from base_instructions.yml.
        skill_config: The parsed default_config for the specific skill (e.g., AskSkill).
        user_app_settings_and_memories_metadata: Metadata about available user app settings/memories (app_id -> list of item_keys).
        cache_service: Instance of CacheService for fetching user credits.
        secrets_manager: Instance of SecretsManager.
        directus_service: Instance of DirectusService for reuse.
        encryption_service: Instance of EncryptionService for reuse.

    Returns:
        PreprocessingResult: A Pydantic model containing the results of the preprocessing.
    """
    log_prefix = f"Preprocessor (ChatID: {request_data.chat_id}, MsgID: {request_data.message_id}):"
    logger.info(f"{log_prefix} Starting preprocessing.")

    # --- Credit Check (skip if payment disabled - self-hosted mode) ---
    # Check if payment is enabled before performing credit checks
    # In self-hosted mode, users can use the system without credit restrictions
    from backend.core.api.app.utils.server_mode import is_payment_enabled
    
    payment_enabled = is_payment_enabled()
    
    if payment_enabled:
        MINIMUM_REQUEST_COST = 1
        logger.info(f"{log_prefix} Performing credit check for user_id: {request_data.user_id}. Minimum cost: {MINIMUM_REQUEST_COST}")
        
        if not request_data.user_id:
            logger.error(f"{log_prefix} user_id is missing in request_data. Cannot perform credit check.")
            return PreprocessingResult(
                can_proceed=False,
                rejection_reason="internal_error_missing_user_id",
                error_message="User identification is missing. Cannot proceed."
            )

        cached_user = await cache_service.get_user_by_id(request_data.user_id)

        if not cached_user:
            logger.error(f"{log_prefix} Could not retrieve cached user data for user_id: {request_data.user_id}.")
            
            # For all billable requests (internal or external), we MUST have user data to proceed.
            # External requests should have been warmed by the task worker before calling preprocessor.
            return PreprocessingResult(
                can_proceed=False,
                rejection_reason="internal_error_user_data_not_found",
                error_message="User information could not be retrieved for credit verification. Please ensure your account is valid."
            )

        user_credits = cached_user.get("credits", 0)
        if not isinstance(user_credits, int): # Ensure credits is an int
            logger.error(f"{log_prefix} User credits for {request_data.user_id} is not an integer: {user_credits}. Treating as 0.") # Log actual user_id
            user_credits = 0
        
        logger.info(f"{log_prefix} User {request_data.user_id} has {user_credits} credits.") # Log actual user_id

        if user_credits < MINIMUM_REQUEST_COST:
            logger.warning(f"{log_prefix} User {request_data.user_id} has insufficient credits ({user_credits}) for minimum cost ({MINIMUM_REQUEST_COST}).") # Log actual user_id

            # CRITICAL: Check if user has auto top-up enabled AND a payment method
            # Auto top-up should only be attempted if BOTH conditions are met:
            # 1. User has auto top-up enabled
            # 2. User has a payment method saved
            # NOTE: All checks use cached_user data (from cache_service.get_user_by_id above)
            # No Directus requests are made - we only read from the cached user dict
            auto_topup_enabled = cached_user.get('auto_topup_low_balance_enabled', False)
            
            # Check if user has a payment method before attempting auto top-up
            # Import billing service to check payment method
            from backend.core.api.app.services.billing_service import BillingService

            # Use passed-in service instances instead of creating new ones
            # This avoids redundant initializations and improves performance
            billing_service = BillingService(
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service
            )

            # Check if user has a payment method (reads from cached_user dict - no Directus call)
            # _get_decrypted_payment_method only reads encrypted_payment_method_id from the cached user dict
            # and decrypts it using the vault key. No database queries are made.
            payment_method_id = await billing_service._get_decrypted_payment_method(cached_user)
            has_payment_method = payment_method_id is not None and payment_method_id != ""

            # Only attempt auto top-up if both conditions are met
            if auto_topup_enabled and has_payment_method:
                logger.info(f"{log_prefix} User {request_data.user_id} has auto top-up enabled and a payment method. Attempting to top up before processing...")

                try:
                    # Trigger low balance auto top-up synchronously
                    # This will check cooldown, payment method, and process payment
                    import asyncio
                    await billing_service._trigger_low_balance_topup(request_data.user_id, cached_user)

                    # Wait a moment for payment to process
                    await asyncio.sleep(2)

                    # Refresh user credits from cache after top-up
                    refreshed_user = await cache_service.get_user_by_id(request_data.user_id)
                    if refreshed_user:
                        new_credits = refreshed_user.get("credits", 0)
                        logger.info(f"{log_prefix} After auto top-up: User {request_data.user_id} now has {new_credits} credits.")

                        if new_credits >= MINIMUM_REQUEST_COST:
                            logger.info(f"{log_prefix} Auto top-up successful! Proceeding with message processing.")
                            # Update user_credits to proceed with processing
                            user_credits = new_credits
                            cached_user = refreshed_user
                        else:
                            logger.warning(f"{log_prefix} Auto top-up completed but still insufficient credits ({new_credits}). Rejecting request.")
                            # Return unified insufficient_credits error message from translations
                            return PreprocessingResult(
                                can_proceed=False,
                                rejection_reason="insufficient_credits",
                                error_message=_get_insufficient_credits_error_message(),
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
                    else:
                        logger.error(f"{log_prefix} Failed to refresh user data after auto top-up.")
                        # Return unified insufficient_credits error message from translations
                        return PreprocessingResult(
                            can_proceed=False,
                            rejection_reason="insufficient_credits",
                            error_message=_get_insufficient_credits_error_message(),
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

                except Exception as e:
                    logger.error(f"{log_prefix} Auto top-up failed with error: {e}", exc_info=True)
                    # Return unified insufficient_credits error message from translations
                    return PreprocessingResult(
                        can_proceed=False,
                        rejection_reason="insufficient_credits",
                        error_message=_get_insufficient_credits_error_message(),
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
            else:
                # No auto top-up enabled OR no payment method - reject with unified message
                if auto_topup_enabled and not has_payment_method:
                    logger.warning(f"{log_prefix} User {request_data.user_id} has auto top-up enabled but no payment method. Cannot trigger auto top-up.")
                else:
                    logger.info(f"{log_prefix} User {request_data.user_id} does not have auto top-up enabled or no payment method. Rejecting request.")
                
                # Return unified insufficient_credits error message from translations
                return PreprocessingResult(
                    can_proceed=False,
                    rejection_reason="insufficient_credits",
                    error_message=_get_insufficient_credits_error_message(),
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
    else:
        # Payment disabled (self-hosted mode) - skip credit check
        logger.info(f"{log_prefix} Payment disabled (self-hosted mode). Skipping credit check - allowing request to proceed.")
        # Still get user for other processing, but don't check credits
        if request_data.user_id:
            cached_user = await cache_service.get_user_by_id(request_data.user_id)
            if not cached_user:
                logger.warning(f"{log_prefix} Could not retrieve cached user data for user_id: {request_data.user_id}, but continuing (self-hosted mode).")
    # --- End Credit Check ---
 
    # Sanitize user messages in the history
    # SECURITY: This sanitization protects against ASCII smuggling attacks
    # which use invisible Unicode characters to embed hidden instructions.
    # See: docs/architecture/prompt_injection_protection.md
    sanitized_message_history = []
    for msg in request_data.message_history: # msg is AIHistoryMessage
        msg_dict = msg.model_dump() # Convert Pydantic model to dict
        if msg.role == "user":
            original_content = msg.content # Accessing attribute from original msg Pydantic object
            if isinstance(original_content, str):
                # Use comprehensive ASCII smuggling sanitization
                sanitized_content = _sanitize_text_content(original_content, log_prefix=log_prefix)
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
    
    # Truncate message history to fit within 120k token budget for summary generation
    # This ensures the preprocessing LLM (Mistral Small, 128k context) receives as much
    # conversation context as possible for generating accurate chat summaries,
    # while leaving room for the system prompt, tool definitions, and output tokens.
    # Uses fast character-based estimation (~4 chars/token) to avoid expensive tokenization.
    from backend.apps.ai.utils.llm_utils import truncate_message_history_to_token_budget
    PREPROCESSING_MAX_HISTORY_TOKENS = 120000
    sanitized_message_history = truncate_message_history_to_token_budget(
        sanitized_message_history,
        max_tokens=PREPROCESSING_MAX_HISTORY_TOKENS,
    )
    
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
    # Two lists are maintained:
    #   - available_skills_list: enriched with preprocessor_hints for the LLM prompt (e.g., "travel-price_calendar: Monthly flight price overview...")
    #   - available_skill_ids: bare identifiers for validation of LLM responses (e.g., "travel-price_calendar")
    available_skills_list: List[str] = []
    available_skill_ids: List[str] = []

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
                    available_skill_ids.append(skill_identifier)
                    # Include preprocessor_hint if available so the LLM can make informed skill selection decisions
                    if skill.preprocessor_hint:
                        available_skills_list.append(f"{skill_identifier}: {skill.preprocessor_hint.strip()}")
                    else:
                        available_skills_list.append(skill_identifier)
    
    # Build list of available focus modes from discovered apps
    # Focus modes help the AI specialize for specific tasks (e.g., research, code writing)
    # Format: "app_id-focus_id" with description for LLM context
    available_focus_modes_list: List[str] = []
    
    if discovered_apps_metadata:
        for app_id, app_metadata in discovered_apps_metadata.items():
            if app_metadata and app_metadata.focuses:
                for focus in app_metadata.focuses:
                    # Use hyphen format for focus mode identifiers (consistent with skill tool names)
                    focus_identifier = f"{app_id}-{focus.id}"
                    available_focus_modes_list.append(focus_identifier)
    
    logger.info(f"{log_prefix} Preparing for LLM call. Using {len(available_categories_list)} categories from mates.yml: {available_categories_list}")
    logger.info(f"  - User Message History Length: {len(request_data.message_history)}")
    logger.info(f"  - Tool to call by LLM: {tool_definition_for_llm.get('function', {}).get('name')}")
    logger.info(f"  - Available app skills for tool preselection ({len(available_skills_list)} total): {', '.join(available_skills_list) if available_skills_list else 'None'}")
    logger.info(f"  - Available focus modes ({len(available_focus_modes_list)} total): {', '.join(available_focus_modes_list) if available_focus_modes_list else 'None'}")
    logger.info("  - Dynamic context for LLM prompt:")
    logger.info(f"    - CATEGORIES_LIST: {available_categories_list}")
    logger.info(f"    - AVAILABLE_APP_SKILLS: {available_skills_list if available_skills_list else 'None'}")
    logger.info(f"    - AVAILABLE_FOCUS_MODES: {available_focus_modes_list if available_focus_modes_list else 'None'}")
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
        "AVAILABLE_FOCUS_MODES": available_focus_modes_list if available_focus_modes_list else [],
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
    
    # --- Intelligent Model Selection using Leaderboard Rankings ---
    # Extract task_area and user_unhappy from LLM analysis for model selection
    task_area_val = llm_analysis_args.get("task_area", "general")
    user_unhappy_val = llm_analysis_args.get("user_unhappy", False)

    # Validate task_area (enum: code, math, creative, instruction, general)
    valid_task_areas = ["code", "math", "creative", "instruction", "general"]
    if task_area_val not in valid_task_areas:
        logger.warning(
            f"{log_prefix} LLM returned invalid task_area '{task_area_val}'. "
            f"Valid values: {valid_task_areas}. Defaulting to 'general'."
        )
        task_area_val = "general"
        llm_analysis_args["task_area"] = task_area_val

    # Validate user_unhappy (boolean)
    if not isinstance(user_unhappy_val, bool):
        logger.warning(
            f"{log_prefix} LLM returned non-boolean user_unhappy: {user_unhappy_val}. "
            f"Defaulting to False."
        )
        user_unhappy_val = False
        llm_analysis_args["user_unhappy"] = user_unhappy_val

    # Extract china_model_sensitive from LLM analysis for model filtering
    # When True, China-origin models (DeepSeek, Qwen, etc.) are excluded to avoid censored/biased responses
    # Default to True (conservative) if not provided - better to exclude CN models than risk biased response
    china_model_sensitive_val = llm_analysis_args.get("china_model_sensitive")
    if china_model_sensitive_val is None:
        logger.error(
            f"{log_prefix} CHINA_SENSITIVITY: 'china_model_sensitive' field missing from LLM response! "
            f"This is a required field. Defaulting to True (conservative) to exclude CN models. "
            f"LLM response keys: {list(llm_analysis_args.keys())}"
        )
        china_related = True
    elif not isinstance(china_model_sensitive_val, bool):
        logger.error(
            f"{log_prefix} CHINA_SENSITIVITY: 'china_model_sensitive' is not a boolean: {china_model_sensitive_val} "
            f"(type: {type(china_model_sensitive_val).__name__}). Defaulting to True (conservative)."
        )
        china_related = True
    else:
        china_related = china_model_sensitive_val
    
    if china_related:
        logger.info(
            f"{log_prefix} CHINA_SENSITIVITY: LLM detected politically sensitive content. "
            f"China-origin models will be excluded from selection."
        )

    # Initialize model selection variables
    selected_llm_for_main_id: Optional[str] = None
    selected_llm_for_main_name: Optional[str] = None
    selected_secondary_model_id: Optional[str] = None
    selected_fallback_model_id: Optional[str] = None
    model_selection_reason: Optional[str] = None
    filtered_cn_models = china_related

    # --- Resolve @best-model:{category} to actual model ID ---
    # If the user used @best-model:coding (or similar), resolve it to the top-ranked model
    # in that category from the leaderboard, then treat it like a regular @ai-model override.
    if user_overrides and user_overrides.best_model_category and not user_overrides.model_id:
        best_category = user_overrides.best_model_category
        logger.info(
            f"{log_prefix} BEST_MODEL: Resolving @best-model:{best_category} to top-ranked model"
        )
        try:
            from backend.core.api.app.tasks.leaderboard_tasks import get_best_model_for_category, get_leaderboard_data

            leaderboard_data = await get_leaderboard_data()
            if leaderboard_data:
                best_entry = get_best_model_for_category(
                    leaderboard_data=leaderboard_data,
                    category=best_category,
                    exclude_cn=china_related,
                )
                if best_entry:
                    resolved_model_id = best_entry.get("model_id")
                    resolved_provider = best_entry.get("provider_id")
                    if resolved_model_id and resolved_provider:
                        user_overrides.model_id = resolved_model_id
                        user_overrides.model_provider = None  # Will be resolved from config
                        logger.info(
                            f"{log_prefix} BEST_MODEL: Resolved @best-model:{best_category} -> "
                            f"{resolved_provider}/{resolved_model_id} "
                            f"(composite_score={best_entry.get('composite_score')})"
                        )
                    else:
                        logger.warning(
                            f"{log_prefix} BEST_MODEL: Top model entry missing model_id or provider_id. "
                            f"Entry: {best_entry}. Falling back to auto-selection."
                        )
                else:
                    logger.warning(
                        f"{log_prefix} BEST_MODEL: No models found for category '{best_category}'. "
                        f"Falling back to auto-selection."
                    )
            else:
                logger.warning(
                    f"{log_prefix} BEST_MODEL: No leaderboard data available. "
                    f"Falling back to auto-selection."
                )
        except Exception as e:
            logger.warning(
                f"{log_prefix} BEST_MODEL: Failed to resolve @best-model:{best_category}: {e}. "
                f"Falling back to auto-selection."
            )

    # --- Apply User Model Override (@ai-model:...) if specified ---
    # User can force a specific model using @ai-model:{model_id} or @ai-model:{model_id}:{provider}
    # Also handles resolved @best-model: overrides from above.
    # This overrides the automatic model selection based on leaderboard rankings
    model_override_applied = False
    if user_overrides and user_overrides.model_id:
        override_model_id = user_overrides.model_id
        override_provider = user_overrides.model_provider

        logger.info(
            f"{log_prefix} USER_OVERRIDE: User requested model override. "
            f"model_id={override_model_id}, provider={override_provider}"
        )

        # For now, we accept the user's model_id directly if it contains a provider prefix
        # If it doesn't, we try to infer from the config or use the specified provider
        if "/" in override_model_id:
            # User provided full model reference (e.g., "anthropic/claude-opus-4-5-20251101")
            selected_llm_for_main_id = override_model_id
            # Extract model ID without provider prefix and look up human-readable name
            raw_model_id = override_model_id.split("/")[-1]
            provider_id = override_model_id.split("/")[0]
            # Look up human-readable name from config (e.g., "Claude Haiku 4.5" instead of "claude-haiku-4-5-20251001")
            selected_llm_for_main_name = config_manager.get_model_display_name(raw_model_id, provider_id) or raw_model_id
            model_override_applied = True
            model_selection_reason = f"User override: {selected_llm_for_main_id}"
            logger.info(
                f"{log_prefix} USER_OVERRIDE: Applied full model reference: {selected_llm_for_main_id} (Display name: {selected_llm_for_main_name})"
            )
        elif override_provider:
            # User provided model + provider (e.g., @ai-model:claude-opus-4-5:anthropic)
            selected_llm_for_main_id = f"{override_provider}/{override_model_id}"
            # Look up human-readable name from config
            selected_llm_for_main_name = config_manager.get_model_display_name(override_model_id, override_provider) or override_model_id
            model_override_applied = True
            model_selection_reason = f"User override with provider: {selected_llm_for_main_id}"
            logger.info(
                f"{log_prefix} USER_OVERRIDE: Constructed model reference from provider: {selected_llm_for_main_id} (Display name: {selected_llm_for_main_name})"
            )
        else:
            # User provided only model_id without provider prefix - try to resolve the provider
            logger.info(
                f"{log_prefix} USER_OVERRIDE: Model '{override_model_id}' specified without provider. "
                f"Attempting to resolve provider from config."
            )
            resolved_provider = config_manager.find_provider_for_model(override_model_id)
            if resolved_provider:
                selected_llm_for_main_id = f"{resolved_provider}/{override_model_id}"
                # Look up human-readable name from config
                selected_llm_for_main_name = config_manager.get_model_display_name(override_model_id, resolved_provider) or override_model_id
                model_override_applied = True
                model_selection_reason = f"User override (provider resolved): {selected_llm_for_main_id}"
                logger.info(
                    f"{log_prefix} USER_OVERRIDE: Resolved provider '{resolved_provider}' for model '{override_model_id}'. "
                    f"Full model ID: {selected_llm_for_main_id} (Display name: {selected_llm_for_main_name})"
                )
            else:
                # Could not resolve provider - this will fail billing preflight, but let it proceed
                # so the error message is clear about the missing provider
                logger.warning(
                    f"{log_prefix} USER_OVERRIDE: Could not resolve provider for model '{override_model_id}'. "
                    f"Model not found in any provider configuration. This will likely fail billing validation."
                )
                selected_llm_for_main_id = override_model_id
                selected_llm_for_main_name = override_model_id
                model_override_applied = True
                model_selection_reason = f"User override (unresolved provider): {override_model_id}"

        logger.info(
            f"{log_prefix} USER_OVERRIDE: Final model selection (after override): "
            f"{selected_llm_for_main_id} (Name: {selected_llm_for_main_name})"
        )

    # --- Use Intelligent Model Selector if no user override ---
    if not model_override_applied:
        # Check if auto model selection is enabled in skill_config
        # Default to False for safety - require explicit opt-in
        enable_auto_select = skill_config.enable_auto_model_selection

        if enable_auto_select:
            # Use ModelSelector to select models based on leaderboard rankings
            try:
                from backend.core.api.app.tasks.leaderboard_tasks import get_leaderboard_data

                # Get leaderboard data from cache (preloaded on server startup)
                leaderboard_data = await get_leaderboard_data()

                # Create model selector and select models
                model_selector = ModelSelector(leaderboard_data=leaderboard_data)
                selection_result = model_selector.select_models(
                    task_area=task_area_val,
                    complexity=complexity_val,
                    china_related=china_related,
                    user_unhappy=user_unhappy_val,
                    log_prefix=log_prefix
                )

                selected_llm_for_main_id = selection_result.primary_model_id
                selected_secondary_model_id = selection_result.secondary_model_id
                selected_fallback_model_id = selection_result.fallback_model_id
                model_selection_reason = selection_result.selection_reason
                filtered_cn_models = selection_result.filtered_cn_models

                # Look up human-readable model name from provider config
                # Format of selected_llm_for_main_id: "provider/model_id" (e.g., "google/gemini-3-pro-preview")
                if selected_llm_for_main_id and "/" in selected_llm_for_main_id:
                    provider_part, model_id_part = selected_llm_for_main_id.split("/", 1)
                    selected_llm_for_main_name = config_manager.get_model_display_name(model_id_part, provider_part)
                    if not selected_llm_for_main_name:
                        # Fallback to model ID if display name not found in config
                        selected_llm_for_main_name = model_id_part
                else:
                    selected_llm_for_main_name = selected_llm_for_main_id

                logger.info(
                    f"{log_prefix} MODEL_SELECTION: Intelligent selection completed. "
                    f"task_area={task_area_val}, complexity={complexity_val}, "
                    f"china_related={china_related}, user_unhappy={user_unhappy_val}. "
                    f"Primary: {selected_llm_for_main_id}, Secondary: {selected_secondary_model_id}, "
                    f"Fallback: {selected_fallback_model_id}. Reason: {model_selection_reason}"
                )
            except Exception as e:
                # Fallback to skill_config if model selector fails
                logger.warning(
                    f"{log_prefix} MODEL_SELECTION: Failed to use intelligent model selector: {e}. "
                    f"Falling back to skill_config defaults."
                )
                # Use skill_config defaults as fallback
                if complexity_val == "complex":
                    selected_llm_for_main_id = skill_config.default_llms.main_processing_complex
                    selected_llm_for_main_name = skill_config.default_llms.main_processing_complex_name
                else:
                    selected_llm_for_main_id = skill_config.default_llms.main_processing_simple
                    selected_llm_for_main_name = skill_config.default_llms.main_processing_simple_name

                model_selection_reason = f"Fallback to skill_config (complexity={complexity_val}) after model selector error"
                logger.info(
                    f"{log_prefix} MODEL_SELECTION: Using fallback model from skill_config: "
                    f"{selected_llm_for_main_id} (Name: {selected_llm_for_main_name})"
                )
        else:
            # Auto-selection disabled - use hardcoded models from skill_config
            logger.info(
                f"{log_prefix} MODEL_SELECTION: Auto-selection disabled (enable_auto_model_selection=false). "
                f"Using hardcoded models from skill_config."
            )
            if complexity_val == "complex":
                selected_llm_for_main_id = skill_config.default_llms.main_processing_complex
                selected_llm_for_main_name = skill_config.default_llms.main_processing_complex_name
            else:
                selected_llm_for_main_id = skill_config.default_llms.main_processing_simple
                selected_llm_for_main_name = skill_config.default_llms.main_processing_simple_name

            model_selection_reason = f"Hardcoded from skill_config (auto-selection disabled, complexity={complexity_val})"
    
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
            # Pass the FULL dynamic_context (same as first call) so the retry LLM has all the info
            # it needs. We only extract category from the retry result, but having complete context
            # helps the LLM make a better decision. We also merge relevant_app_skills from the retry
            # as a union with the first call's skills, since the retry may identify skills the first
            # call missed (or vice versa).
            retry_llm_call_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"{request_data.chat_id}_{request_data.message_id}_retry",
                model_id=preprocessing_model,
                fallback_models=preprocessing_fallbacks,
                message_history=sanitized_message_history,
                tool_definition=retry_tool_definition,
                secrets_manager=secrets_manager,
                user_app_settings_and_memories_metadata=user_app_settings_and_memories_metadata,
                dynamic_context=dynamic_context  # Use the same full context as the first call
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
                
                # --- Merge relevant_app_skills from retry into first call's results ---
                # The retry LLM may select different/additional skills compared to the first call.
                # Since the first call returned an invalid category, it may also have had a suboptimal
                # skill selection. We take the UNION of both to maximize coverage.
                # This is safe because the skill validation logic downstream will filter out any
                # invalid skills, and the main LLM decides which tools to actually invoke.
                if retry_llm_call_result.arguments:
                    retry_skills = retry_llm_call_result.arguments.get("relevant_app_skills")
                    original_skills = llm_analysis_args.get("relevant_app_skills")
                    if retry_skills and isinstance(retry_skills, list):
                        if original_skills and isinstance(original_skills, list):
                            # Union: combine both lists, preserving order (original first, then retry additions)
                            original_set = set(original_skills)
                            merged_skills = list(original_skills) + [s for s in retry_skills if s not in original_set]
                            if len(merged_skills) > len(original_skills):
                                logger.info(
                                    f"{log_prefix} Merged relevant_app_skills from retry into first call results. "
                                    f"Original: {original_skills}, Retry: {retry_skills}, Merged: {merged_skills}"
                                )
                                llm_analysis_args["relevant_app_skills"] = merged_skills
                        elif not original_skills or not isinstance(original_skills, list):
                            # First call had no skills, use retry's skills entirely
                            logger.info(
                                f"{log_prefix} Using relevant_app_skills from retry (first call had none): {retry_skills}"
                            )
                            llm_analysis_args["relevant_app_skills"] = retry_skills
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

    # --- Apply User Mate Override (@mate:...) if specified ---
    # User can force a specific mate/persona using @mate:{mate_id} or @mate:{category}
    # This overrides the automatic mate selection based on LLM-detected category.
    # IMPORTANT: Users can specify either the mate ID (e.g., @mate:sophia) or the 
    # category name (e.g., @mate:software_development). We check both.
    if user_overrides and user_overrides.mate_id:
        override_value = user_overrides.mate_id
        override_mate = None
        
        # First, try to match by mate ID (e.g., @mate:sophia)
        override_mate = next((mate for mate in all_mates if mate.id == override_value), None)
        
        # If no match by ID, try to match by category (e.g., @mate:software_development)
        if not override_mate:
            override_mate = next((mate for mate in all_mates if mate.category == override_value), None)
            if override_mate:
                logger.info(
                    f"{log_prefix} USER_OVERRIDE: Matched override value '{override_value}' by category. "
                    f"Resolved to mate_id='{override_mate.id}'"
                )
        
        if override_mate:
            selected_mate_id = override_mate.id
            # Update category to match the mate's category for consistency
            if override_mate.category:
                validated_category = override_mate.category
                llm_analysis_args["category"] = validated_category
            logger.info(
                f"{log_prefix} USER_OVERRIDE: Applied mate override. "
                f"mate_id={selected_mate_id}, category={validated_category} "
                f"(user specified: @mate:{override_value})"
            )
        else:
            logger.warning(
                f"{log_prefix} USER_OVERRIDE: Invalid mate override. "
                f"'{override_value}' not found as mate ID or category. "
                f"Available mates: {[m.id for m in all_mates]}. "
                f"Available categories: {[m.category for m in all_mates]}. "
                f"Keeping automatic selection: {selected_mate_id}"
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
            # Build a set of all available keys (format: "app_id:item_key" using colon for cache mixin compatibility)
            available_keys = set()
            for app_id, item_keys in user_app_settings_and_memories_metadata.items():
                for item_key in item_keys:
                    available_keys.add(f"{app_id}:{item_key}")

            # Helper function to normalize LLM output format to match expected format
            # LLMs may return formats like "code: preferred_tech", "code - preferred_tech", etc.
            # We need to normalize these to "code:preferred_tech" (colon separator, no spaces)
            # NOTE: The cache mixin expects "app_id:item_key" format (colon separator)
            def normalize_app_settings_key(key: str) -> str:
                """
                Normalizes app settings/memories key format from LLM output.
                Handles variations like:
                  - "code: preferred_tech" -> "code:preferred_tech"
                  - "code - preferred_tech" -> "code:preferred_tech"
                  - "code:preferred_tech" -> "code:preferred_tech" (already correct)
                  - "code -preferred_tech" -> "code:preferred_tech"
                  - "code-preferred_tech" -> "code:preferred_tech"
                """
                normalized = key.strip()
                # Handle "app_id: item_key" format (colon followed by space) - remove the space
                normalized = normalized.replace(": ", ":")
                # Handle "app_id : item_key" format (space colon space) - normalize to single colon
                normalized = normalized.replace(" : ", ":")
                # Handle "app_id - item_key" format (space hyphen space) - convert to colon
                normalized = normalized.replace(" - ", ":")
                # Handle "app_id -item_key" or "app_id- item_key" edge cases - convert to colon
                normalized = normalized.replace(" -", ":").replace("- ", ":")
                # Handle any remaining hyphens that are used as separators (single hyphen between app_id and item_key)
                # Only replace if there's no colon already (to avoid double-converting)
                if ":" not in normalized and "-" in normalized:
                    # Replace the first hyphen only (the separator between app_id and item_key)
                    normalized = normalized.replace("-", ":", 1)
                # Remove any leading/trailing whitespace that may have been left
                normalized = normalized.strip()
                return normalized

            # Normalize all LLM-provided keys and validate against available keys
            validated_keys = []
            invalid_keys = []
            for raw_key in load_app_settings_and_memories_val:
                normalized_key = normalize_app_settings_key(raw_key)
                if normalized_key in available_keys:
                    validated_keys.append(normalized_key)
                else:
                    invalid_keys.append(f"{raw_key} (normalized: {normalized_key})")

            if invalid_keys:
                logger.warning(
                    f"{log_prefix} LLM requested {len(invalid_keys)} invalid app_settings_and_memories key(s) that don't exist: {invalid_keys}. "
                    f"Filtered out. Valid keys: {validated_keys}. Available keys: {list(available_keys)}"
                )
            elif validated_keys:
                logger.info(f"{log_prefix} Successfully validated {len(validated_keys)} app_settings_and_memories key(s): {validated_keys}")
            
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
    
    # --- Validate output_language field (ISO 639-1 two-letter code) ---
    # This is used for loading disclaimers and other user-facing messages in the correct language
    SUPPORTED_LANGUAGES = {"en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"}
    output_language_val = llm_analysis_args.get("output_language", "en")
    if not isinstance(output_language_val, str) or output_language_val not in SUPPORTED_LANGUAGES:
        logger.warning(
            f"{log_prefix} LLM returned invalid output_language '{output_language_val}'. "
            f"Valid values are: {sorted(SUPPORTED_LANGUAGES)}. Defaulting to 'en'."
        )
        output_language_val = "en"
        llm_analysis_args["output_language"] = output_language_val
    else:
        logger.info(f"{log_prefix} Detected output language: '{output_language_val}'")

    # Extract relevant_app_skills from LLM response if present (for tool preselection)
    # For now, if not provided by LLM, we'll set to None (meaning all skills available)
    relevant_app_skills_val = llm_analysis_args.get("relevant_app_skills")
    if relevant_app_skills_val and isinstance(relevant_app_skills_val, list):
        # Build a robust skill name resolver to handle common LLM hallucinations
        # This mirrors the tool_resolver_map pattern in main_processor.py
        # Maps hallucinated skill names to valid skill identifiers
        skill_resolver_map: Dict[str, str] = {}
        
        for valid_skill in available_skill_ids:
            # Add exact match
            skill_resolver_map[valid_skill] = valid_skill
            
            # Handle underscore variant: app_skill -> app-skill
            underscore_variant = valid_skill.replace("-", "_")
            skill_resolver_map[underscore_variant] = valid_skill
            
            # Handle duplicated segment pattern: app-skill-skill -> app-skill
            # Example: web-search-search -> web-search
            parts = valid_skill.split("-")
            if len(parts) >= 2:
                # Create duplicated variant: web-search -> web-search-search
                duplicated = f"{valid_skill}-{parts[-1]}"
                skill_resolver_map[duplicated] = valid_skill
                
                # Also handle underscore with duplication: web_search_search -> web-search
                underscore_duplicated = f"{underscore_variant}_{parts[-1].replace('-', '_')}"
                skill_resolver_map[underscore_duplicated] = valid_skill
        
        logger.debug(f"{log_prefix} Built skill resolver map with {len(skill_resolver_map)} entries for handling hallucinated skill names")
        
        # Validate and correct skill identifiers
        validated_relevant_skills = []
        corrected_skills = []
        invalid_skills = []
        
        for skill in relevant_app_skills_val:
            if skill in available_skill_ids:
                # Exact match - no correction needed
                validated_relevant_skills.append(skill)
            elif skill in skill_resolver_map:
                # Hallucinated name that we can correct
                corrected_skill = skill_resolver_map[skill]
                validated_relevant_skills.append(corrected_skill)
                corrected_skills.append(f"{skill} -> {corrected_skill}")
            else:
                # Could not resolve - truly invalid
                invalid_skills.append(skill)
        
        # Remove duplicates while preserving order
        validated_relevant_skills = list(dict.fromkeys(validated_relevant_skills))
        
        if corrected_skills:
            logger.info(
                f"{log_prefix} Corrected {len(corrected_skills)} hallucinated skill name(s): {corrected_skills}"
            )
        
        if invalid_skills:
            logger.warning(
                f"{log_prefix} LLM returned {len(invalid_skills)} invalid skill identifier(s) that couldn't be resolved: {invalid_skills}. "
                f"Filtered out. Available skills: {available_skill_ids if available_skill_ids else 'None'}. "
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
    
    # Extract relevant_focus_modes from LLM response if present (for focus mode activation)
    # Focus modes change how the AI responds by providing specialized system prompt instructions
    relevant_focus_modes_val = llm_analysis_args.get("relevant_focus_modes")
    validated_relevant_focus_modes: List[str] = []
    
    if relevant_focus_modes_val and isinstance(relevant_focus_modes_val, list):
        # Build a resolver map to handle common LLM hallucinations (similar to skills)
        focus_resolver_map: Dict[str, str] = {}
        
        for valid_focus in available_focus_modes_list:
            # Add exact match
            focus_resolver_map[valid_focus] = valid_focus
            
            # Handle underscore variant: app_focus -> app-focus
            underscore_variant = valid_focus.replace("-", "_")
            focus_resolver_map[underscore_variant] = valid_focus
        
        # Validate and correct focus mode identifiers
        corrected_focus_modes = []
        invalid_focus_modes = []
        
        for focus in relevant_focus_modes_val:
            if focus in available_focus_modes_list:
                # Exact match - no correction needed
                validated_relevant_focus_modes.append(focus)
            elif focus in focus_resolver_map:
                # Hallucinated name that we can correct
                corrected_focus = focus_resolver_map[focus]
                validated_relevant_focus_modes.append(corrected_focus)
                corrected_focus_modes.append(f"{focus} -> {corrected_focus}")
            else:
                # Could not resolve - truly invalid
                invalid_focus_modes.append(focus)
        
        # Remove duplicates while preserving order
        validated_relevant_focus_modes = list(dict.fromkeys(validated_relevant_focus_modes))
        
        if corrected_focus_modes:
            logger.info(
                f"{log_prefix} Corrected {len(corrected_focus_modes)} hallucinated focus mode name(s): {corrected_focus_modes}"
            )
        
        if invalid_focus_modes:
            logger.warning(
                f"{log_prefix} LLM returned {len(invalid_focus_modes)} invalid focus mode identifier(s) that couldn't be resolved: {invalid_focus_modes}. "
                f"Filtered out. Available focus modes: {available_focus_modes_list if available_focus_modes_list else 'None'}."
            )
        
        if validated_relevant_focus_modes:
            logger.info(f"{log_prefix} Preprocessing selected {len(validated_relevant_focus_modes)} relevant focus mode(s): {', '.join(validated_relevant_focus_modes)}")
        else:
            logger.debug(f"{log_prefix} Preprocessing selected no relevant focus modes.")
    else:
        logger.debug(f"{log_prefix} No focus mode preselection from preprocessing.")
    
    # --- Determine if hardcoded disclaimer injection is required ---
    # This is a HARDCODED safety mechanism for legal compliance.
    # We do NOT rely on LLM instructions to include disclaimers for sensitive topics.
    # The disclaimer will be appended by stream_consumer AFTER the response completes.
    requires_disclaimer: Optional[str] = None
    final_category = validated_category or "general_knowledge"
    
    if final_category in SENSITIVE_CATEGORY_TO_DISCLAIMER:
        disclaimer_type = SENSITIVE_CATEGORY_TO_DISCLAIMER[final_category]
        
        # Check if we need to show this disclaimer (not shown recently for this type)
        needs_disclaimer = await _check_if_disclaimer_needed(
            chat_id=request_data.chat_id,
            disclaimer_type=disclaimer_type,
            cache_service=cache_service,
            log_prefix=log_prefix
        )
        
        if needs_disclaimer:
            requires_disclaimer = disclaimer_type
            logger.info(
                f"{log_prefix} [DISCLAIMER] Category '{final_category}' requires "
                f"'{disclaimer_type}' disclaimer injection"
            )
        else:
            logger.debug(
                f"{log_prefix} [DISCLAIMER] Category '{final_category}' is sensitive but "
                f"disclaimer was shown recently, skipping"
            )
    
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
        relevant_focus_modes=validated_relevant_focus_modes,  # Use validated relevant focus modes (filtered against available focus modes)
        output_language=output_language_val,  # Detected language of user's request (ISO 639-1 code)
        requires_advice_disclaimer=requires_disclaimer,  # Hardcoded disclaimer type to inject (or None if not needed)
        selected_main_llm_model_id=selected_llm_for_main_id,
        selected_main_llm_model_name=selected_llm_for_main_name,
        selected_secondary_model_id=selected_secondary_model_id,  # Secondary fallback model from leaderboard selection
        selected_fallback_model_id=selected_fallback_model_id,  # Final fallback model (hardcoded reliable default)
        model_selection_reason=model_selection_reason,  # Explanation of model selection for debugging
        filtered_cn_models=filtered_cn_models,  # True if CN models were filtered due to sensitive content
        selected_mate_id=selected_mate_id,
        raw_llm_response=llm_analysis_args,
        error_message=None
    )
    
    logger.info(f"{log_prefix} Preprocessing finished.")
    return final_result
