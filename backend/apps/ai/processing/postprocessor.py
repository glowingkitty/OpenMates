# backend/apps/ai/processing/postprocessor.py
# Post-processing module for generating suggestions and metadata after AI responses

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import datetime

from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


class PostProcessingResult(BaseModel):
    """Result from post-processing stage"""
    follow_up_request_suggestions: List[str] = Field(default_factory=list, description="6 follow-up suggestions (max 5 words each)")
    new_chat_request_suggestions: List[str] = Field(default_factory=list, description="6 new chat suggestions (max 5 words each)")
    harmful_response: float = Field(default=0.0, description="Score 0-10 for harmful response detection")
    top_recommended_apps_for_user: List[str] = Field(default_factory=list, description="Top 5 recommended app IDs for this user based on conversation context")


async def handle_postprocessing(
    task_id: str,
    user_message: str,
    assistant_response: str,
    chat_summary: str,
    chat_tags: List[str],
    base_instructions: Dict[str, Any],
    secrets_manager: SecretsManager,
    cache_service: CacheService,
    available_app_ids: List[str],
    is_incognito: bool = False,
) -> Optional[PostProcessingResult]:
    """
    Generate post-processing suggestions using LLM.

    Args:
        task_id: Task ID for logging
        user_message: Last user message content
        assistant_response: Last assistant response content
        chat_summary: Chat summary from preprocessing (based on full chat history)
        chat_tags: Chat tags from preprocessing (topics, technologies, concepts discussed)
        base_instructions: Base instructions from yml
        secrets_manager: Secrets manager instance
        cache_service: Cache service instance
        available_app_ids: List of available app IDs in the system (required for validation)

    Returns:
        PostProcessingResult with suggestions

    Raises:
        RuntimeError: If post-processing fails (no error swallowing)
    """

    logger.info(f"[Task ID: {task_id}] [PostProcessor] Starting post-processing")

    # CRITICAL: Skip post-processing for incognito chats (no suggestions generated)
    if is_incognito:
        logger.info(f"[Task ID: {task_id}] [PostProcessor] Skipping post-processing for incognito chat - no suggestions will be generated")
        return None

    # Get the post-processing tool definition from base_instructions
    postprocess_tool = base_instructions.get("postprocess_response_tool")
    if not postprocess_tool:
        raise RuntimeError("postprocess_response_tool not found in base_instructions.yml")

    # Build message history for post-processing LLM call
    # Include: system context + chat summary (from preprocessing) + last user message + assistant response
    messages = []

    # Add current date/time context (critical for temporal awareness in suggestions)
    now = datetime.datetime.now(datetime.timezone.utc)
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    # Add system context about the task
    system_message = (
        f"Current date and time: {date_time_str}\n\n"
        "You are analyzing a conversation to generate helpful suggestions. "
        "Generate contextual follow-up suggestions that encourage deeper engagement and exploration. "
        "Generate new chat suggestions that are related but explore new angles."
    )
    messages.append({"role": "system", "content": system_message})

    # Add chat summary and tags from preprocessing (provides context about the full conversation)
    chat_tags_str = ", ".join(chat_tags) if chat_tags else "No tags"
    
    # Add available app IDs to system context
    available_apps_list = ", ".join(sorted(available_app_ids))
    available_apps_context = f"\n\nAvailable app IDs in the system: {available_apps_list}\nIMPORTANT: Only use app IDs from this list. Do not invent or make up app IDs."
    
    messages.append({
        "role": "system",
        "content": f"Full conversation summary: {chat_summary}\nConversation tags: {chat_tags_str}{available_apps_context}"
    })

    # Add the last user-assistant exchange as a single user message
    # (Mistral requires last message to be from user, not assistant)
    combined_context = (
        f"Last user message: {user_message}\n\n"
        f"Assistant's response: {assistant_response}\n\n"
        f"Based on this exchange and the conversation context, generate follow-up and new chat suggestions."
    )
    messages.append({"role": "user", "content": combined_context})

    # Use same model as preprocessing (Mistral Small) for consistency
    model_id = "mistral/mistral-small-latest"

    # Call the LLM with function calling
    llm_result: LLMPreprocessingCallResult = await call_preprocessing_llm(
        task_id=task_id,
        model_id=model_id,
        message_history=messages,
        tool_definition=postprocess_tool,
        secrets_manager=secrets_manager,
        user_app_settings_and_memories_metadata=None,  # Not needed for post-processing
        dynamic_context=None  # No dynamic context needed
    )

    if llm_result.error_message:
        raise RuntimeError(f"LLM call failed: {llm_result.error_message}")

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
    
    result = PostProcessingResult(
        follow_up_request_suggestions=llm_result.arguments.get("follow_up_request_suggestions", []),
        new_chat_request_suggestions=llm_result.arguments.get("new_chat_request_suggestions", []),
        harmful_response=llm_result.arguments.get("harmful_response", 0.0),
        top_recommended_apps_for_user=validated_app_ids[:5]  # Limit to 5 and use validated IDs
    )

    # Validate that we have the required number of suggestions
    if len(result.follow_up_request_suggestions) < 6:
        logger.warning(f"[Task ID: {task_id}] [PostProcessor] Only {len(result.follow_up_request_suggestions)} follow-up suggestions generated (expected 6)")

    if len(result.new_chat_request_suggestions) < 6:
        logger.warning(f"[Task ID: {task_id}] [PostProcessor] Only {len(result.new_chat_request_suggestions)} new chat suggestions generated (expected 6)")

    if len(validated_app_ids) < len(raw_top_recommended_apps):
        logger.info(f"[Task ID: {task_id}] [PostProcessor] Filtered {len(raw_top_recommended_apps) - len(validated_app_ids)} invalid app IDs. "
                   f"Returning {len(validated_app_ids)} validated app IDs: {validated_app_ids}")

    logger.info(f"[Task ID: {task_id}] [PostProcessor] Successfully generated {len(result.follow_up_request_suggestions)} follow-up suggestions, "
               f"{len(result.new_chat_request_suggestions)} new chat suggestions, and {len(result.top_recommended_apps_for_user)} validated app recommendations")

    return result
