# backend/apps/ai/llm_providers/anthropic_client.py
# Client for interacting with Anthropic Claude models via direct API or AWS Bedrock.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import boto3
import anthropic

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager

from .anthropic_shared import UnifiedAnthropicResponse, ParsedAnthropicToolCall, AnthropicUsageMetadata
from .anthropic_direct_api import invoke_direct_api
from .anthropic_bedrock import invoke_bedrock_api

logger = logging.getLogger(__name__)

# --- Global State ---
AWS_REGION: Optional[str] = None
_anthropic_client_initialized = False
_bedrock_runtime_client: Optional[boto3.client] = None
_anthropic_direct_client: Optional[anthropic.Anthropic] = None


def _get_bedrock_model_id(model_id: str) -> str:
    """
    Convert the model_id to the appropriate AWS Bedrock model ID.
    For Anthropic models using AWS Bedrock, we need to use the server_model_id
    from the provider configuration instead of the id field.
    """
    try:
        # Get the Anthropic provider configuration
        provider_config = config_manager.get_provider_config("anthropic")
        if not provider_config:
            logger.warning(f"Anthropic provider configuration not found. Using model_id as-is: {model_id}")
            return model_id
        
        # Look for the model in the provider configuration
        models = provider_config.get("models", [])
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_id:
                # Look for AWS Bedrock server configuration
                servers = model.get("servers", [])
                for server in servers:
                    if server.get("id") == "aws_bedrock":
                        bedrock_model_id = server.get("model_id")
                        if bedrock_model_id:
                            logger.debug(f"Mapped model_id '{model_id}' to AWS Bedrock model_id '{bedrock_model_id}'")
                            return bedrock_model_id
                        break
                
                logger.warning(f"Model '{model_id}' found in config but missing AWS Bedrock server model_id. Using model_id as-is.")
                return model_id
        
        logger.warning(f"Model '{model_id}' not found in Anthropic provider configuration. Using model_id as-is.")
        return model_id
        
    except Exception as e:
        logger.error(f"Error while mapping model_id '{model_id}' to AWS Bedrock model_id: {e}")
        return model_id


def _should_use_direct_api(model_id: str) -> bool:
    """
    Determine whether to use Anthropic's direct API or AWS Bedrock based on:
    1. Whether anthropic_api_key is available
    2. Whether the model's default_server is set to "anthropic"
    """
    try:
        # Check if we have the direct API client initialized
        if not _anthropic_direct_client:
            return False
            
        # Get the Anthropic provider configuration
        provider_config = config_manager.get_provider_config("anthropic")
        if not provider_config:
            logger.debug(f"No provider config found, defaulting to AWS Bedrock for model: {model_id}")
            return False
        
        # Look for the model in the provider configuration
        models = provider_config.get("models", [])
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_id:
                default_server = model.get("default_server")
                if default_server == "anthropic":
                    logger.debug(f"Model '{model_id}' configured to use Anthropic direct API")
                    return True
                else:
                    logger.debug(f"Model '{model_id}' configured to use server: {default_server}")
                    return False
        
        logger.debug(f"Model '{model_id}' not found in config, defaulting to AWS Bedrock")
        return False
        
    except Exception as e:
        logger.error(f"Error determining API choice for model '{model_id}': {e}")
        return False


async def initialize_anthropic_client(secrets_manager: SecretsManager):
    global _anthropic_client_initialized, AWS_REGION, _bedrock_runtime_client, _anthropic_direct_client
    if _anthropic_client_initialized:
        logger.debug("Anthropic client already initialized.")
        return

    try:
        logger.info("Attempting to initialize Anthropic client...")
        
        secret_path = "kv/data/providers/anthropic"
        
        # Option 1: Try to initialize Anthropic direct API
        anthropic_api_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="api_key")
        if anthropic_api_key:
            try:
                _anthropic_direct_client = anthropic.Anthropic(api_key=anthropic_api_key)
                logger.info("Anthropic direct API client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic direct API client: {e}")
                _anthropic_direct_client = None

        # Option 2: Initialize AWS Bedrock as fallback
        aws_access_key_id = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_access_key_id")
        aws_secret_access_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_secret_access_key")
        region = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_region")

        if not region:
            region = 'eu-central-1'
            logger.info(f"AWS region not found in secrets. Defaulting to '{region}'.")

        if all([aws_access_key_id, aws_secret_access_key]):
            try:
                AWS_REGION = region
                _bedrock_runtime_client = boto3.client(
                    'bedrock-runtime',
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=AWS_REGION
                )
                logger.info(f"Anthropic AWS Bedrock client initialized successfully for region '{AWS_REGION}'.")
            except Exception as e:
                logger.error(f"Failed to initialize AWS Bedrock client: {e}")
                _bedrock_runtime_client = None
        else:
            logger.warning("AWS credentials not found. AWS Bedrock will not be available.")

        # Check if at least one client was initialized
        if _anthropic_direct_client or _bedrock_runtime_client:
            _anthropic_client_initialized = True
            logger.info("Anthropic client initialization completed successfully.")
        else:
            logger.error("Failed to initialize any Anthropic client (neither direct API nor AWS Bedrock).")
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
    if not _anthropic_client_initialized:
        if secrets_manager:
            await initialize_anthropic_client(secrets_manager)
        else:
            error_msg = "SecretsManager not provided, and Anthropic client is not initialized."
            logger.error(f"[{task_id}] {error_msg}")
            if stream: raise ValueError(error_msg)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    if not _anthropic_client_initialized:
        error_msg = "Anthropic client initialization failed. Check logs for details."
        logger.error(f"[{task_id}] {error_msg}")
        if stream: raise ValueError(error_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    # Determine which API to use
    use_direct_api = _should_use_direct_api(model_id)
    
    if use_direct_api and _anthropic_direct_client:
        return await invoke_direct_api(
            task_id, model_id, messages, _anthropic_direct_client, 
            temperature, max_tokens, tools, tool_choice, stream
        )
    elif _bedrock_runtime_client:
        bedrock_model_id = _get_bedrock_model_id(model_id)
        return await invoke_bedrock_api(
            task_id, model_id, bedrock_model_id, messages, _bedrock_runtime_client,
            temperature, max_tokens, tools, tool_choice, stream
        )
    else:
        error_msg = "No available Anthropic client (neither direct API nor AWS Bedrock)."
        logger.error(f"[{task_id}] {error_msg}")
        if stream: raise ValueError(error_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)
