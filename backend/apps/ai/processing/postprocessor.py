# backend/apps/ai/processing/postprocessor.py
# Post-processing module for generating suggestions and metadata after AI responses
#
# This module implements a two-phase pipeline for generating settings/memories suggestions:
# - Phase 1 (handle_postprocessing): Lightweight category selection based on conversation
# - Phase 2 (handle_memory_generation): Full entry generation with schemas for selected categories

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import datetime

from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult, resolve_fallback_servers_from_provider_config
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.cache import CacheService
from backend.shared.python_schemas.app_metadata_schemas import AppYAML

logger = logging.getLogger(__name__)


def extract_available_skills(
    discovered_apps: Dict[str, AppYAML],
) -> List[Dict[str, str]]:
    """
    Extract a compact list of all production-stage skills from discovered apps.

    These are injected into the postprocessor system prompt so the LLM can
    generate structured suggestions with valid [app_id-skill_id] prefixes.

    Args:
        discovered_apps: Dictionary of discovered app metadata (app_id -> AppYAML)

    Returns:
        List of skill dicts: [{"id": "web-search", "hint": "..."}, ...]
    """
    skills = []

    for app_id, app_metadata in discovered_apps.items():
        if not app_metadata.skills:
            continue

        for skill in app_metadata.skills:
            if getattr(skill, "stage", "development") != "production":
                continue
            # Skip internal skills (auto-invoked, not user-facing)
            if getattr(skill, "internal", False):
                continue

            skill_id = f"{app_id}-{skill.id}"
            hint = getattr(skill, "preprocessor_hint", None) or ""
            # Truncate hint to keep context compact
            if len(hint) > 150:
                hint = hint[:147] + "..."

            skills.append({"id": skill_id, "hint": hint})

    logger.debug(f"[PostProcessor] Extracted {len(skills)} production-stage skills")
    return skills


def extract_available_focus_modes(
    discovered_apps: Dict[str, AppYAML],
) -> List[Dict[str, str]]:
    """
    Extract a compact list of all production-stage focus modes from discovered apps.

    These are injected into the postprocessor system prompt so the LLM can
    generate structured suggestions with valid [app_id-focus_id] prefixes.

    Args:
        discovered_apps: Dictionary of discovered app metadata (app_id -> AppYAML)

    Returns:
        List of focus mode dicts: [{"id": "jobs-career_insights", "hint": "..."}, ...]
    """
    focus_modes = []

    for app_id, app_metadata in discovered_apps.items():
        if not app_metadata.focuses:
            continue

        for focus in app_metadata.focuses:
            if getattr(focus, "stage", None) != "production":
                continue

            focus_id = f"{app_id}-{focus.id}"
            hint = getattr(focus, "preprocessor_hint", None) or ""
            if len(hint) > 150:
                hint = hint[:147] + "..."

            focus_modes.append({"id": focus_id, "hint": hint})

    logger.debug(f"[PostProcessor] Extracted {len(focus_modes)} production-stage focus modes")
    return focus_modes


def sanitize_suggestions(
    suggestions: List[str],
    valid_skill_ids: set,
    valid_focus_ids: set,
    valid_memory_ids: set,
    allow_memory_prefixes: bool,
    task_id: str,
) -> List[str]:
    """
    Post-LLM sanitizer: validate and clean suggestions that may carry [app_id-X] prefixes.

    Rules:
    - If a suggestion starts with [prefix], check that prefix is in the valid set.
    - Invalid prefixes are stripped (the body text is kept so the suggestion isn't lost).
    - Memory prefixes are only allowed in follow-up suggestions (allow_memory_prefixes=True).
    - Suggestions that are empty after stripping are dropped.

    Args:
        suggestions: Raw suggestion strings from the LLM
        valid_skill_ids: Set of valid "app_id-skill_id" strings
        valid_focus_ids: Set of valid "app_id-focus_id" strings
        valid_memory_ids: Set of valid "app_id-memory_id" strings (dot-notation converted)
        allow_memory_prefixes: Whether memory prefixes are allowed in this suggestion list
        task_id: Task ID for logging

    Returns:
        Cleaned list of suggestion strings (same count or fewer if some were blank after strip)
    """
    import re

    # All valid prefixes for this call
    all_valid = valid_skill_ids | valid_focus_ids
    if allow_memory_prefixes:
        all_valid = all_valid | valid_memory_ids

    PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")

    cleaned = []
    for raw in suggestions:
        if not isinstance(raw, str) or not raw.strip():
            continue

        m = PREFIX_RE.match(raw)
        if m:
            prefix = m.group(1).strip()
            body = raw[m.end():].strip()

            if prefix in all_valid:
                # Valid prefix — keep as-is
                cleaned.append(raw.strip())
            else:
                # Invalid/hallucinated prefix — strip the bracket tag, keep body text
                logger.warning(
                    f"[Task ID: {task_id}] [PostProcessor] Stripped unknown prefix "
                    f"'[{prefix}]' from suggestion (not in valid set). Body kept: '{body[:60]}'"
                )
                if body:
                    cleaned.append(body)
        else:
            # No prefix — plain suggestion, always keep
            cleaned.append(raw.strip())

    return cleaned


