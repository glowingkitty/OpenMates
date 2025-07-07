# backend/apps/ai/llm_providers/anthropic_direct_api.py
# Direct API implementation for Anthropic Claude models

import logging
import json
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import tiktoken
import anthropic

from .anthropic_shared import (
    AnthropicUsageMetadata, 
    ParsedAnthropicToolCall, 
    UnifiedAnthropicResponse,
    RawAnthropicChatCompletionResponse,
    _prepare_messages_for_anthropic,
    _map_tools_to_anthropic_format
)

logger = logging.getLogger(__name__)


async def invoke_direct_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    anthropic_client: anthropic.Anthropic,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedAnthropicResponse, AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]]:
    """Handle requests using Anthropic's direct API"""
    log_prefix = f"[{task_id}] Anthropic Direct API ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        system_prompt, anthropic_messages = _prepare_messages_for_anthropic(messages)
        
        if not anthropic_messages:
            err_msg = "Message history is empty after processing."
            if stream: raise ValueError(err_msg)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

        anthropic_tools = _map_tools_to_anthropic_format(tools)
        
        # Prepare the request for direct API
        request_kwargs = {
            "model": model_id,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096
        }
        
        if system_prompt:
            request_kwargs["system"] = system_prompt
            
        if anthropic_tools:
            request_kwargs["tools"] = anthropic_tools
            if tool_choice and tool_choice != "auto":
                if tool_choice == "required":
                    request_kwargs["tool_choice"] = {"type": "any"}
                elif tool_choice == "none":
                    request_kwargs["tool_choice"] = {"type": "auto"}

        logger.debug(f"{log_prefix} Request prepared with caching optimizations.")

        if stream:
            return _iterate_direct_api_stream(task_id, model_id, request_kwargs, anthropic_client, messages, log_prefix)
        else:
            return await _process_direct_api_response(task_id, model_id, request_kwargs, anthropic_client, log_prefix)

    except Exception as e:
        err_msg = f"Error during direct API request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream: raise ValueError(err_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)


async def _process_direct_api_response(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    anthropic_client: anthropic.Anthropic,
    log_prefix: str
) -> UnifiedAnthropicResponse:
    """Process non-streaming response from Anthropic direct API"""
    try:
        response = anthropic_client.messages.create(**request_kwargs)
        logger.info(f"{log_prefix} Received non-streamed response from Anthropic direct API.")
        
        # Parse direct API response
        usage_metadata = AnthropicUsageMetadata(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            cache_creation_input_tokens=getattr(response.usage, 'cache_creation_input_tokens', 0),
            cache_read_input_tokens=getattr(response.usage, 'cache_read_input_tokens', 0)
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
        
        for block in response.content:
            if block.type == "text":
                text_content.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
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
        logger.error(f"{log_prefix} Failed to process direct API response: {e}", exc_info=True)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))


async def _iterate_direct_api_stream(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    anthropic_client: anthropic.Anthropic,
    messages: List[Dict[str, str]],
    log_prefix: str
) -> AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]:
    """Handle streaming response from Anthropic direct API"""
    logger.info(f"{log_prefix} Stream connection initiated.")
    
    output_buffer = ""
    usage = None
    current_tool_calls = {}
    
    try:
        request_kwargs["stream"] = True
        stream = anthropic_client.messages.create(**request_kwargs)
        
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    text_chunk = event.delta.text
                    output_buffer += text_chunk
                    yield text_chunk
            
            elif event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    tool_id = event.content_block.id
                    tool_name = event.content_block.name
                    current_tool_calls[tool_id] = {
                        "id": tool_id,
                        "name": tool_name,
                        "input": event.content_block.input
                    }
            
            elif event.type == "content_block_stop":
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
            
            elif event.type == "message_delta":
                if hasattr(event.delta, 'usage'):
                    usage_data = event.delta.usage
                    usage = AnthropicUsageMetadata(
                        input_tokens=usage_data.input_tokens,
                        output_tokens=usage_data.output_tokens,
                        total_tokens=usage_data.input_tokens + usage_data.output_tokens,
                        cache_creation_input_tokens=getattr(usage_data, 'cache_creation_input_tokens', 0),
                        cache_read_input_tokens=getattr(usage_data, 'cache_read_input_tokens', 0)
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

    except Exception as e_stream:
        err_msg = f"Unexpected error during direct API streaming: {e_stream}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        raise IOError(f"Anthropic Direct API Streaming Error: {e_stream}") from e_stream
