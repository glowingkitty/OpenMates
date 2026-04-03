# backend/apps/ai/processing/postprocessor.py
# Post-processing module for generating suggestions and metadata after AI responses.
#
# Generates follow-up suggestions, new chat suggestions, chat summaries,
# daily inspiration topics, and harmful response detection.
#
# Architecture context: Settings/memories suggestions were moved from post-processing
# to inline deep links in the main AI response. See docs/architecture/app-skills.md.

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
    valid_app_ids: Optional[set] = None,
) -> List[str]:
    """
    Post-LLM sanitizer: validate and clean suggestions that may carry [app_id-X] or [app_id] prefixes.

    Rules:
    - If a suggestion starts with [prefix], check that prefix is in the valid set.
    - App-only prefixes like [ai], [code] are valid if they match a known app ID.
    - Invalid prefixes are stripped (the body text is kept, prefixed with [ai] fallback).
    - Memory prefixes are only allowed in follow-up suggestions (allow_memory_prefixes=True).
    - Suggestions without any prefix get [ai] prepended as fallback.
    - Suggestions that are empty after stripping are dropped.

    Args:
        suggestions: Raw suggestion strings from the LLM
        valid_skill_ids: Set of valid "app_id-skill_id" strings
        valid_focus_ids: Set of valid "app_id-focus_id" strings
        valid_memory_ids: Set of valid "app_id-memory_id" strings (dot-notation converted)
        allow_memory_prefixes: Whether memory prefixes are allowed in this suggestion list
        task_id: Task ID for logging
        valid_app_ids: Set of valid app IDs for app-only prefixes (e.g. {"ai", "web", "code"})

    Returns:
        Cleaned list of suggestion strings (same count or fewer if some were blank after strip)
    """
    import re

    # All valid compound prefixes (app_id-skill_id / app_id-focus_id)
    all_valid_compound = valid_skill_ids | valid_focus_ids
    if allow_memory_prefixes:
        all_valid_compound = all_valid_compound | valid_memory_ids

    # Valid app-only prefixes (e.g. "ai", "code", "web")
    app_only_valid = valid_app_ids or set()

    PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")

    # Minimum word count for suggestion body text (after stripping the prefix).
    # Suggestions with fewer words are too vague (e.g. "Quantum computing") and
    # should be dropped in favor of action-oriented phrases ("Explain quantum computing basics").
    MIN_BODY_WORDS = 4

    cleaned = []
    for raw in suggestions:
        if not isinstance(raw, str) or not raw.strip():
            continue

        m = PREFIX_RE.match(raw)
        if m:
            prefix = m.group(1).strip()
            body = raw[m.end():].strip()

            # Drop suggestions whose body text is too short (fewer than MIN_BODY_WORDS words)
            if len(body.split()) < MIN_BODY_WORDS:
                logger.debug(
                    f"[Task ID: {task_id}] [PostProcessor] Dropped suggestion with "
                    f"<{MIN_BODY_WORDS} words in body: '[{prefix}] {body}'"
                )
                continue

            if prefix in all_valid_compound or prefix in app_only_valid:
                # Valid prefix — keep as-is
                cleaned.append(raw.strip())
            else:
                # Invalid/hallucinated prefix — replace with [ai] fallback, keep body text
                logger.warning(
                    f"[Task ID: {task_id}] [PostProcessor] Replaced unknown prefix "
                    f"'[{prefix}]' with [ai] fallback. Body: '{body[:60]}'"
                )
                cleaned.append(f"[ai] {body}")
        else:
            # No prefix — prepend [ai] as fallback (every suggestion must have a prefix)
            body = raw.strip()
            if body and len(body.split()) >= MIN_BODY_WORDS:
                logger.debug(
                    f"[Task ID: {task_id}] [PostProcessor] Added [ai] prefix to unprefixed suggestion: '{body[:60]}'"
                )
                cleaned.append(f"[ai] {body}")
            elif body:
                logger.debug(
                    f"[Task ID: {task_id}] [PostProcessor] Dropped unprefixed suggestion with "
                    f"<{MIN_BODY_WORDS} words: '{body}'"
                )

    return cleaned











