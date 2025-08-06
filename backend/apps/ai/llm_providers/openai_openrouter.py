# backend/apps/ai/llm_providers/openai_openrouter.py
# Public wrapper for OpenRouter API integration with OpenAI models.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager

from .openrouter_client import invoke_openrouter_api
from .openai_shared import UnifiedOpenAIResponse, ParsedOpenAIToolCall, OpenAIUsageMetadata

logger = logging.getLogger(__name__)

# Path to the OpenRouter API key in Vault
OPENROUTER_SECRET_PATH = "kv/data/providers/openrouter"
OPENROUTER_API_KEY_NAME = "api_key"

# Global state
_openrouter_api_key: Optional[str] = None


async def _get_openrouter_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the OpenRouter API key from Vault.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    global _openrouter_api_key
    
    if _openrouter_api_key:
        return _openrouter_api_key
    
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=OPENROUTER_SECRET_PATH,
            secret_key=OPENROUTER_API_KEY_NAME
        )
        
        if not api_key:
            logger.error("OpenRouter API key not found in Vault")
            return None
        
        _openrouter_api_key = api_key
        logger.info("Successfully retrieved OpenRouter API key from Vault")
        return api_key
    
    except Exception as e:
        logger.error(f"Error retrieving OpenRouter API key: {str(e)}", exc_info=True)
        return None


def _get_provider_overrides_for_model(model_id: str) -> Optional[Dict[str, Any]]:
    """
    Gets the provider overrides for the specified model from the provider configuration.
    
    Args:
        model_id: The model ID to get overrides for
        
    Returns:
        The provider overrides if found, None otherwise
    """
    try:
        # Get the OpenAI provider configuration
        provider_config = config_manager.get_provider_config("openai")
        if not provider_config:
            logger.warning(f"OpenAI provider configuration not found for model '{model_id}'")
            return None
        
        # Look for the model in the provider configuration
        models = provider_config.get("models", [])
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_id:
                provider_overrides = model.get("provider_overrides")
                if provider_overrides:
                    logger.debug(f"Found provider overrides for model '{model_id}': {provider_overrides}")
                    return provider_overrides
                else:
                    logger.debug(f"No provider overrides found for model '{model_id}'")
                    return None
        
        logger.warning(f"Model '{model_id}' not found in OpenAI provider configuration")
        return None
        
    except Exception as e:
        logger.error(f"Error getting provider overrides for model '{model_id}': {str(e)}", exc_info=True)
        return None


async def invoke_openrouter_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Public wrapper for invoking the OpenRouter API with OpenAI models.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID to use (e.g., "openai/gpt-oss-120b")
        messages: List of message objects with role and content
        secrets_manager: SecretsManager instance for retrieving API keys
        temperature: Sampling temperature (default: 0.7)
        max_tokens: Maximum number of tokens to generate (default: None)
        tools: List of tool definitions (default: None)
        tool_choice: Tool choice strategy (default: None)
        stream: Whether to stream the response (default: False)
        
    Returns:
        If stream=False, returns a UnifiedOpenAIResponse object.
        If stream=True, returns an AsyncIterator that yields strings, ParsedOpenAIToolCall objects,
        or an OpenAIUsageMetadata object.
    """
    log_prefix = f"[{task_id}] OpenRouterWrapper:"
    logger.info(f"{log_prefix} Preparing to invoke OpenRouter API with model '{model_id}'")
    
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
    
    # Get the OpenRouter API key
    api_key = await _get_openrouter_api_key(secrets_manager)
    if not api_key:
        error_msg = "Failed to retrieve OpenRouter API key"
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    
    # Get provider overrides for the model
    provider_overrides = _get_provider_overrides_for_model(model_id)
    logger.debug(f"{log_prefix} Using provider overrides: {provider_overrides}")
    
    # Invoke the OpenRouter API
    return await invoke_openrouter_api(
        task_id=task_id,
        model_id=model_id,
        messages=messages,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        provider_overrides=provider_overrides
    )