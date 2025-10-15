# backend/apps/ai/llm_providers/cerebras_wrapper.py
# Public wrapper for Cerebras Inference API integration.
# Provides fast inference using Cerebras' specialized hardware.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator

from backend.core.api.app.utils.secrets_manager import SecretsManager

from .cerebras_client import invoke_cerebras_api
from .openai_shared import UnifiedOpenAIResponse, ParsedOpenAIToolCall, OpenAIUsageMetadata

logger = logging.getLogger(__name__)

# Path to the Cerebras API key in Vault
CEREBRAS_SECRET_PATH = "kv/data/providers/cerebras"
CEREBRAS_API_KEY_NAME = "api_key"

# Global state for caching the API key
_cerebras_api_key: Optional[str] = None


async def _get_cerebras_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the Cerebras API key from Vault.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    global _cerebras_api_key
    
    # Return cached key if available
    if _cerebras_api_key:
        return _cerebras_api_key
    
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=CEREBRAS_SECRET_PATH,
            secret_key=CEREBRAS_API_KEY_NAME
        )
        
        if not api_key:
            logger.error("Cerebras API key not found in Vault")
            return None
        
        _cerebras_api_key = api_key
        logger.info("Successfully retrieved Cerebras API key from Vault")
        return api_key
    
    except Exception as e:
        logger.error(f"Error retrieving Cerebras API key: {str(e)}", exc_info=True)
        return None


async def invoke_cerebras_chat_completions(
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
    Public wrapper for invoking the Cerebras Inference API.
    
    Cerebras provides ultra-fast inference using their specialized CS-3 chips,
    offering speeds up to 2000+ tokens/second. The API is OpenAI-compatible.
    
    Documentation: https://inference-docs.cerebras.ai/
    
    Args:
        task_id: Unique identifier for the task
        model_id: Cerebras model id (e.g., "llama-4-scout-17b-16e-instruct")
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
    log_prefix = f"[{task_id}] CerebrasWrapper:"
    logger.info(f"{log_prefix} Preparing to invoke Cerebras API with model '{model_id}'")
    
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
    
    # Get the Cerebras API key from Vault
    api_key = await _get_cerebras_api_key(secrets_manager)
    if not api_key:
        error_msg = "Failed to retrieve Cerebras API key"
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    
    # Invoke the Cerebras API
    return await invoke_cerebras_api(
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

