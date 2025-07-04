# backend/apps/ai/llm_providers/anthropic_client.py
# Client for interacting with Anthropic Claude models via AWS Bedrock.

import logging
import json
import os
import uuid
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import boto3
from botocore.exceptions import ClientError, BotoCoreError
import tiktoken
from pydantic import BaseModel, Field

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager

logger = logging.getLogger(__name__)

# --- Global State ---
AWS_REGION: Optional[str] = None
_anthropic_client_initialized = False
_bedrock_runtime_client: Optional[boto3.client] = None

# Caching configuration
CACHE_TOKEN_THRESHOLD = 1024  # Minimum tokens required for caching
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate for token counting

# --- Pydantic Models for Structured Anthropic Response ---

class AnthropicUsageMetadata(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_creation_input_tokens: Optional[int] = 0
    cache_read_input_tokens: Optional[int] = 0

class RawAnthropicChatCompletionResponse(BaseModel):
    text: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage_metadata: Optional[AnthropicUsageMetadata] = None

class ParsedAnthropicToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Dict[str, Any]
    parsing_error: Optional[str] = None

class UnifiedAnthropicResponse(BaseModel):
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedAnthropicToolCall]] = None
    raw_response: Optional[RawAnthropicChatCompletionResponse] = None
    usage: Optional[AnthropicUsageMetadata] = None


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
                server_model_id = model.get("server_model_id")
                if server_model_id:
                    logger.debug(f"Mapped model_id '{model_id}' to server_model_id '{server_model_id}' for AWS Bedrock")
                    return server_model_id
                else:
                    logger.warning(f"Model '{model_id}' found in config but missing server_model_id. Using model_id as-is.")
                    return model_id
        
        logger.warning(f"Model '{model_id}' not found in Anthropic provider configuration. Using model_id as-is.")
        return model_id
        
    except Exception as e:
        logger.error(f"Error while mapping model_id '{model_id}' to server_model_id: {e}")
        return model_id


async def initialize_anthropic_client(secrets_manager: SecretsManager):
    global _anthropic_client_initialized, AWS_REGION, _bedrock_runtime_client
    if _anthropic_client_initialized:
        logger.debug("Anthropic AWS Bedrock client already initialized.")
        return

    try:
        logger.info("Attempting to initialize Anthropic AWS Bedrock client...")
        
        secret_path = "kv/data/providers/anthropic"
        aws_access_key_id = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_access_key_id")
        aws_secret_access_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_secret_access_key")
        region = await secrets_manager.get_secret(secret_path=secret_path, secret_key="aws_region")

        if not region:
            region = 'eu-central-1'
            logger.info(f"AWS region not found in secrets. Defaulting to '{region}'.")

        if not all([aws_access_key_id, aws_secret_access_key]):
            logger.error(f"AWS credentials (aws_access_key_id, aws_secret_access_key) not found at '{secret_path}'. Initialization failed.")
            return
        
        AWS_REGION = region

        # Initialize AWS Bedrock Runtime client
        _bedrock_runtime_client = boto3.client(
            'bedrock-runtime',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=AWS_REGION
        )

        _anthropic_client_initialized = True
        logger.info(f"Anthropic AWS Bedrock client initialized successfully for region '{AWS_REGION}'.")

    except Exception as e:
        logger.error(f"Error during Anthropic AWS Bedrock client initialization: {e}", exc_info=True)
        _anthropic_client_initialized = False


def _should_cache_content(content: str) -> bool:
    """Determine if content should be cached based on token threshold"""
    if not content:
        return False
    
    # Conservative estimation: ~4 chars per token
    estimated_tokens = len(content) / CHARS_PER_TOKEN_ESTIMATE
    return estimated_tokens >= CACHE_TOKEN_THRESHOLD


def _map_tools_to_anthropic_format(tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    
    anthropic_tools = []
    for tool_def in tools:
        if tool_def.get("type") == "function":
            func = tool_def.get("function", {})
            anthropic_tools.append({
                "name": func.get("name"),
                "description": func.get("description"),
                "input_schema": func.get("parameters", {})
            })
    
    return anthropic_tools if anthropic_tools else None


def _prepare_system_with_caching(system_prompt: str) -> Union[str, List[Dict[str, Any]]]:
    """Prepare system prompt with caching if it meets threshold"""
    if not system_prompt:
        return system_prompt
    
    if _should_cache_content(system_prompt):
        logger.debug(f"System prompt ({len(system_prompt)} chars) will be cached.")
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]
    else:
        logger.debug(f"System prompt ({len(system_prompt)} chars) too short for caching.")
        return system_prompt