def extract_settings_memory_categories(
    discovered_apps: Dict[str, AppYAML],
    translation_service: Optional[Any] = None
) -> List[Dict[str, str]]:
    """
    Extract a compact list of all production-stage settings/memory categories from discovered apps.
    
    This is used in Phase 1 of post-processing to provide the LLM with a lightweight list
    of available categories for selection, without including full schemas.
    
    Args:
        discovered_apps: Dictionary of discovered app metadata (app_id -> AppYAML)
        translation_service: Optional translation service to resolve description keys
        
    Returns:
        List of category dictionaries with format:
        [{"id": "app_id.item_type", "description": "Short description of this category"}, ...]
    """
    categories = []
    
    for app_id, app_metadata in discovered_apps.items():
        if not app_metadata.memory_fields:
            continue
            
        for memory_field in app_metadata.memory_fields:
            # Only include production-stage categories
            field_stage = getattr(memory_field, 'stage', 'development')
            if field_stage != 'production':
                continue
            
            # Build category ID in format "app_id.item_type"
            category_id = f"{app_id}.{memory_field.id}"
            
            # Try to get a description from translation service, or use the translation key as fallback
            description = memory_field.description_translation_key
            if translation_service:
                try:
                    # Attempt to resolve translation
                    resolved = translation_service.get_translation(
                        memory_field.description_translation_key,
                        namespace="app_settings_memories"
                    )
                    if resolved:
                        description = resolved
                except Exception:
                    pass  # Use translation key as fallback
            
            # Truncate description if too long (keep it compact for LLM context)
            if len(description) > 100:
                description = description[:97] + "..."
            
            categories.append({
                "id": category_id,
                "description": description
            })
    
    logger.debug(f"[PostProcessor] Extracted {len(categories)} production-stage settings/memory categories")
    return categories