class PostProcessingResult(BaseModel):
    """Result from post-processing stage"""
    follow_up_request_suggestions: List[str] = Field(default_factory=list, description="6 follow-up suggestions (action-verb focused, min 4 words each)")
    new_chat_request_suggestions: List[str] = Field(default_factory=list, description="6 new chat suggestions (action-verb focused, min 4 words each)")
    harmful_response: float = Field(default=0.0, description="Score 0-10 for harmful response detection")
    top_recommended_apps_for_user: List[str] = Field(default_factory=list, description="Top 5 recommended app IDs for this user based on conversation context")
    chat_summary: Optional[str] = Field(None, description="Updated chat summary (max 20 words) including the latest exchange")
    # Updated chat title: only set when the conversation has evolved significantly beyond the original title.
    # None means the current title still fits. See OPE-265 for feature context.
    updated_chat_title: Optional[str] = Field(None, description="New chat title (3-8 words) if the current title no longer describes the conversation well. None if no update needed.")
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

    available_skills: Optional[List[Dict[str, str]]] = None,
    available_focus_modes: Optional[List[Dict[str, str]]] = None,
    is_incognito: bool = False,
    output_language: str = "en",
    user_system_language: str = "en",
    current_chat_title: Optional[str] = None,
) -> Optional[PostProcessingResult]:
    """
    Generate post-processing suggestions using LLM.
    
    Generates follow-up suggestions, new chat suggestions, chat summaries,
    harmful response detection, app recommendations, and daily inspiration topics.

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

        available_skills: Optional list of production skills for suggestion prefix generation.
            Format: [{"id": "web-search", "hint": "..."}, ...] (app_id-skill_id)
        available_focus_modes: Optional list of production focus modes for suggestion prefix generation.
            Format: [{"id": "jobs-career_insights", "hint": "..."}, ...] (app_id-focus_id)
        output_language: ISO 639-1 code of the chat/conversation language (detected by preprocessor).
            Used for generating follow-up suggestions in the same language as the conversation.
        user_system_language: ISO 639-1 code of the user's UI/system language (from user profile).
            Used for generating new chat suggestions in a consistent language on the welcome screen,
            regardless of which language individual chats were conducted in.
        current_chat_title: The current decrypted chat title (if available). Passed to the LLM so it
            can decide whether the title still fits the conversation. None for new chats (first message).

    Returns:
        PostProcessingResult with suggestions, summaries, and metadata

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
    


    # Build skill/focus context so the LLM can generate [app_id-skill_id] prefixed suggestions.
    # We keep this compact — just ID + one-line hint per item.
    if available_skills:
        skills_lines = "\n".join(
            f"- {s['id']}: {s['hint']}" if s.get("hint") else f"- {s['id']}"
            for s in available_skills
        )
        skills_context = (
            f"\n\nAvailable skill IDs for suggestion prefixes (format: [app_id-skill_id]):\n"
            f"{skills_lines}\n"
            "Use these IDs as [app_id-skill_id] prefix in suggestions when the skill is clearly relevant."
        )
    else:
        skills_context = ""

    if available_focus_modes:
        focus_lines = "\n".join(
            f"- {f['id']}: {f['hint']}" if f.get("hint") else f"- {f['id']}"
            for f in available_focus_modes
        )
        focus_context = (
            f"\n\nAvailable focus mode IDs for suggestion prefixes (format: [app_id-focus_id]):\n"
            f"{focus_lines}\n"
            "Use these IDs as [app_id-focus_id] prefix in suggestions when activating a focus mode is relevant."
        )
    else:
        focus_context = ""

    # App-only prefix context: when no specific skill/focus fits, use [app_id] as prefix.
    # Fallback to [ai] for general knowledge questions that don't map to any specific app.
    app_prefix_context = (
        "\n\nIMPORTANT — Every suggestion MUST have a prefix:\n"
        "- Use [app_id-skill_id] when a specific skill is relevant\n"
        "- Use [app_id-focus_id] when a focus mode is relevant\n"
        "- Use [app_id] (app only) when the app is relevant but no specific skill/focus fits\n"
        "- Use [ai] as fallback for general knowledge questions\n"
        "Do NOT generate suggestions without a prefix."
    )

    # Memory prefixes are no longer used in suggestions — settings/memories suggestions
    # are now generated inline by the main AI processor as deep links in the response text.
    memory_prefix_context = ""

    # Build title update context: pass the current title so the LLM can judge whether it still fits
    if current_chat_title:
        title_context = (
            f"\n\nCurrent chat title: \"{current_chat_title}\"\n"
            "Evaluate whether this title still accurately describes the conversation. "
            "If the conversation has significantly drifted or expanded beyond the original title, "
            "generate an updated_chat_title. If the title still fits reasonably well, leave updated_chat_title empty/null."
        )
    else:
        title_context = (
            "\n\nThis chat does not have a title yet (first message). "
            "Do NOT generate an updated_chat_title — the title is generated separately during preprocessing."
        )

    # Build language instruction for suggestion generation
    # Follow-up suggestions should match the conversation language (output_language) so they
    # feel natural in context. New chat suggestions should use the user's system/UI language
    # so the welcome screen has a consistent language, regardless of individual chat languages.
    language_instruction = (
        f"\n\nLanguage instructions:\n"
        f"- **follow_up_request_suggestions**: Generate in '{output_language}' (the conversation language).\n"
        f"- **new_chat_request_suggestions**: Generate in '{user_system_language}' (the user's system/UI language).\n"
        f"- **chat_summary**: Generate in '{user_system_language}' (the user's system/UI language).\n"
        f"- **updated_chat_title**: Generate in '{user_system_language}' (the user's system/UI language), if needed."
    )

    system_message = (
        f"Current date and time: {date_time_str}\n\n"
        "You are analyzing a conversation to generate helpful suggestions and an updated chat summary. "
        "The full conversation history is provided below. "
        "Generate contextual follow-up suggestions that encourage deeper engagement and exploration. "
        "Generate new chat suggestions that are related but explore new angles.\n\n"
        "CRITICAL — Action-verb style: Every suggestion body (the text after the [prefix]) MUST start with "
        "a strong action verb (Search, Compare, Explain, Write, Find, Create, Show, List, Teach, Help, "
        "Analyze, Summarize, Plan, Design, Build, Describe, Calculate, etc.). "
        "NEVER produce noun-only or adjective-only suggestions (e.g. 'Quantum physics' or 'Latest AI news'). "
        "Every suggestion body must be at least 4 words long.\n\n"
        f"Conversation tags: {chat_tags_str}"
        f"{available_apps_context}"
        f"{skills_context}{focus_context}{memory_prefix_context}"
        f"{app_prefix_context}"
        f"{title_context}"
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
    model_id = "mistral/mistral-small-2506"

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
    # Memory prefixes are no longer used in suggestions (handled by Phase 2 memory generation).
    valid_skill_ids: set = {s["id"] for s in (available_skills or [])}
    valid_focus_ids: set = {f["id"] for f in (available_focus_modes or [])}
    # Note: valid_memory_ids no longer needed — memory prefixes removed from suggestions.

    # Sanitize follow-up suggestions: allow skill + focus + app-only prefixes (no memory —
    # memory suggestions are handled by the automated Phase 2 memory generation step)
    raw_follow_up = llm_result.arguments.get("follow_up_request_suggestions", [])
    sanitized_follow_up = sanitize_suggestions(
        suggestions=raw_follow_up,
        valid_skill_ids=valid_skill_ids,
        valid_focus_ids=valid_focus_ids,
        valid_memory_ids=set(),  # Memory prefixes removed — handled by Phase 2
        allow_memory_prefixes=False,
        task_id=task_id,
        valid_app_ids=available_app_set,
    )

    # Sanitize new chat suggestions: allow skill + focus + app-only prefixes (NO memory)
    raw_new_chat = llm_result.arguments.get("new_chat_request_suggestions", [])
    sanitized_new_chat = sanitize_suggestions(
        suggestions=raw_new_chat,
        valid_skill_ids=valid_skill_ids,
        valid_focus_ids=valid_focus_ids,
        valid_memory_ids=set(),  # Memory not allowed here
        allow_memory_prefixes=False,
        task_id=task_id,
        valid_app_ids=available_app_set,
    )


    # Validate chat_summary from post-processing LLM
    postproc_chat_summary = llm_result.arguments.get("chat_summary")
    if postproc_chat_summary and isinstance(postproc_chat_summary, str) and postproc_chat_summary.strip():
        postproc_chat_summary = postproc_chat_summary.strip()
        logger.debug(f"[Task ID: {task_id}] [PostProcessor] chat_summary generated (length: {len(postproc_chat_summary)} characters)")
    else:
        logger.warning(f"[Task ID: {task_id}] [PostProcessor] chat_summary missing or empty from post-processing LLM. Will fall back to preprocessing summary.")
        postproc_chat_summary = None

    # Validate updated_chat_title from post-processing LLM (OPE-265)
    # Only set when the LLM determines the current title no longer fits the conversation.
    postproc_updated_title = llm_result.arguments.get("updated_chat_title")
    if postproc_updated_title and isinstance(postproc_updated_title, str) and postproc_updated_title.strip():
        postproc_updated_title = postproc_updated_title.strip()
        # Reject if it's the same as the current title (no-op update)
        if current_chat_title and postproc_updated_title.lower() == current_chat_title.lower():
            logger.debug(f"[Task ID: {task_id}] [PostProcessor] updated_chat_title is identical to current title — ignoring")
            postproc_updated_title = None
        else:
            logger.info(
                f"[Task ID: {task_id}] [PostProcessor] updated_chat_title generated: "
                f"'{postproc_updated_title}' (current: '{current_chat_title or 'N/A'}')"
            )
    else:
        postproc_updated_title = None

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

    # Translate the updated title into the user's system/UI language (same pattern as chat_summary).
    # Reuses translate_chat_summary since it's the same isolated translation pattern.
    if postproc_updated_title and output_language != user_system_language:
        logger.info(
            f"[Task ID: {task_id}] [PostProcessor] Translating updated_chat_title to '{user_system_language}'"
        )
        postproc_updated_title = await translate_chat_summary(
            task_id=task_id,
            summary=postproc_updated_title,
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
        updated_chat_title=postproc_updated_title,  # New title if conversation drifted (may be None)

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



    logger.info(
        f"[Task ID: {task_id}] [PostProcessor] Phase 1 complete: "
        f"{len(result.follow_up_request_suggestions)} follow-up suggestions, "
        f"{len(result.new_chat_request_suggestions)} new chat suggestions, "
        f"{len(result.top_recommended_apps_for_user)} app recommendations, "

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

    model_id = "mistral/mistral-small-2506"
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
    - Same cheap model as the rest of post-processing (mistral-small-2506)
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
        f"- Each suggestion may start with a routing prefix in square brackets, e.g. [web-search], [ai], [reminder].\n"
        f"  CRITICAL: Preserve the [prefix] EXACTLY as-is at the start of the translated suggestion.\n"
        f"  Only translate the text that comes AFTER the [prefix]. Never translate or modify the prefix itself.\n"
        f"- Preserve the exact meaning and intent of each suggestion\n"
        f"- Keep each suggestion short (max 8 words after the prefix)\n"
        f"- Return EXACTLY {len(suggestions)} translated suggestions — one per input item\n"
        f"- Use natural, conversational phrasing in {language_name}\n"
        f"- Do NOT add explanations, commentary, or extra items"
    )

    suggestions_list = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(suggestions))
    user_message = (
        f"Important: Preserve the [prefix] at the start of each suggestion unchanged. "
        f"Only translate the text after it.\n\n"
        f"Translate these {len(suggestions)} suggestions to {language_name}:\n\n"
        f"{suggestions_list}"
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    model_id = "mistral/mistral-small-2506"
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


