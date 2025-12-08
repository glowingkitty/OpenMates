# backend/apps/ai/processing/url_corrector.py
# URL correction for assistant responses.
# Corrects full responses with broken URLs by removing broken links and optionally asking about search.

import logging
from typing import List, Dict, Any, Optional
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


async def correct_full_response_with_broken_urls(
    original_response: str,
    broken_urls: List[Dict[str, Any]],
    user_message: str,
    task_id: str,
    model_id: str,
    secrets_manager: Optional[SecretsManager] = None
) -> Optional[str]:
    """
    Use LLM with function calling to correct the full assistant response by removing broken URLs
    and, when appropriate, asking if the user wants the chatbot to search for that topic.
    Uses the same main processing model for consistency.
    Returns the corrected response, or None if correction fails.
    
    Args:
        original_response: Original full assistant response with broken URLs
        broken_urls: List of broken URL info dicts from validation
        user_message: The user's original message for context
        task_id: Task ID for logging
        model_id: Model ID to use for correction (same as main processing model)
        secrets_manager: SecretsManager instance for LLM calls
        
    Returns:
        Corrected full response text, or None if correction fails
    """
    base_instructions = load_base_instructions()
    correction_tool = base_instructions.get("url_correction_tool")
    correction_system_prompt = base_instructions.get("url_correction_system_prompt", "")
    
    if not correction_tool:
        logger.error(f"[{task_id}] URL correction tool definition not found in base_instructions")
        return None
    
    # Build context about broken URLs
    broken_urls_context = "\n".join([
        f"- Link text: '{url['text']}', URL: {url['url']} (Status: {url.get('status_code', 'unknown')})"
        for url in broken_urls
    ])
    
    # Build user message for correction - emphasize asking for search permission
    correction_user_message = f"""Previous user message: {user_message}

Assistant response with broken links:
{original_response}

Broken links found (these need to be removed):
{broken_urls_context}

Please correct the response by:
1. Removing broken links completely (don't keep them)
2. Consider whether it makes sense to ask if the user wants the chatbot to search for that topic
3. Only add a search question if the link was to valuable information (documentation, articles, resources)
4. If the link wasn't essential, just remove it without adding a question
5. Make any search questions sound natural and conversational

The chatbot has access to a web-search skill that can search for any topic.

Examples:
- Documentation link: "You can find more in the [Python docs](broken-link)" → "You can find more information about Python. Would you like me to search for Python documentation?"
- Essential article: "See [this article](broken-link)" → "I can search for more information about this topic if you'd like. Should I do that?"
- Non-essential example: "Example: [example.com](broken-link)" → "Example: example.com" (just remove, no question)

Maintain the same response structure, tone, and content - only remove broken links and optionally add search questions when appropriate."""
    
    messages = [
        {
            "role": "system",
            "content": correction_system_prompt
        },
        {
            "role": "user",
            "content": correction_user_message
        }
    ]
    
    try:
        # Use the same main processing model for consistency
        result = await call_preprocessing_llm(
            task_id=f"{task_id}_url_correction",
            model_id=model_id,  # Use same model as main processing
            message_history=messages,
            tool_definition=correction_tool,
            secrets_manager=secrets_manager
        )
        
        # Extract the corrected response from function call result
        # LLMPreprocessingCallResult has 'arguments' field (Dict[str, Any]) containing the parsed function arguments
        if result.arguments:
            corrected_response = result.arguments.get("assistant_response_corrected")
            
            if corrected_response:
                logger.info(
                    f"[{task_id}] Successfully corrected full response with {len(broken_urls)} broken URLs, "
                    f"added search questions if appropriate"
                )
                return corrected_response
            else:
                logger.warning(
                    f"[{task_id}] URL correction function call completed but 'assistant_response_corrected' not found in result arguments"
                )
                return None
        else:
            # Check if there was an error
            if result.error_message:
                logger.warning(
                    f"[{task_id}] URL correction LLM call failed: {result.error_message}"
                )
            else:
                logger.warning(
                    f"[{task_id}] URL correction LLM call completed but no function call arguments returned"
                )
            return None
            
    except Exception as e:
        logger.error(
            f"[{task_id}] Failed to correct full response with broken URLs: {e}",
            exc_info=True
        )
        return None