def get_category_schemas(
    discovered_apps: Dict[str, AppYAML],
    category_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """
    Get full schemas for specific categories (used in Phase 2).
    
    Args:
        discovered_apps: Dictionary of discovered app metadata
        category_ids: List of category IDs to get schemas for (format: "app_id.item_type")
        
    Returns:
        Dictionary mapping category_id to its full schema definition
    """
    schemas = {}
    
    for category_id in category_ids:
        parts = category_id.split(".", 1)
        if len(parts) != 2:
            logger.warning(f"[PostProcessor] Invalid category ID format: {category_id}")
            continue
            
        app_id, item_type = parts
        
        app_metadata = discovered_apps.get(app_id)
        if not app_metadata or not app_metadata.memory_fields:
            logger.warning(f"[PostProcessor] App '{app_id}' not found or has no memory fields")
            continue
            
        # Find the matching memory field
        for memory_field in app_metadata.memory_fields:
            if memory_field.id == item_type:
                schemas[category_id] = {
                    "app_id": app_id,
                    "item_type": item_type,
                    "type": memory_field.type,
                    "schema": memory_field.schema_definition or {}
                }
                break
        else:
            logger.warning(f"[PostProcessor] Memory field '{item_type}' not found in app '{app_id}'")
    
    return schemas


class SuggestedSettingsMemoryEntry(BaseModel):
    """
    A single suggested settings/memory entry to be stored by the user.
    Generated during post-processing Phase 2 (memory generation).
    
    The entry follows the schema of the target category but only includes
    fields that can be confidently populated from the conversation.
    Non-certain fields (like proficiency levels) are omitted - the user
    can add those details later if they choose to save the entry.
    """
    app_id: str = Field(description="App ID this entry belongs to (e.g., 'code', 'travel')")
    item_type: str = Field(description="Category ID within the app (e.g., 'preferred_tech', 'trips')")
    suggested_title: str = Field(description="Short title for client-side deduplication (compared against existing entries)")
    item_value: dict = Field(default_factory=dict, description="Entry data matching category schema - only includes certain fields")


class PostProcessingResult(BaseModel):
    """Result from post-processing stage"""
    follow_up_request_suggestions: List[str] = Field(default_factory=list, description="6 follow-up suggestions (max 5 words each)")
    new_chat_request_suggestions: List[str] = Field(default_factory=list, description="6 new chat suggestions (max 5 words each)")
    harmful_response: float = Field(default=0.0, description="Score 0-10 for harmful response detection")
    top_recommended_apps_for_user: List[str] = Field(default_factory=list, description="Top 5 recommended app IDs for this user based on conversation context")
    chat_summary: Optional[str] = Field(None, description="Updated chat summary (max 20 words) including the latest exchange")
    # Phase 1 output: Categories that might be relevant for generating new settings/memories
    relevant_settings_memory_categories: List[str] = Field(default_factory=list, description="Up to 3 category IDs (format: app_id.item_type) that could have new entries based on conversation")
    # Phase 2 output: Actual suggested entries (populated by separate memory generation step)
    suggested_settings_memories: List[SuggestedSettingsMemoryEntry] = Field(default_factory=list, description="Up to 3 suggested new settings/memory entries")
    # Daily inspiration: Topic suggestions collected from conversation for personalized inspiration generation
    # Cached server-side (24h TTL, rolling 50 per user) to inform daily inspiration LLM calls
    daily_inspiration_topic_suggestions: List[str] = Field(
        default_factory=list,
        description="3 concise topic/interest phrases (in English) capturing what the user discussed or showed curiosity about"
    )


async def handle_postprocessing(
    task_id: str,
    user_message: str,
    assistant_response: str,
    chat_summary: str,
    chat_tags: List[str],
    message_history: List[Dict[str, Any]],
    base_instructions: Dict[str, Any],
    secrets_manager: SecretsManager,
    cache_service: CacheService,
    available_app_ids: List[str],
    available_settings_memory_categories: List[Dict[str, str]],
    available_skills: Optional[List[Dict[str, str]]] = None,
    available_focus_modes: Optional[List[Dict[str, str]]] = None,
    is_incognito: bool = False,
    output_language: str = "en",
    user_system_language: str = "en",
) -> Optional[PostProcessingResult]:
    """
    Generate post-processing suggestions using LLM (Phase 1).
    
    This is Phase 1 of the two-phase settings/memories suggestion pipeline:
    - Phase 1 (this function): Identifies relevant categories that might have new entries
    - Phase 2 (handle_memory_generation): Generates actual entry suggestions with full schemas

    Args:
        task_id: Task ID for logging
        user_message: Last user message content
        assistant_response: Last assistant response content
        chat_summary: Chat summary from preprocessing (based on full chat history)
        chat_tags: Chat tags from preprocessing (topics, technologies, concepts discussed)
        message_history: Full chat message history (list of dicts with role/content),
            truncated to 120k token budget. Used for generating accurate updated summaries.
        base_instructions: Base instructions from yml
        secrets_manager: Secrets manager instance
        cache_service: Cache service instance
        available_app_ids: List of available app IDs in the system (required for validation)
        available_settings_memory_categories: List of available categories with descriptions
            Format: [{"id": "code.preferred_tech", "description": "Technologies user prefers"}, ...]
        available_skills: Optional list of production skills for suggestion prefix generation.
            Format: [{"id": "web-search", "hint": "..."}, ...] (app_id-skill_id)
        available_focus_modes: Optional list of production focus modes for suggestion prefix generation.
            Format: [{"id": "jobs-career_insights", "hint": "..."}, ...] (app_id-focus_id)
        output_language: ISO 639-1 code of the chat/conversation language (detected by preprocessor).
            Used for generating follow-up suggestions in the same language as the conversation.
        user_system_language: ISO 639-1 code of the user's UI/system language (from user profile).
            Used for generating new chat suggestions in a consistent language on the welcome screen,
            regardless of which language individual chats were conducted in.

    Returns:
        PostProcessingResult with suggestions and relevant_settings_memory_categories

    Raises:
        RuntimeError: If post-processing fails (no error swallowing)
    """

    logger.info(f"[Task ID: {task_id}] [PostProcessor] Starting post-processing (chat_lang='{output_language}', system_lang='{user_system_language}')")

    # CRITICAL: Skip post-processing for incognito chats (no suggestions generated)
    if is_incognito:
        logger.info(f"[Task ID: {task_id}] [PostProcessor] Skipping post-processing for incognito chat - no suggestions will be generated")
        return None

    # Get the post-processing tool definition from base_instructions
    postprocess_tool = base_instructions.get("postprocess_response_tool")
    if not postprocess_tool:
        raise RuntimeError("postprocess_response_tool not found in base_instructions.yml")

    # Build message history for post-processing LLM call
    # Include: system context + full chat history (truncated to 120k tokens) + latest assistant response
    # The full history allows the LLM to generate accurate updated summaries and contextual suggestions
    messages = []

    # Add current date/time context (critical for temporal awareness in suggestions)
    now = datetime.datetime.now(datetime.timezone.utc)
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    # Add system context about the task
    chat_tags_str = ", ".join(chat_tags) if chat_tags else "No tags"
    
    # Add available app IDs to system context
    available_apps_list = ", ".join(sorted(available_app_ids))
    available_apps_context = f"\n\nAvailable app IDs in the system: {available_apps_list}\nIMPORTANT: Only use app IDs from this list. Do not invent or make up app IDs."
    
    # Add available settings/memory categories for Phase 1 category selection
    # Format: compact list of "category_id: description" for efficient token usage
    if available_settings_memory_categories:
        categories_list = "\n".join([
            f"- {cat['id']}: {cat['description']}" 
            for cat in available_settings_memory_categories
        ])
        settings_memory_context = (
            f"\n\nAvailable settings/memory categories (format: app_id.item_type):\n{categories_list}\n"
            "IMPORTANT: Only select categories from this list. Select up to 3 categories ONLY if the conversation "
            "reveals user preferences, facts, or information that would be valuable to remember."
        )
    else:
        settings_memory_context = ""

    # Build skill/focus context so the LLM can generate [app_id-skill_id] prefixed suggestions.
    # We keep this compact — just ID + one-line hint per item.
    if available_skills:
        skills_lines = "\n".join(
            f"- {s['id']}: {s['hint']}" if s.get("hint") else f"- {s['id']}"
            for s in available_skills
        )
        skills_context = (
            f"\n\nAvailable skill IDs for suggestion prefixes (format: app_id-skill_id):\n"
            f"{skills_lines}\n"
            "Use these IDs as [prefix] in suggestions when the skill is clearly relevant. "
            "Only use IDs from this list. Aim for at least 2-3 skill/focus prefixed suggestions."
        )
    else:
        skills_context = ""

    if available_focus_modes:
        focus_lines = "\n".join(
            f"- {f['id']}: {f['hint']}" if f.get("hint") else f"- {f['id']}"
            for f in available_focus_modes
        )
        focus_context = (
            f"\n\nAvailable focus mode IDs for suggestion prefixes (format: app_id-focus_id):\n"
            f"{focus_lines}\n"
            "Use these IDs as [prefix] in suggestions when activating a focus mode is relevant. "
            "Only use IDs from this list."
        )
    else:
        focus_context = ""

    # Build memory prefix context (only valid in follow-up suggestions, not new-chat)
    if available_settings_memory_categories:
        # Convert dot-notation category IDs to dash-notation for the prefix format
        memory_prefix_lines = "\n".join(
            f"- {cat['id'].replace('.', '-')}: {cat['description']}"
            for cat in available_settings_memory_categories
        )
        memory_prefix_context = (
            f"\n\nAvailable memory/settings IDs for follow-up suggestion prefixes (format: app_id-memory_id):\n"
            f"{memory_prefix_lines}\n"
            "These IDs can be used as [prefix] ONLY in follow_up_request_suggestions (NOT in new_chat_request_suggestions). "
            "Use them only when the conversation reveals information worth saving to a memory category."
        )
    else:
        memory_prefix_context = ""

    # Build language instruction for suggestion generation
    # Follow-up suggestions should match the conversation language (output_language) so they
    # feel natural in context. New chat suggestions should use the user's system/UI language
    # so the welcome screen has a consistent language, regardless of individual chat languages.
    language_instruction = (
        f"\n\nLanguage instructions:\n"
        f"- **follow_up_request_suggestions**: Generate in '{output_language}' (the conversation language).\n"
        f"- **new_chat_request_suggestions**: Generate in '{user_system_language}' (the user's system/UI language).\n"
        f"- **chat_summary**: Generate in '{user_system_language}' (the user's system/UI language)."
    )

    system_message = (
        f"Current date and time: {date_time_str}\n\n"
        "You are analyzing a conversation to generate helpful suggestions and an updated chat summary. "
        "The full conversation history is provided below. "
        "Generate contextual follow-up suggestions that encourage deeper engagement and exploration. "
        "Generate new chat suggestions that are related but explore new angles.\n\n"
        f"Conversation tags: {chat_tags_str}"
        f"{available_apps_context}{settings_memory_context}"
        f"{skills_context}{focus_context}{memory_prefix_context}"
        f"{language_instruction}"
    )
    messages.append({"role": "system", "content": system_message})

    # Include the full chat history (already truncated to 120k token budget by caller)
    # This gives the postprocessor access to the entire conversation for accurate summarization
    # and contextually relevant suggestions, instead of relying on a condensed 20-word summary.
    from backend.apps.ai.utils.llm_utils import truncate_message_history_to_token_budget
    POSTPROCESSING_MAX_HISTORY_TOKENS = 120000
    
    if message_history:
        # Truncate to token budget (in case caller didn't already truncate)
        truncated_history = truncate_message_history_to_token_budget(
            message_history,
            max_tokens=POSTPROCESSING_MAX_HISTORY_TOKENS,
        )
        
        # Transform internal format messages to LLM format (role + content only)
        for msg in truncated_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if not content:
                continue
            # Only include user and assistant messages (skip tool/system messages from history)
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content if isinstance(content, str) else str(content)})
        
        logger.info(
            f"[Task ID: {task_id}] [PostProcessor] Included {len(truncated_history)} messages "
            f"from full chat history for post-processing"
        )
    
    # Append the latest assistant response (not yet in message_history)
    # and a final user instruction for the LLM
    # (Mistral requires last message to be from user, not assistant)
    combined_context = (
        f"Assistant's latest response: {assistant_response}\n\n"
        "Based on the full conversation history above and this latest response, "
        "generate follow-up and new chat suggestions, and update the chat summary."
    )
    messages.append({"role": "user", "content": combined_context})

    # Use same model as preprocessing (Mistral Small) for consistency
    model_id = "mistral/mistral-small-latest"

    # Resolve fallback providers from the model's provider config (e.g. openrouter)
    # so that post-processing is resilient to Mistral API timeouts/outages,
    # the same way the preprocessor handles fallbacks.
    postprocess_fallbacks = resolve_fallback_servers_from_provider_config(model_id)

    # Call the LLM with function calling
    llm_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
        task_id=task_id,
        model_id=model_id,
        message_history=messages,
        tool_definition=postprocess_tool,
        secrets_manager=secrets_manager,
        user_app_settings_and_memories_metadata=None,  # Not needed for post-processing
        dynamic_context=None,  # No dynamic context needed
        fallback_models=postprocess_fallbacks
    )

    # CRITICAL FIX: Handle LLM errors gracefully instead of crashing the entire task
    # When postprocessing fails, we should still deliver the main AI response to the user
    # The only consequence is that suggestions won't be generated - this is acceptable
    if llm_result.error_message:
        logger.error(
            f"[Task ID: {task_id}] [PostProcessor] LLM call failed: {llm_result.error_message}. "
            f"Returning empty result - main AI response will still be delivered without suggestions."
        )
        # Return an empty result instead of crashing - allows main response to be delivered
        return PostProcessingResult(
            follow_up_request_suggestions=[],
            new_chat_request_suggestions=[],
            harmful_response=0.0,
            top_recommended_apps_for_user=[]
        )

    # Handle case where LLM returns empty arguments (might be valid - LLM chose not to generate suggestions)
    # Use empty dict as default if arguments is None or empty
    if llm_result.arguments is None:
        logger.warning(f"[Task ID: {task_id}] [PostProcessor] LLM returned None arguments. Using empty defaults.")
        llm_result.arguments = {}

    # Parse the LLM response into PostProcessingResult
    raw_top_recommended_apps = llm_result.arguments.get("top_recommended_apps_for_user", [])
    
    # Validate and filter app IDs to ensure only real apps are included
    validated_app_ids = []
    available_app_set = set(available_app_ids)
    if raw_top_recommended_apps:
        for app_id in raw_top_recommended_apps:
            if isinstance(app_id, str) and app_id in available_app_set:
                validated_app_ids.append(app_id)
            else:
                logger.warning(f"[Task ID: {task_id}] [PostProcessor] Invalid app ID '{app_id}' filtered out (not in available apps)")
    
    # Build valid prefix sets for the suggestion sanitizer.
    # Skills and focus modes use dash notation (app_id-skill_id / app_id-focus_id).
    # Memory categories are stored as dot notation in available_settings_memory_categories
    # but the LLM is instructed to use dash notation in prefixes, so we convert here.
    valid_skill_ids: set = {s["id"] for s in (available_skills or [])}
    valid_focus_ids: set = {f["id"] for f in (available_focus_modes or [])}
    valid_memory_ids: set = {
        cat["id"].replace(".", "-") for cat in (available_settings_memory_categories or [])
    }

    # Sanitize follow-up suggestions: allow skill + focus + memory prefixes
    raw_follow_up = llm_result.arguments.get("follow_up_request_suggestions", [])
    sanitized_follow_up = sanitize_suggestions(
        suggestions=raw_follow_up,
        valid_skill_ids=valid_skill_ids,
        valid_focus_ids=valid_focus_ids,
        valid_memory_ids=valid_memory_ids,
        allow_memory_prefixes=True,
        task_id=task_id,
    )

    # Sanitize new chat suggestions: allow skill + focus prefixes only (NO memory)
    raw_new_chat = llm_result.arguments.get("new_chat_request_suggestions", [])
    sanitized_new_chat = sanitize_suggestions(
        suggestions=raw_new_chat,
        valid_skill_ids=valid_skill_ids,
        valid_focus_ids=valid_focus_ids,
        valid_memory_ids=set(),  # Memory not allowed here
        allow_memory_prefixes=False,
        task_id=task_id,
    )

    # Validate and filter settings/memory categories (Phase 1 output)
    raw_categories = llm_result.arguments.get("relevant_settings_memory_categories", [])
    validated_categories = []
    available_category_ids = {cat["id"] for cat in available_settings_memory_categories} if available_settings_memory_categories else set()
    if raw_categories:
        for category_id in raw_categories:
            if isinstance(category_id, str) and category_id in available_category_ids:
                validated_categories.append(category_id)
            else:
                logger.warning(f"[Task ID: {task_id}] [PostProcessor] Invalid category ID '{category_id}' filtered out (not in available categories)")
    
    # Validate chat_summary from post-processing LLM
    postproc_chat_summary = llm_result.arguments.get("chat_summary")
    if postproc_chat_summary and isinstance(postproc_chat_summary, str) and postproc_chat_summary.strip():
        postproc_chat_summary = postproc_chat_summary.strip()
        logger.debug(f"[Task ID: {task_id}] [PostProcessor] chat_summary generated (length: {len(postproc_chat_summary)} characters)")
    else:
        logger.warning(f"[Task ID: {task_id}] [PostProcessor] chat_summary missing or empty from post-processing LLM. Will fall back to preprocessing summary.")
        postproc_chat_summary = None

    # Translate the chat summary into the user's system/UI language when the conversation
    # was conducted in a different language. This mirrors the translate_new_chat_suggestions
    # pattern: an isolated call with no conversation context avoids language bleed reliably.
    # The system prompt already instructs the LLM to use user_system_language, but that
    # instruction is frequently overridden when the entire conversation history is in a
    # foreign language. The post-hoc translation call is the reliable enforcement layer.
    if postproc_chat_summary and output_language != user_system_language:
        logger.info(
            f"[Task ID: {task_id}] [PostProcessor] Conversation language '{output_language}' differs "
            f"from UI language '{user_system_language}' — translating chat summary."
        )
        postproc_chat_summary = await translate_chat_summary(
            task_id=task_id,
            summary=postproc_chat_summary,
            target_language=user_system_language,
            secrets_manager=secrets_manager,
        )

    # Parse and validate daily inspiration topic suggestions
    # These are short topic phrases (English, 2-5 words) capturing user interests from the conversation.
    # Stored in server-side cache to inform personalized daily inspiration generation later.
    raw_topic_suggestions = llm_result.arguments.get("daily_inspiration_topic_suggestions", [])
    validated_topic_suggestions = []
    if raw_topic_suggestions and isinstance(raw_topic_suggestions, list):
        for topic in raw_topic_suggestions[:3]:  # Limit to 3
            if isinstance(topic, str) and topic.strip():
                validated_topic_suggestions.append(topic.strip())
    if len(validated_topic_suggestions) < 3:
        logger.warning(
            f"[Task ID: {task_id}] [PostProcessor] Only {len(validated_topic_suggestions)} daily inspiration "
            f"topic suggestions generated (expected 3)"
        )

    # Translate new chat suggestions into the user's system/UI language.
    #
    # Why: The main postprocessor call sees the full conversation history (potentially in any
    # language). Even with explicit language instructions, the model frequently "bleeds" the
    # conversation language into new_chat_request_suggestions. A separate isolated translation
    # call with no conversation context is far more reliable.
    #
    # Follow-up suggestions are intentionally NOT translated here — they should remain in the
    # conversation language (a French chat should show French follow-ups).
    #
    # Note: The sanitized_new_chat list is used here (not raw LLM output) so that the
    # translated suggestions are already free of hallucinated prefixes before translation.
    if sanitized_new_chat:
        translated_new_chat_suggestions = await translate_new_chat_suggestions(
            task_id=task_id,
            suggestions=sanitized_new_chat,
            target_language=user_system_language,
            secrets_manager=secrets_manager,
        )
    else:
        translated_new_chat_suggestions = sanitized_new_chat

    result = PostProcessingResult(
        follow_up_request_suggestions=sanitized_follow_up,
        new_chat_request_suggestions=translated_new_chat_suggestions,
        harmful_response=llm_result.arguments.get("harmful_response", 0.0),
        top_recommended_apps_for_user=validated_app_ids[:5],  # Limit to 5 and use validated IDs
        chat_summary=postproc_chat_summary,  # Updated summary including latest exchange (may be None)
        relevant_settings_memory_categories=validated_categories[:3],  # Limit to 3 categories for Phase 2
        daily_inspiration_topic_suggestions=validated_topic_suggestions,
    )

    # Validate that we have the required number of suggestions
    if len(result.follow_up_request_suggestions) < 6:
        logger.warning(
            f"[Task ID: {task_id}] [PostProcessor] Only {len(result.follow_up_request_suggestions)} follow-up suggestions "
            f"after sanitization (raw: {len(raw_follow_up)}, expected 6)"
        )

    if len(result.new_chat_request_suggestions) < 6:
        logger.warning(
            f"[Task ID: {task_id}] [PostProcessor] Only {len(result.new_chat_request_suggestions)} new chat suggestions "
            f"after sanitization (raw: {len(raw_new_chat)}, expected 6)"
        )

    if len(validated_app_ids) < len(raw_top_recommended_apps):
        logger.info(f"[Task ID: {task_id}] [PostProcessor] Filtered {len(raw_top_recommended_apps) - len(validated_app_ids)} invalid app IDs. "
                   f"Returning {len(validated_app_ids)} validated app IDs: {validated_app_ids}")

    if len(validated_categories) < len(raw_categories):
        logger.info(f"[Task ID: {task_id}] [PostProcessor] Filtered {len(raw_categories) - len(validated_categories)} invalid category IDs. "
                   f"Returning {len(validated_categories)} validated categories: {validated_categories}")

    logger.info(
        f"[Task ID: {task_id}] [PostProcessor] Phase 1 complete: "
        f"{len(result.follow_up_request_suggestions)} follow-up suggestions, "
        f"{len(result.new_chat_request_suggestions)} new chat suggestions, "
        f"{len(result.top_recommended_apps_for_user)} app recommendations, "
        f"{len(result.relevant_settings_memory_categories)} relevant categories for memory generation, "
        f"{len(result.daily_inspiration_topic_suggestions)} daily inspiration topic suggestions"
    )

    return result


