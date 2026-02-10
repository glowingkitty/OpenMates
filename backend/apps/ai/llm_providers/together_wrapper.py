# backend/apps/ai/llm_providers/together_wrapper.py
# Public wrapper for Together AI API integration.
# Provides serverless inference on a wide range of open-source models.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator

from backend.core.api.app.utils.secrets_manager import SecretsManager

from .together_client import invoke_together_api
from .openai_shared import UnifiedOpenAIResponse, ParsedOpenAIToolCall, OpenAIUsageMetadata

logger = logging.getLogger(__name__)

# Path to the Together AI API key in Vault
TOGETHER_SECRET_PATH = "kv/data/providers/together"
TOGETHER_API_KEY_NAME = "api_key"

# Global state for caching the API key
_together_api_key: Optional[str] = None


async def _get_together_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the Together AI API key from Vault.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    global _together_api_key
    
    # Return cached key if available
    if _together_api_key:
        return _together_api_key
    
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=TOGETHER_SECRET_PATH,
            secret_key=TOGETHER_API_KEY_NAME
        )
        
        if not api_key:
            logger.error(
                "Together AI API key not found in Vault at path 'kv/data/providers/together' with key 'api_key'. "
                "Please configure the Together AI API key in Vault to enable Together AI API access."
            )
            return None
        
        _together_api_key = api_key
        logger.info("Successfully retrieved Together AI API key from Vault")
        return api_key
    
    except Exception as e:
        logger.error(f"Error retrieving Together AI API key: {str(e)}", exc_info=True)
        return None


async def invoke_together_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
    top_p: Optional[float] = None,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Public wrapper for invoking the Together AI API.
    
    Together AI provides serverless inference on a wide range of open-source models
    via an OpenAI-compatible API endpoint.
    
    Documentation: https://docs.together.ai/docs/openai-api-compatibility
    
    Args:
        task_id: Unique identifier for the task
        model_id: Together AI model id (e.g., "moonshotai/Kimi-K2.5")
        messages: List of message objects with role and content
        secrets_manager: SecretsManager instance for retrieving API keys
        temperature: Sampling temperature (default: 0.7)
        max_tokens: Maximum number of tokens to generate (default: None)
        tools: List of tool definitions (default: None)
        tool_choice: Tool choice strategy (default: None)
        stream: Whether to stream the response (default: False)
        top_p: Nucleus sampling parameter (default: None)
        
    Returns:
        If stream=False, returns a UnifiedOpenAIResponse object.
        If stream=True, returns an AsyncIterator that yields strings, ParsedOpenAIToolCall objects,
        or an OpenAIUsageMetadata object.
    """
    log_prefix = f"[{task_id}] TogetherWrapper:"
    logger.info(f"{log_prefix} Preparing to invoke Together AI API with model '{model_id}'")
    
    # Validate that secrets_manager is provided
    if not secrets_manager:
        error_msg = "SecretsManager not provided"
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    
    # Get the Together AI API key from Vault
    api_key = await _get_together_api_key(secrets_manager)
    if not api_key:
        error_msg = (
            "Failed to retrieve Together AI API key from Vault. "
            "Please ensure the API key is configured at 'kv/data/providers/together' with key 'api_key'."
        )
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    
    # Invoke the Together AI API
    return await invoke_together_api(
        task_id=task_id,
        model_id=model_id,
        messages=messages,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        top_p=top_p
    )
