# backend/apps/ai/llm_providers/anthropic_client.py
# Client for interacting with Anthropic Claude models via the direct Anthropic API.
#
# AWS Bedrock is handled separately by bedrock_client.py (unified across all providers).
# This module only handles direct Anthropic API access using the anthropic SDK.
#
# Architecture: docs/architecture/ai/ai-model-selection.md

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import anthropic

from backend.core.api.app.utils.secrets_manager import SecretsManager

from .anthropic_shared import UnifiedAnthropicResponse, ParsedAnthropicToolCall, AnthropicUsageMetadata
from .anthropic_direct_api import invoke_direct_api

logger = logging.getLogger(__name__)

# --- Global State ---
_anthropic_client_initialized = False
_anthropic_direct_client: Optional[anthropic.Anthropic] = None


async def initialize_anthropic_client(secrets_manager: SecretsManager):
    """Initialize the Anthropic direct API client from Vault credentials."""
    global _anthropic_client_initialized, _anthropic_direct_client
    if _anthropic_client_initialized:
        logger.debug("Anthropic client already initialized.")
        return

    try:
        logger.info("Attempting to initialize Anthropic direct API client...")

        secret_path = "kv/data/providers/anthropic"
        anthropic_api_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="api_key")

        if anthropic_api_key:
            try:
                _anthropic_direct_client = anthropic.Anthropic(api_key=anthropic_api_key)
                logger.info("Anthropic direct API client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic direct API client: {e}")
                _anthropic_direct_client = None

        if _anthropic_direct_client:
            _anthropic_client_initialized = True
            logger.info("Anthropic client initialization completed successfully.")
        else:
            logger.error("Failed to initialize Anthropic direct API client. Check API key at kv/data/providers/anthropic.")
            _anthropic_client_initialized = False

    except Exception as e:
        logger.error(f"Error during Anthropic client initialization: {e}", exc_info=True)
        _anthropic_client_initialized = False


async def invoke_anthropic_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedAnthropicResponse, AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]]:
    """
    Invoke Anthropic Claude models via the direct Anthropic API.

    Auto-discovered by the provider registry as the handler for server_id="anthropic".
    """
    if not _anthropic_client_initialized:
        if secrets_manager:
            await initialize_anthropic_client(secrets_manager)
        else:
            error_msg = "SecretsManager not provided, and Anthropic client is not initialized."
            logger.error(f"[{task_id}] {error_msg}")
            if stream:
                raise ValueError(error_msg)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    if not _anthropic_client_initialized or not _anthropic_direct_client:
        error_msg = "Anthropic direct API client not available. Check API key at kv/data/providers/anthropic."
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    return await invoke_direct_api(
        task_id, model_id, messages, _anthropic_direct_client,
        temperature, max_tokens, tools, tool_choice, stream
    )