async def translate_chat_summary(
    task_id: str,
    summary: str,
    target_language: str,
    secrets_manager: SecretsManager,
) -> str:
    """
    Translate a chat summary into the user's system/UI language via an isolated LLM call.

    Why a separate call instead of relying on the postprocessor's language instruction:
    The main postprocessor call sees the full conversation history (which may be in any language).
    Even with an explicit language instruction, the model frequently generates the summary in the
    conversation language instead of the user's UI language. An isolated call with no conversation
    context is immune to language bleed and reliably produces the correct language.

    Args:
        task_id: Task ID for logging
        summary: Raw chat summary string (may be in the wrong language)
        target_language: ISO 639-1 language code to translate into (e.g. "en", "de", "fr")
        secrets_manager: Secrets manager instance for LLM credentials

    Returns:
        Translated summary string. Falls back to the original summary if the translation
        call fails (non-fatal — we prefer a summary in the wrong language over no summary).
    """
    if not summary or not summary.strip():
        return summary

    logger.info(
        f"[Task ID: {task_id}] [TranslateSummary] Translating chat summary to '{target_language}'"
    )

    # Build the human-readable language name for clearer model instructions
    language_names = {
        "en": "English", "de": "German", "fr": "French", "es": "Spanish",
        "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
        "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
        "ar": "Arabic", "tr": "Turkish", "sv": "Swedish", "no": "Norwegian",
        "da": "Danish", "fi": "Finnish", "cs": "Czech", "ro": "Romanian",
        "hu": "Hungarian", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
        "uk": "Ukrainian",
    }
    language_name = language_names.get(target_language, target_language.upper())

    # Inline tool schema — static and minimal, no conversation context needed
    translation_tool = {
        "type": "function",
        "function": {
            "name": "translate_summary",
            "description": (
                f"Translate a chat summary into {language_name} ({target_language}). "
                "Preserve the exact meaning and keep it concise (max 20 words). "
                "Return only the translated summary text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "translated_summary": {
                        "type": "string",
                        "description": (
                            f"The summary translated into {language_name}. "
                            "Must be concise (max 20 words) and preserve the original meaning."
                        ),
                    }
                },
                "required": ["translated_summary"],
            },
        },
    }

    system_message = (
        f"You are a professional translation engine. "
        f"Translate the given chat summary into {language_name} ({target_language}). "
        f"Rules:\n"
        f"- Preserve the exact meaning of the summary\n"
        f"- Keep it concise (max 20 words)\n"
        f"- Use natural, fluent phrasing in {language_name}\n"
        f"- Do NOT add explanations, commentary, or extra content"
    )

    user_message = f"Translate this chat summary to {language_name}:\n\n{summary}"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    model_id = "mistral/mistral-small-latest"
    translation_fallbacks = resolve_fallback_servers_from_provider_config(model_id)

    try:
        llm_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=task_id,
            model_id=model_id,
            message_history=messages,
            tool_definition=translation_tool,
            secrets_manager=secrets_manager,
            user_app_settings_and_memories_metadata=None,
            dynamic_context=None,
            fallback_models=translation_fallbacks,
        )

        if llm_result.error_message:
            logger.error(
                f"[Task ID: {task_id}] [TranslateSummary] LLM call failed: {llm_result.error_message}. "
                f"Falling back to original (untranslated) summary."
            )
            return summary

        if llm_result.arguments is None:
            logger.warning(
                f"[Task ID: {task_id}] [TranslateSummary] LLM returned None arguments. "
                f"Falling back to original summary."
            )
            return summary

        translated = llm_result.arguments.get("translated_summary", "")

        if not translated or not isinstance(translated, str) or not translated.strip():
            logger.warning(
                f"[Task ID: {task_id}] [TranslateSummary] Empty or invalid translated_summary. "
                f"Falling back to original summary."
            )
            return summary

        logger.info(
            f"[Task ID: {task_id}] [TranslateSummary] Successfully translated summary to '{target_language}'"
        )
        return translated.strip()

    except Exception as e:
        logger.error(
            f"[Task ID: {task_id}] [TranslateSummary] Unexpected error during translation: {e}",
            exc_info=True,
        )
        return summary