def _prepare_messages_with_caching(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Prepare messages with selective caching for content over threshold"""
    anthropic_messages = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Handle tool responses - convert to user message with tool result
        if role == "tool":
            anthropic_messages.append({
                "role": "user",
                "content": f"Tool result: {content}"
            })
            continue
        
        # Apply selective caching based on content length
        if _should_cache_content(content):
            logger.debug(f"Message from {role} ({len(content)} chars) will be cached.")
            anthropic_messages.append({
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            })
        else:
            logger.debug(f"Message from {role} ({len(content)} chars) too short for caching.")
            anthropic_messages.append({
                "role": role,
                "content": content
            })
            
    return anthropic_messages


def _prepare_messages_for_anthropic(messages: List[Dict[str, str]]) -> (Optional[Union[str, List[Dict[str, Any]]]], List[Dict[str, Any]]):
    """Prepare messages for Anthropic API with caching support"""
    system_prompt = None
    processed_messages = list(messages)
    
    # Extract system prompt if present
    if processed_messages and processed_messages[0].get("role") == "system":
        system_prompt_content = processed_messages.pop(0)["content"]
        system_prompt = _prepare_system_with_caching(system_prompt_content)

    # Process remaining messages with selective caching
    anthropic_messages = _prepare_messages_with_caching(processed_messages)
            
    return system_prompt, anthropic_messages


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

    if not _anthropic_client_initialized or not _bedrock_runtime_client:
        error_msg = "Anthropic AWS Bedrock client initialization failed. Check logs for details."
        logger.error(f"[{task_id}] {error_msg}")
        if stream: raise ValueError(error_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    # Convert model_id to the appropriate AWS Bedrock model ID
    bedrock_model_id = _get_bedrock_model_id(model_id)

    log_prefix = f"[{task_id}] Anthropic Client ({model_id} -> {bedrock_model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        system_prompt, anthropic_messages = _prepare_messages_for_anthropic(messages)
        
        if not anthropic_messages:
            err_msg = "Message history is empty after processing."
            if stream: raise ValueError(err_msg)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

        anthropic_tools = _map_tools_to_anthropic_format(tools)
        
        # Prepare the request body for AWS Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096
        }
        
        if system_prompt:
            request_body["system"] = system_prompt
            
        if anthropic_tools:
            request_body["tools"] = anthropic_tools
            if tool_choice and tool_choice != "auto":
                if tool_choice == "required":
                    request_body["tool_choice"] = {"type": "any"}
                elif tool_choice == "none":
                    request_body["tool_choice"] = {"type": "auto"}

        logger.debug(f"{log_prefix} Request body prepared with caching optimizations.")

    except Exception as e:
        err_msg = f"Error during request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream: raise ValueError(err_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

    async def _process_non_stream_response(response_body: Dict[str, Any]) -> UnifiedAnthropicResponse:
        logger.info(f"{log_prefix} Received non-streamed response from AWS Bedrock.")
        
        try:
            # Parse AWS Bedrock response
            content = response_body.get("content", [])
            usage = response_body.get("usage", {})
            
            usage_metadata = AnthropicUsageMetadata(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage.get("cache_read_input_tokens", 0)
            )
            
            raw_response_pydantic = RawAnthropicChatCompletionResponse(
                usage_metadata=usage_metadata
            )

            unified_resp = UnifiedAnthropicResponse(
                task_id=task_id, model_id=model_id, success=True,
                raw_response=raw_response_pydantic, usage=usage_metadata
            )
            
            # Process content blocks
            text_content = []
            tool_calls = []
            
            for block in content:
                if block.get("type") == "text":
                    text_content.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input", {})
                    })
            
            if tool_calls:
                unified_resp.tool_calls_made = []
                for tc in tool_calls:
                    args_dict = tc["input"]
                    unified_resp.tool_calls_made.append(ParsedAnthropicToolCall(
                        tool_call_id=tc["id"],
                        function_name=tc["name"],
                        function_arguments_parsed=args_dict,
                        function_arguments_raw=json.dumps(args_dict)
                    ))
                logger.info(f"{log_prefix} Call resulted in {len(unified_resp.tool_calls_made)} tool call(s).")
            
            elif text_content:
                unified_resp.direct_message_content = "".join(text_content)
                raw_response_pydantic.text = unified_resp.direct_message_content
                logger.info(f"{log_prefix} Call resulted in a direct message response.")
            
            else:
                unified_resp.error_message = "Response has no text or tool calls."
                logger.warning(f"{log_prefix} {unified_resp.error_message}")

            # Log cache usage if present
            if usage_metadata.cache_read_input_tokens > 0:
                logger.info(f"{log_prefix} Cache hit: {usage_metadata.cache_read_input_tokens} tokens read from cache.")
            if usage_metadata.cache_creation_input_tokens > 0:
                logger.info(f"{log_prefix} Cache write: {usage_metadata.cache_creation_input_tokens} tokens written to cache.")
                
            return unified_resp
            
        except Exception as e:
            logger.error(f"{log_prefix} Failed to parse non-streamed response: {e}", exc_info=True)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))

    async def _iterate_stream_response() -> AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]:
        logger.info(f"{log_prefix} Stream connection initiated.")
        
        output_buffer = ""
        usage = None
        current_tool_calls = {}
        
        try:
            response = _bedrock_runtime_client.invoke_model_with_response_stream(
                modelId=bedrock_model_id,
                body=json.dumps(request_body)
            )
            
            stream = response.get('body')
            if stream:
                for event in stream:
                    chunk = event.get('chunk')
                    if chunk:
                        chunk_data = json.loads(chunk.get('bytes').decode())
                        
                        if chunk_data.get("type") == "content_block_delta":
                            delta = chunk_data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text_chunk = delta.get("text", "")
                                output_buffer += text_chunk
                                yield text_chunk
                        
                        elif chunk_data.get("type") == "content_block_start":
                            content_block = chunk_data.get("content_block", {})
                            if content_block.get("type") == "tool_use":
                                tool_id = content_block.get("id")
                                tool_name = content_block.get("name")
                                current_tool_calls[tool_id] = {
                                    "id": tool_id,
                                    "name": tool_name,
                                    "input": content_block.get("input", {})
                                }
                        
                        elif chunk_data.get("type") == "content_block_stop":
                            # Tool call completed
                            for tool_call in current_tool_calls.values():
                                args_dict = tool_call["input"]
                                parsed_tool_call = ParsedAnthropicToolCall(
                                    tool_call_id=tool_call["id"],
                                    function_name=tool_call["name"],
                                    function_arguments_parsed=args_dict,
                                    function_arguments_raw=json.dumps(args_dict)
                                )
                                logger.info(f"{log_prefix} Yielding a tool call from stream: {tool_call['name']}")
                                yield parsed_tool_call
                            current_tool_calls.clear()
                        
                        elif chunk_data.get("type") == "message_delta":
                            delta = chunk_data.get("delta", {})
                            if "usage" in delta:
                                usage_data = delta["usage"]
                                usage = AnthropicUsageMetadata(
                                    input_tokens=usage_data.get("input_tokens", 0),
                                    output_tokens=usage_data.get("output_tokens", 0),
                                    total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
                                    cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
                                    cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0)
                                )

            # Yield final usage information
            if usage:
                if usage.cache_read_input_tokens > 0:
                    logger.info(f"{log_prefix} Stream cache hit: {usage.cache_read_input_tokens} tokens read from cache.")
                if usage.cache_creation_input_tokens > 0:
                    logger.info(f"{log_prefix} Stream cache write: {usage.cache_creation_input_tokens} tokens written to cache.")
                yield usage
            else:
                # Estimate usage if not provided
                logger.warning(f"{log_prefix} Stream finished without usage data. Estimating tokens with tiktoken.")
                try:
                    encoding = tiktoken.get_encoding("cl100k_base")
                    # Estimate input tokens from messages
                    input_text = ""
                    for msg in messages:
                        input_text += msg.get("content", "")
                    estimated_input_tokens = len(encoding.encode(input_text))
                    estimated_output_tokens = len(encoding.encode(output_buffer))
                    
                    usage = AnthropicUsageMetadata(
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0
                    )
                    yield usage
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to estimate tokens with tiktoken: {e}", exc_info=True)

            logger.info(f"{log_prefix} Stream finished.")

        except ClientError as e:
            err_msg = f"AWS Bedrock error during streaming: {e}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"AWS Bedrock Error: {e}") from e
        except Exception as e_stream:
            err_msg = f"Unexpected error during streaming: {e_stream}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Anthropic Streaming Error: {e_stream}") from e_stream

    if stream:
        return _iterate_stream_response()
    else:
        try:
            response = _bedrock_runtime_client.invoke_model(
                modelId=bedrock_model_id,
                body=json.dumps(request_body)
            )
            response_body = json.loads(response.get('body').read())
            return await _process_non_stream_response(response_body)
        except ClientError as e_api:
            err_msg = f"AWS Bedrock error calling API: {e_api}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e_api))
        except Exception as e_gen:
            err_msg = f"Unexpected error during API call: {e_gen}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e_gen))
