# backend/apps/ai/llm_providers/anthropic_bedrock.py
# AWS Bedrock implementation for Anthropic Claude models

import logging
import json
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import boto3
from botocore.exceptions import ClientError
import tiktoken

from .anthropic_shared import (
    AnthropicUsageMetadata, 
    ParsedAnthropicToolCall, 
    UnifiedAnthropicResponse,
    RawAnthropicChatCompletionResponse,
    _prepare_messages_for_anthropic,
    _map_tools_to_anthropic_format
)

logger = logging.getLogger(__name__)


async def invoke_bedrock_api(
    task_id: str,
    model_id: str,
    bedrock_model_id: str,
    messages: List[Dict[str, str]],
    bedrock_client: boto3.client,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedAnthropicResponse, AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]]:
    """Handle requests using AWS Bedrock"""
    log_prefix = f"[{task_id}] Anthropic AWS Bedrock ({model_id} -> {bedrock_model_id}):"
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

        if stream:
            return _iterate_bedrock_stream_response(task_id, model_id, bedrock_model_id, request_body, bedrock_client, messages, log_prefix)
        else:
            return await _process_bedrock_non_stream_response(task_id, model_id, bedrock_model_id, request_body, bedrock_client, log_prefix)

    except Exception as e:
        err_msg = f"Error during AWS Bedrock request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream: raise ValueError(err_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)


async def _process_bedrock_non_stream_response(
    task_id: str,
    model_id: str,
    bedrock_model_id: str,
    request_body: Dict[str, Any],
    bedrock_client: boto3.client,
    log_prefix: str
) -> UnifiedAnthropicResponse:
    """Process non-streaming response from AWS Bedrock"""
    try:
        response = bedrock_client.invoke_model(
            modelId=bedrock_model_id,
            body=json.dumps(request_body)
        )
        response_body = json.loads(response.get('body').read())
        logger.info(f"{log_prefix} Received non-streamed response from AWS Bedrock.")
        
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
        
    except ClientError as e_api:
        err_msg = f"AWS Bedrock error calling API: {e_api}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e_api))
    except Exception as e:
        logger.error(f"{log_prefix} Failed to parse AWS Bedrock non-streamed response: {e}", exc_info=True)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))


async def _iterate_bedrock_stream_response(
    task_id: str,
    model_id: str,
    bedrock_model_id: str,
    request_body: Dict[str, Any],
    bedrock_client: boto3.client,
    messages: List[Dict[str, str]],
    log_prefix: str
) -> AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]:
    """Handle streaming response from AWS Bedrock"""
    logger.info(f"{log_prefix} Stream connection initiated.")
    
    output_buffer = ""
    usage = None
    current_tool_calls = {}
    
    try:
        response = bedrock_client.invoke_model_with_response_stream(
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
        err_msg = f"Unexpected error during AWS Bedrock streaming: {e_stream}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        raise IOError(f"Anthropic AWS Bedrock Streaming Error: {e_stream}") from e_stream