async def translate_new_chat_suggestions(
    task_id: str,
    suggestions: List[str],
    target_language: str,
    secrets_manager: SecretsManager,
) -> List[str]:
    """
    Translate new chat suggestions into the user's system/UI language via a dedicated LLM call.

    Why a separate call instead of relying on the postprocessor's language instruction:
    The main postprocessor call sees the full conversation history (which may be in any language).
    Even with an explicit language instruction, the model frequently "bleeds" the conversation
    language into the new_chat_request_suggestions output. A dedicated, isolated translation call
    has no conversation context — it receives only the raw suggestions and the target language,
    making it far more reliable.

    The call is intentionally minimal:
    - No conversation history (avoids language bleed)
    - Tight system prompt focused purely on translation
    - Function calling with a simple schema: { translated_suggestions: string[] }
    - Same cheap model as the rest of post-processing (mistral-small-latest)
    - Token cost: ~130 input + ~50 output tokens per message — negligible

    Args:
        task_id: Task ID for logging
        suggestions: List of raw suggestion strings (may be in any language)
        target_language: ISO 639-1 language code to translate into (e.g. "en", "de", "fr")
        secrets_manager: Secrets manager instance for LLM credentials

    Returns:
        List of translated suggestion strings. Falls back to original suggestions if the
        translation call fails (non-fatal — we prefer showing suggestions in the wrong language
        over showing no suggestions at all).
    """
    if not suggestions:
        return suggestions

    logger.info(
        f"[Task ID: {task_id}] [Translate] Translating {len(suggestions)} new chat suggestions "
        f"to '{target_language}'"
    )

    # Inline tool schema — static and simple, no need for base_instructions.yml
    translation_tool = {
        "type": "function",
        "function": {
            "name": "translate_suggestions",
            "description": (
                "Translate a list of chat suggestions into the specified target language. "
                "Preserve the exact meaning, tone, and format of each suggestion. "
                "Keep suggestions concise (max 5 words each). "
                "Return exactly the same number of suggestions as provided."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "translated_suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The translated suggestions, in the same order as the input. "
                            "Must contain exactly the same number of items as the input list."
                        ),
                    }
                },
                "required": ["translated_suggestions"],
            },
        },
    }

    # Build the language name for clarity (ISO code alone can be ambiguous to the model)
    language_names = {
        "en": "English", "de": "German", "fr": "French", "es": "Spanish",
        "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
        "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
        "ar": "Arabic", "tr": "Turkish", "sv": "Swedish", "no": "Norwegian",
        "da": "Danish", "fi": "Finnish", "cs": "Czech", "ro": "Romanian",
        "hu": "Hungarian", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
        "uk": "Ukrainian",
    }
    language_name = language_names.get(target_language, target_language.upper())

    system_message = (
        f"You are a professional translation engine. "
        f"Translate each suggestion into {language_name} ({target_language}). "
        f"Rules:\n"
        f"- Preserve the exact meaning and intent of each suggestion\n"
        f"- Keep each suggestion short (max 5 words)\n"
        f"- Return EXACTLY {len(suggestions)} translated suggestions — one per input item\n"
        f"- Use natural, conversational phrasing in {language_name}\n"
        f"- Do NOT add explanations, commentary, or extra items"
    )

    suggestions_list = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(suggestions))
    user_message = (
        f"Translate these {len(suggestions)} suggestions to {language_name}:\n\n"
        f"{suggestions_list}"
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    model_id = "mistral/mistral-small-latest"
    translation_fallbacks = resolve_fallback_servers_from_provider_config(model_id)

    try:
        llm_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=task_id,
            model_id=model_id,
            message_history=messages,
            tool_definition=translation_tool,
            secrets_manager=secrets_manager,
            user_app_settings_and_memories_metadata=None,
            dynamic_context=None,
            fallback_models=translation_fallbacks,
        )

        if llm_result.error_message:
            logger.error(
                f"[Task ID: {task_id}] [Translate] LLM call failed: {llm_result.error_message}. "
                f"Falling back to original (untranslated) suggestions."
            )
            return suggestions

        if llm_result.arguments is None:
            logger.warning(
                f"[Task ID: {task_id}] [Translate] LLM returned None arguments. "
                f"Falling back to original suggestions."
            )
            return suggestions

        translated = llm_result.arguments.get("translated_suggestions", [])

        # Validate: must return the same count as input
        if not translated or not isinstance(translated, list):
            logger.warning(
                f"[Task ID: {task_id}] [Translate] Invalid translated_suggestions format. "
                f"Falling back to original suggestions."
            )
            return suggestions

        if len(translated) != len(suggestions):
            logger.warning(
                f"[Task ID: {task_id}] [Translate] Got {len(translated)} translated suggestions "
                f"but expected {len(suggestions)}. Falling back to original suggestions."
            )
            return suggestions

        # Validate each item is a non-empty string
        validated = [s.strip() for s in translated if isinstance(s, str) and s.strip()]
        if len(validated) != len(suggestions):
            logger.warning(
                f"[Task ID: {task_id}] [Translate] {len(suggestions) - len(validated)} translated "
                f"suggestions were empty/invalid. Falling back to original suggestions."
            )
            return suggestions

        logger.info(
            f"[Task ID: {task_id}] [Translate] Successfully translated {len(validated)} "
            f"new chat suggestions to '{target_language}'"
        )
        return validated

    except Exception as e:
        logger.error(
            f"[Task ID: {task_id}] [Translate] Unexpected error during translation: {e}",
            exc_info=True,
        )
        return suggestions


