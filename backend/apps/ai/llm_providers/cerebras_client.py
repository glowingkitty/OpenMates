# backend/apps/ai/llm_providers/cerebras_client.py
# Low-level HTTP client for interacting with Cerebras Inference API.
# Cerebras provides an OpenAI-compatible API for fast inference.
#
# Health Check:
# - No dedicated /health endpoint available
# - Health checks use test LLM requests (minimal: "1+2?" with system prompt "Answer short")
# - Checked every 5 minutes via Celery Beat task

import logging
import json
import httpx
import asyncio
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import time

from .openai_shared import (
    UnifiedOpenAIResponse,
    ParsedOpenAIToolCall,
    OpenAIUsageMetadata,
    RawOpenAIChatCompletionResponse,
    _map_tools_to_openai_format,
    calculate_token_breakdown
)

logger = logging.getLogger(__name__)

# Cerebras API endpoint (OpenAI-compatible)
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"

# Default timeout for API calls (in seconds)
DEFAULT_TIMEOUT = 180.0

# Default headers (User-Agent is required by CloudFront)
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "OpenMates/1.0",
}


async def invoke_cerebras_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    api_key: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
    top_p: Optional[float] = None,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Invokes the Cerebras Inference API with the given parameters.
    
    Cerebras provides an OpenAI-compatible API endpoint for fast inference
    using their specialized hardware. See: https://inference-docs.cerebras.ai/
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID to use (e.g., "llama-4-scout-17b-16e-instruct")
        messages: List of message objects with role and content
        api_key: Cerebras API key
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
    log_prefix = f"[{task_id}] CerebrasClient:"
    logger.info(f"{log_prefix} Invoking Cerebras API with model '{model_id}'")
    
    # Prepare the request payload (OpenAI-compatible format)
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "stream": stream
    }
    
    # Add optional parameters if provided
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    
    if top_p is not None:
        payload["top_p"] = top_p
    
    # Add tools if provided (OpenAI-compatible format)
    # _map_tools_to_openai_format already sanitizes schemas (removes min/max for all providers)
    if tools:
        openai_tools = _map_tools_to_openai_format(tools)
        if openai_tools:
            payload["tools"] = openai_tools
            
            # Log tool definitions for debugging (Cerebras requires specific format)
            logger.info(f"{log_prefix} Adding {len(openai_tools)} tool(s) to request")
            for idx, tool in enumerate(openai_tools):
                tool_name = tool.get("function", {}).get("name", "unknown")
                tool_desc = tool.get("function", {}).get("description", "")
                tool_params = tool.get("function", {}).get("parameters", {})
                logger.info(
                    f"{log_prefix} Tool {idx + 1}: name='{tool_name}', "
                    f"description_length={len(tool_desc)}, "
                    f"parameters_type={tool_params.get('type', 'unknown')}, "
                    f"parameters_properties_count={len(tool_params.get('properties', {}))}"
                )
                # Log full tool definition at debug level
                logger.debug(f"{log_prefix} Tool {idx + 1} full definition: {json.dumps(tool, indent=2)}")
            
            if tool_choice:
                # Cerebras API expects literal strings: "none", "auto", or "required"
                # OR a ChoiceObject with {"type": "function", "function": {"name": "function_name"}}
                # For "required", use the string directly (simplest and most compatible)
                if tool_choice == "required":
                    payload["tool_choice"] = "required"
                elif tool_choice == "auto":
                    payload["tool_choice"] = "auto"
                elif tool_choice == "none":
                    payload["tool_choice"] = "none"
                else:
                    # For specific function selection, pass as-is (should be ChoiceObject format)
                    payload["tool_choice"] = tool_choice
            logger.info(f"{log_prefix} Tool choice: {payload.get('tool_choice', 'not set')}")
    
    # Prepare headers with API key
    headers = DEFAULT_HEADERS.copy()
    headers["Authorization"] = f"Bearer {api_key}"
    
    # Log the request (excluding sensitive information)
    sanitized_payload = payload.copy()
    # Remove sensitive data from logged payload
    if "messages" in sanitized_payload:
        # Log message count and roles, but not full content
        messages_summary = [
            {"role": msg.get("role"), "content_length": len(str(msg.get("content", "")))}
            for msg in sanitized_payload["messages"]
        ]
        sanitized_payload["messages"] = messages_summary
    
    logger.info(
        f"{log_prefix} Request payload: model={model_id}, messages_count={len(messages)}, "
        f"stream={stream}, temperature={temperature}, tools_count={len(payload.get('tools', []))}"
    )
    # Log full payload structure at debug level (without sensitive content)
    logger.debug(f"{log_prefix} Request payload structure: {json.dumps(sanitized_payload, indent=2)}")
    # Log actual tools payload at info level for debugging Cerebras 400 errors
    if "tools" in payload:
        logger.info(f"{log_prefix} Tools payload being sent to Cerebras...")
    
    try:
        if stream:
            return _stream_cerebras_response(task_id, model_id, payload, headers)
        else:
            return await _send_cerebras_request(task_id, model_id, payload, headers)
    except Exception as e:
        error_msg = f"Error invoking Cerebras API: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )


