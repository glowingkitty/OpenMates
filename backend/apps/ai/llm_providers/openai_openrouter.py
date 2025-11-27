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
    Resolve provider overrides for a given OpenRouter model identifier.

    model_id should be the OpenRouter model string, e.g.,
    - "openai/gpt-oss-120b"
    - "alibaba/qwen3-235b-a22b-2507"

    We derive the upstream provider ("openai", "alibaba", etc.) from the prefix
    and then look up the model entry in that provider's config by its suffix
    (e.g., "gpt-oss-120b", "qwen3-235b-a22b-2507").
    """
    try:
        if "/" in model_id:
            upstream_provider, model_suffix = model_id.split("/", 1)
        else:
            # Default to openai if no upstream prefix is present
            upstream_provider, model_suffix = "openai", model_id

        provider_config = config_manager.get_provider_config(upstream_provider)
        if not provider_config:
            logger.warning(f"Provider configuration not found for '{upstream_provider}' when resolving overrides for model '{model_id}'")
            return None

        for model in provider_config.get("models", []):
            if isinstance(model, dict) and model.get("id") == model_suffix:
                provider_overrides = model.get("provider_overrides")
                if provider_overrides:
                    logger.debug(f"Found provider overrides for {upstream_provider}/{model_suffix}: {provider_overrides}")
                    return provider_overrides
                return None

        logger.warning(f"Model '{model_suffix}' not found in provider config for '{upstream_provider}'")
        return None
    except Exception as e:
        logger.error(f"Error getting provider overrides for model '{model_id}': {str(e)}", exc_info=True)
        return None


def _resolve_openrouter_model_id(model_id: str) -> str:
    """
    Resolve the model identifier to the exact string OpenRouter expects.

    Examples:
    - Input: "alibaba/qwen3-235b-a22b-2507" → Look up provider config for 'alibaba',
      model id 'qwen3-235b-a22b-2507', and if servers.openrouter.model_id exists,
      return that (e.g., "qwen/qwen3-235b-a22b-2507").
    - Input: "qwen/qwen3-235b-a22b-2507" → Already OpenRouter-ready; return as-is.
    - Input: "openai/gpt-oss-120b" → Already OpenRouter-ready; return as-is.
    - Input without prefix → return as-is.
    """
    try:
        if "/" not in model_id:
            return model_id

        upstream_provider, model_suffix = model_id.split("/", 1)
        # If it's already an upstream OpenRouter namespace like qwen/* or openai/*, keep it
        if upstream_provider in {"qwen", "openai", "mistral", "anthropic", "google"}:
            return model_id

        provider_config = config_manager.get_provider_config(upstream_provider)
        if not provider_config:
            return model_id

        for model in provider_config.get("models", []):
            if isinstance(model, dict) and model.get("id") == model_suffix:
                servers = model.get("servers") or []
                for server in servers:
                    if isinstance(server, dict) and server.get("id") == "openrouter" and server.get("model_id"):
                        return str(server["model_id"])  # mapped OpenRouter id
                break
        return model_id
    except Exception:
        return model_id


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
        model_id: OpenRouter model id including upstream provider (e.g., "qwen/qwen3-235b-a22b-2507")
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
    
    # When using OpenRouter, always use 'auto' provider selection to let OpenRouter
    # choose the best available provider automatically. This prevents failures when
    # a specific provider (like Mistral) is having issues.
    # OpenRouter's 'auto' will select the best provider based on availability and performance.
    resolved_model_id = "auto"
    logger.info(f"{log_prefix} Using OpenRouter 'auto' provider selection (original model_id: '{model_id}')")
    
    # Don't use provider overrides when using 'auto' - let OpenRouter choose
    provider_overrides = None
    
    # Invoke the OpenRouter API
    return await invoke_openrouter_api(
        task_id=task_id,
        model_id=resolved_model_id,
        messages=messages,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        provider_overrides=provider_overrides
    )