async def handle_memory_generation(
    task_id: str,
    user_message: str,
    assistant_response: str,
    relevant_categories: List[str],
    category_schemas: Dict[str, Dict[str, Any]],
    base_instructions: Dict[str, Any],
    secrets_manager: SecretsManager,
) -> List[SuggestedSettingsMemoryEntry]:
    """
    Phase 2: Generate actual settings/memory entry suggestions.
    
    This function is called ONLY when Phase 1 (handle_postprocessing) identified 
    relevant categories. It receives the full schemas for those categories and
    generates properly structured entry suggestions.
    
    Args:
        task_id: Task ID for logging
        user_message: Last user message content
        assistant_response: Last assistant response content
        relevant_categories: List of category IDs selected in Phase 1 (format: "app_id.item_type")
        category_schemas: Full schemas for the relevant categories
        base_instructions: Base instructions from yml
        secrets_manager: Secrets manager instance
        
    Returns:
        List of suggested settings/memory entries (up to 3)
    """
    logger.info(f"[Task ID: {task_id}] [MemoryGeneration] Phase 2 starting for {len(relevant_categories)} categories: {relevant_categories}")
    
    if not relevant_categories or not category_schemas:
        logger.info(f"[Task ID: {task_id}] [MemoryGeneration] No categories or schemas provided, skipping Phase 2")
        return []
    
    # Get the memory generation tool definition
    memory_gen_tool = base_instructions.get("generate_settings_memories_tool")
    if not memory_gen_tool:
        logger.error(f"[Task ID: {task_id}] [MemoryGeneration] generate_settings_memories_tool not found in base_instructions.yml")
        return []
    
    # Build the schema context for the LLM
    schema_descriptions = []
    for category_id, schema_info in category_schemas.items():
        schema_str = f"""
Category: {category_id}
- App: {schema_info['app_id']}
- Type: {schema_info['item_type']}
- Schema: {schema_info['schema']}
"""
        schema_descriptions.append(schema_str)
    
    schemas_context = "\n".join(schema_descriptions)
    
    # Build message history
    messages = []
    
    # System message with schemas
    system_message = f"""You are generating settings/memory entries based on a conversation.

**Available Categories and Their Schemas:**
{schemas_context}

**CRITICAL RULES:**
1. ONLY fill fields you are 100% CERTAIN about from the conversation
2. If the user didn't explicitly state something (like proficiency level), DO NOT guess - leave it out
3. The suggested_title should be the most identifying field (usually 'name')
4. Better to suggest nothing than to suggest something uncertain
5. Maximum 3 entries total

**Example of what TO DO:**
- User says "I really like working with Python" → Generate entry with name: "Python", NO proficiency
- User says "I'm planning a trip to Tokyo next month" → Generate entry with destination: "Tokyo", NO specific dates unless mentioned

**Example of what NOT TO DO:**
- User asks "What's Python good for?" → This is a QUESTION, not a preference. Do NOT create an entry.
- User says "I've used Python" → This doesn't indicate PREFERENCE, just usage. Be cautious.
"""
    messages.append({"role": "system", "content": system_message})
    
    # Add the conversation context
    combined_context = (
        f"Last user message: {user_message}\n\n"
        f"Assistant's response: {assistant_response}\n\n"
        f"Based on this conversation, generate settings/memory entries ONLY if the user clearly expressed "
        f"preferences, facts about themselves, or information worth remembering. "
        f"If nothing concrete was revealed, return an empty array."
    )
    messages.append({"role": "user", "content": combined_context})
    
    # Use same model as preprocessing for consistency
    model_id = "mistral/mistral-small-latest"

    # Resolve fallback providers from the model's provider config (e.g. openrouter)
    # so that memory generation is resilient to Mistral API timeouts/outages,
    # the same way the preprocessor handles fallbacks.
    memory_gen_fallbacks = resolve_fallback_servers_from_provider_config(model_id)

    try:
        llm_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=task_id,
            model_id=model_id,
            message_history=messages,
            tool_definition=memory_gen_tool,
            secrets_manager=secrets_manager,
            user_app_settings_and_memories_metadata=None,
            dynamic_context=None,
            fallback_models=memory_gen_fallbacks
        )
        
        if llm_result.error_message:
            logger.error(f"[Task ID: {task_id}] [MemoryGeneration] LLM call failed: {llm_result.error_message}")
            return []
        
        if llm_result.arguments is None:
            logger.warning(f"[Task ID: {task_id}] [MemoryGeneration] LLM returned None arguments")
            return []
        
        # Parse the suggested entries
        raw_entries = llm_result.arguments.get("suggested_entries", [])
        if not raw_entries:
            logger.info(f"[Task ID: {task_id}] [MemoryGeneration] LLM returned no suggestions (nothing concrete to suggest)")
            return []
        
        # Validate and convert to SuggestedSettingsMemoryEntry
        valid_entries = []
        valid_category_set = set(relevant_categories)
        
        for entry in raw_entries[:3]:  # Limit to 3
            try:
                app_id = entry.get("app_id", "")
                item_type = entry.get("item_type", "")
                category_id = f"{app_id}.{item_type}"
                
                # Validate that the entry is for a category we asked for
                if category_id not in valid_category_set:
                    logger.warning(f"[Task ID: {task_id}] [MemoryGeneration] Entry for unexpected category '{category_id}' ignored")
                    continue
                
                suggested_entry = SuggestedSettingsMemoryEntry(
                    app_id=app_id,
                    item_type=item_type,
                    suggested_title=entry.get("suggested_title", ""),
                    item_value=entry.get("item_value", {})
                )
                
                # Basic validation: must have a title and at least one field in item_value
                if not suggested_entry.suggested_title:
                    logger.warning(f"[Task ID: {task_id}] [MemoryGeneration] Entry missing suggested_title, skipping")
                    continue
                    
                if not suggested_entry.item_value:
                    logger.warning(f"[Task ID: {task_id}] [MemoryGeneration] Entry has empty item_value, skipping")
                    continue
                
                valid_entries.append(suggested_entry)
                
            except Exception as e:
                logger.warning(f"[Task ID: {task_id}] [MemoryGeneration] Failed to parse entry: {e}")
                continue
        
        logger.info(f"[Task ID: {task_id}] [MemoryGeneration] Phase 2 complete: Generated {len(valid_entries)} valid entries")
        return valid_entries
        
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] [MemoryGeneration] Unexpected error: {e}", exc_info=True)
        return []