async def _send_cerebras_request(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str]
) -> UnifiedOpenAIResponse:
    """
    Sends a non-streaming request to the Cerebras API.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID being used
        payload: Request payload
        headers: Request headers
        
    Returns:
        A UnifiedOpenAIResponse object
    """
    log_prefix = f"[{task_id}] CerebrasClient:"
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                CEREBRAS_API_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT
            )
            
            # Check for HTTP errors
            response.raise_for_status()
            response_data = response.json()
            
            # Log response time
            elapsed_time = time.time() - start_time
            logger.info(f"{log_prefix} Request completed in {elapsed_time:.2f}s")
            
            # Extract the response content
            choices = response_data.get("choices", [])
            if not choices:
                return UnifiedOpenAIResponse(
                    task_id=task_id,
                    model_id=model_id,
                    success=False,
                    error_message="No choices returned in the response"
                )
            
            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content")
            
            # Extract usage information
            usage_data = response_data.get("usage", {})
            
            # Calculate token breakdown from input messages (estimate)
            messages = payload.get("messages", [])
            breakdown = calculate_token_breakdown(messages, model_id)
            
            usage = OpenAIUsageMetadata(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                user_input_tokens=breakdown.get("user_input_tokens"),
                system_prompt_tokens=breakdown.get("system_prompt_tokens")
            )
            
            # Handle tool calls if present
            tool_calls_made = None
            if "tool_calls" in message:
                tool_calls_made = []
                for tc in message.get("tool_calls", []):
                    if tc.get("type") == "function":
                        function_data = tc.get("function", {})
                        function_name = function_data.get("name") or ""
                        arguments_raw = function_data.get("arguments") or "{}"
                        
                        # Parse the function arguments
                        parsed_args = {}
                        parsing_error = None
                        try:
                            parsed_args = json.loads(arguments_raw)
                        except json.JSONDecodeError as e:
                            parsing_error = f"Failed to parse function arguments: {str(e)}"
                            logger.error(f"{log_prefix} {parsing_error}")
                        
                        tool_calls_made.append(ParsedOpenAIToolCall(
                            tool_call_id=tc.get("id", ""),
                            function_name=function_name,
                            function_arguments_raw=arguments_raw,
                            function_arguments_parsed=parsed_args,
                            parsing_error=parsing_error
                        ))
            
            # Create the raw response object
            raw_response = RawOpenAIChatCompletionResponse(
                text=content,
                tool_calls=message.get("tool_calls"),
                usage_metadata=usage
            )
            
            # Return the unified response
            return UnifiedOpenAIResponse(
                task_id=task_id,
                model_id=model_id,
                success=True,
                direct_message_content=content,
                tool_calls_made=tool_calls_made,
                raw_response=raw_response,
                usage=usage
            )
            
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
        logger.error(f"{log_prefix} {error_msg}")
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}")
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )


async def _stream_cerebras_response(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str]
) -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
    """
    Streams the response from the Cerebras API.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID being used
        payload: Request payload
        headers: Request headers
        
    Yields:
        Strings for content chunks, ParsedOpenAIToolCall objects for tool calls,
        or an OpenAIUsageMetadata object for usage information.
    """
    log_prefix = f"[{task_id}] CerebrasClient (Stream):"
    logger.info(f"{log_prefix} Starting stream request")
    
    # Ensure streaming is enabled in the payload
    payload["stream"] = True
    
    # Track usage across chunks
    cumulative_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
    }
    
    # Track tool calls across chunks
    tool_calls_buffer = {}
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                CEREBRAS_API_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT
            ) as response:
                # Check for HTTP errors before reading stream
                # If there's an error, we need to read the response body first
                if response.status_code >= 400:
                    # Read error response body - for error responses, read as bytes first
                    error_body = b""
                    try:
                        # Read the entire response body for error responses
                        async for chunk in response.aiter_bytes():
                            error_body += chunk
                            if len(error_body) > 10000:  # Limit error body size
                                break
                    except Exception as e:
                        logger.warning(f"{log_prefix} Error reading error response body: {e}")
                    
                    # Try to parse error JSON
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_text = error_body.decode('utf-8', errors='ignore').strip()
                        if error_text:
                            try:
                                error_detail = json.loads(error_text)
                                error_msg = error_detail.get('error', {}).get('message', error_detail.get('message', error_msg))
                            except json.JSONDecodeError:
                                # Not JSON, use raw text
                                error_msg = f"HTTP {response.status_code}: {error_text[:500]}"
                    except UnicodeDecodeError:
                        error_msg = f"HTTP {response.status_code}: {str(error_body[:500])}"
                    
                    # Log the full error details including the payload that caused it
                    logger.error(f"{log_prefix} Cerebras API error: {error_msg}")
                    logger.error(f"{log_prefix} Error response body: {error_text if 'error_text' in locals() else error_body[:500]}")
                    logger.debug(f"{log_prefix} Request payload that caused error: {json.dumps(payload, indent=2)}")
                    raise ValueError(f"HTTP error {response.status_code}: {error_msg}")
                
                # Stream successful response
                async for line in response.aiter_lines():
                    # Skip empty lines
                    if not line.strip():
                        continue
                    
                    # Skip SSE comment lines (keep-alive heartbeats)
                    if line.startswith(":"):
                        continue
                    
                    # Handle SSE data lines
                    if line.startswith("data: "):
                        line = line[6:]  # Remove "data: " prefix
                    else:
                        # Skip lines that don't follow SSE format (not data: or comment)
                        continue
                    
                    # Check for stream termination
                    if line.strip() == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(line)
                        
                        # Extract content from the chunk
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        
                        # Handle content chunks
                        if "content" in delta and delta["content"]:
                            yield delta["content"]
                        
                        # Handle tool calls - accumulate them in the buffer
                        if "tool_calls" in delta:
                            for tc_delta in delta["tool_calls"]:
                                tc_id = tc_delta.get("id", "")
                                tc_index = tc_delta.get("index", 0)
                                
                                # Initialize or update the tool call in the buffer
                                if tc_id not in tool_calls_buffer:
                                    tool_calls_buffer[tc_id] = {
                                        "id": tc_id,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    }
                                
                                # Update function name if present (guard against None)
                                if "function" in tc_delta and "name" in tc_delta["function"] and tc_delta["function"]["name"]:
                                    tool_calls_buffer[tc_id]["function"]["name"] = tc_delta["function"]["name"]
                                
                                # Update function arguments if present (accumulate across chunks, guard against None)
                                if "function" in tc_delta and "arguments" in tc_delta["function"] and tc_delta["function"]["arguments"]:
                                    tool_calls_buffer[tc_id]["function"]["arguments"] += tc_delta["function"]["arguments"]
                        
                        # Check for finish_reason and yield accumulated tool calls
                        # finish_reason is typically set on the final chunk, which may not have tool_calls in delta
                        finish_reason = choice.get("finish_reason")
                        if finish_reason == "tool_calls" and tool_calls_buffer:
                            # Yield all accumulated tool calls when finish_reason indicates tool_calls
                            for tc_id, tc in tool_calls_buffer.items():
                                function_name = tc["function"]["name"] or ""
                                arguments_raw = tc["function"]["arguments"] or ""
                                
                                # Parse the function arguments
                                parsed_args = {}
                                parsing_error = None
                                try:
                                    parsed_args = json.loads(arguments_raw)
                                except json.JSONDecodeError as e:
                                    parsing_error = f"Failed to parse function arguments: {str(e)}"
                                    logger.error(f"{log_prefix} {parsing_error}")
                                
                                yield ParsedOpenAIToolCall(
                                    tool_call_id=tc_id,
                                    function_name=function_name,
                                    function_arguments_raw=arguments_raw,
                                    function_arguments_parsed=parsed_args,
                                    parsing_error=parsing_error
                                )
                            
                            # Clear the buffer after yielding
                            tool_calls_buffer.clear()
                        
                        # Update usage if present
                        if "usage" in chunk:
                            usage_chunk = chunk["usage"]
                            cumulative_usage["input_tokens"] = usage_chunk.get("prompt_tokens", cumulative_usage["input_tokens"])
                            cumulative_usage["output_tokens"] = usage_chunk.get("completion_tokens", cumulative_usage["output_tokens"])
                            cumulative_usage["total_tokens"] = usage_chunk.get("total_tokens", cumulative_usage["total_tokens"])
                            
                            # Calculate token breakdown from input messages (estimate)
                            messages = payload.get("messages", [])
                            breakdown = calculate_token_breakdown(messages, model_id)
                            cumulative_usage["user_input_tokens"] = breakdown.get("user_input_tokens")
                            cumulative_usage["system_prompt_tokens"] = breakdown.get("system_prompt_tokens")
                    
                    except json.JSONDecodeError as e:
                        # Log with more context to help debug actual parsing issues
                        logger.warning(f"{log_prefix} Failed to parse SSE chunk as JSON: {str(e)}. Line content: {line[:100]}...")
                        continue
                
                # Yield final usage information
                yield OpenAIUsageMetadata(
                    input_tokens=cumulative_usage["input_tokens"],
                    output_tokens=cumulative_usage["output_tokens"],
                    total_tokens=cumulative_usage["total_tokens"],
                    user_input_tokens=cumulative_usage.get("user_input_tokens"),
                    system_prompt_tokens=cumulative_usage.get("system_prompt_tokens")
                )
                
                logger.info(f"{log_prefix} Stream completed")
                
    except httpx.HTTPStatusError as e:
        # This should not happen since we check status before reading stream
        # But handle it gracefully if it does
        error_msg = f"HTTP {e.response.status_code}"
        try:
            # Try to read error response (non-streaming responses can use .text)
            if hasattr(e.response, 'text'):
                error_text = e.response.text
                try:
                    error_detail = json.loads(error_text)
                    error_msg = error_detail.get('error', {}).get('message', error_msg)
                except json.JSONDecodeError:
                    error_msg = f"HTTP {e.response.status_code}: {error_text[:200]}"
        except Exception as read_error:
            logger.warning(f"{log_prefix} Could not read error response body: {read_error}")
        
        logger.error(f"{log_prefix} Cerebras API error: {error_msg}")
        # Raise ValueError so the fallback logic can catch it and try the next server
        raise ValueError(f"HTTP error {e.response.status_code}: {error_msg}")
    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}")
        # Raise ValueError so the fallback logic can catch it
        raise ValueError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        # Raise ValueError so the fallback logic can catch it
        raise ValueError(error_msg)

