# backend/apps/ai/llm_providers/openrouter_client.py
# Low-level HTTP client for interacting with OpenRouter API.

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
    calculate_token_breakdown,
)

logger = logging.getLogger(__name__)

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default timeout for API calls (in seconds)
DEFAULT_TIMEOUT = 180.0

# Default headers
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    # Optional analytics headers can be added here
    "HTTP-Referer": "https://openmates.org",
    "X-Title": "OpenMates",
}


async def invoke_openrouter_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    api_key: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
    provider_overrides: Optional[Dict[str, Any]] = None
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Invokes the OpenRouter API with the given parameters.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID to use (e.g., "openai/gpt-oss-120b")
        messages: List of message objects with role and content
        api_key: OpenRouter API key
        temperature: Sampling temperature (default: 0.7)
        max_tokens: Maximum number of tokens to generate (default: None)
        tools: List of tool definitions (default: None)
        tool_choice: Tool choice strategy (default: None)
        stream: Whether to stream the response (default: False)
        provider_overrides: Provider-specific overrides (default: None)
        
    Returns:
        If stream=False, returns a UnifiedOpenAIResponse object.
        If stream=True, returns an AsyncIterator that yields strings, ParsedOpenAIToolCall objects,
        or an OpenAIUsageMetadata object.
    """
    log_prefix = f"[{task_id}] OpenRouterClient:"
    logger.info(f"{log_prefix} Invoking OpenRouter API with model '{model_id}'")
    
    # Prepare the request payload
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "stream": stream
    }
    
    # Add optional parameters if provided
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    
    if tools:
        openrouter_tools = _map_tools_to_openai_format(tools)
        if openrouter_tools:
            payload["tools"] = openrouter_tools
            
            if tool_choice:
                if tool_choice == "required":
                    # For "required", we want to force tool usage
                    # If we have exactly one tool, use its function name to force that specific tool
                    # This is compatible with Groq and other strict providers
                    if len(openrouter_tools) == 1 and "function" in openrouter_tools[0]:
                        function_name = openrouter_tools[0]["function"].get("name")
                        if function_name:
                            payload["tool_choice"] = {
                                "type": "function",
                                "function": {"name": function_name}
                            }
                        else:
                            # Fallback to "auto" if function name not found
                            logger.warning(f"{log_prefix} tool_choice='required' but function name not found in tool definition, using 'auto'")
                            payload["tool_choice"] = "auto"
                    else:
                        # Multiple tools or invalid format - use "auto" to let model decide
                        # This is compatible with all providers including Groq
                        payload["tool_choice"] = "auto"
                elif tool_choice == "auto":
                    payload["tool_choice"] = "auto"
                elif tool_choice == "none":
                    payload["tool_choice"] = "none"
                elif isinstance(tool_choice, dict):
                    # If it's already a dict (e.g., {"type": "function", "function": {"name": "..."}}), use it as-is
                    payload["tool_choice"] = tool_choice
                else:
                    # For any other string value, pass it through (should be "auto" or "none")
                    payload["tool_choice"] = tool_choice
    
    # Add provider overrides if specified
    if provider_overrides:
        payload["provider"] = provider_overrides
    
    # Prepare headers with API key
    headers = DEFAULT_HEADERS.copy()
    headers["Authorization"] = f"Bearer {api_key}"
    
    # Log the request (excluding sensitive information)
    sanitized_payload = payload.copy()
    logger.debug(f"{log_prefix} Request payload: {json.dumps(sanitized_payload)}")
    
    try:
        if stream:
            return _stream_openrouter_response(task_id, model_id, payload, headers)
        else:
            return await _send_openrouter_request(task_id, model_id, payload, headers)
    except Exception as e:
        error_msg = f"Error invoking OpenRouter API: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=False,
            error_message=error_msg
        )


async def _send_openrouter_request(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str]
) -> UnifiedOpenAIResponse:
    """
    Sends a non-streaming request to the OpenRouter API.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID being used
        payload: Request payload
        headers: Request headers
        
    Returns:
        A UnifiedOpenAIResponse object
    """
    log_prefix = f"[{task_id}] OpenRouterClient:"
    start_time = time.time()
    
    try:
        # Log the actual request URL and model for debugging
        logger.info(f"{log_prefix} Making request to {OPENROUTER_API_URL} with model '{model_id}'")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT
            )
            
            # Log response status for debugging
            logger.info(f"{log_prefix} Received response: HTTP {response.status_code} from {OPENROUTER_API_URL}")
            
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
            
            # Get breakdown from input messages (estimate)
            messages = payload.get("messages", [])
            # Include tools in the breakdown estimate to ensure system_prompt_tokens matches prompt_tokens
            breakdown = calculate_token_breakdown(messages, model_id, tools=payload.get("tools"))
            
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
                        function_name = function_data.get("name", "")
                        arguments_raw = function_data.get("arguments", "{}")
                        
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


async def _stream_openrouter_response(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str]
) -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
    """
    Streams the response from the OpenRouter API.
    
    Args:
        task_id: Unique identifier for the task
        model_id: The model ID being used
        payload: Request payload
        headers: Request headers
        
    Yields:
        Strings for content chunks, ParsedOpenAIToolCall objects for tool calls,
        or an OpenAIUsageMetadata object for usage information.
    """
    log_prefix = f"[{task_id}] OpenRouterClient (Stream):"
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
    
    # Calculate token breakdown from input messages (estimate)
    # Include tools in the breakdown estimate to ensure system_prompt_tokens matches prompt_tokens
    messages = payload.get("messages", [])
    token_breakdown = calculate_token_breakdown(messages, model_id, tools=payload.get("tools"))
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                OPENROUTER_API_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT
            ) as response:
                # Check for HTTP errors before reading stream
                # For error responses, we need to read the body first
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
                    
                    # Improve error message for 401 errors (API key issues)
                    if response.status_code == 401:
                        if "user not found" in error_msg.lower() or "unauthorized" in error_msg.lower():
                            logger.error(
                                f"{log_prefix} OpenRouter API authentication failed (401). "
                                f"This usually means the OpenRouter API key is missing or invalid. "
                                f"Please check Vault configuration at 'kv/data/providers/openrouter' with key 'api_key'. "
                                f"Original error: {error_msg}"
                            )
                            error_msg = "OpenRouter API key is missing or invalid. Please configure the API key in Vault."
                        else:
                            logger.error(f"{log_prefix} OpenRouter API authentication error (401): {error_msg}")
                    else:
                        logger.error(f"{log_prefix} OpenRouter API error: {error_msg}")
                    
                    yield f"[ERROR: HTTP error {response.status_code}: {error_msg}]"
                    return
                
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
                        
                        # Handle tool calls
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
                                
                                # Update function name if present
                                if "function" in tc_delta and "name" in tc_delta["function"]:
                                    tool_calls_buffer[tc_id]["function"]["name"] = tc_delta["function"]["name"]
                                
                                # Update function arguments if present
                                if "function" in tc_delta and "arguments" in tc_delta["function"]:
                                    tool_calls_buffer[tc_id]["function"]["arguments"] += tc_delta["function"]["arguments"]
                                
                                # If this is the last chunk for this tool call, yield it
                                if choice.get("finish_reason") == "tool_calls":
                                    tc = tool_calls_buffer[tc_id]
                                    function_name = tc["function"]["name"]
                                    arguments_raw = tc["function"]["arguments"]
                                    
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
                        
                        # Update usage if present
                        if "usage" in chunk:
                            usage = chunk["usage"]
                            cumulative_usage["input_tokens"] = usage.get("prompt_tokens", cumulative_usage["input_tokens"])
                            cumulative_usage["output_tokens"] = usage.get("completion_tokens", cumulative_usage["output_tokens"])
                            cumulative_usage["total_tokens"] = usage.get("total_tokens", cumulative_usage["total_tokens"])
                    
                    except json.JSONDecodeError as e:
                        # Log with more context to help debug actual parsing issues
                        logger.warning(f"{log_prefix} Failed to parse SSE chunk as JSON: {str(e)}. Line content: {line[:100]}...")
                        continue
                
                # Yield final usage information
                yield OpenAIUsageMetadata(
                    input_tokens=cumulative_usage["input_tokens"],
                    output_tokens=cumulative_usage["output_tokens"],
                    total_tokens=cumulative_usage["total_tokens"],
                    user_input_tokens=token_breakdown.get("user_input_tokens"),
                    system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
                )
                
                logger.info(f"{log_prefix} Stream completed")
                
    except httpx.HTTPStatusError as e:
        # For streaming responses that weren't caught above, try to read error body
        # This handles cases where the exception is raised before we check status_code
        try:
            # Try to read the response body if available
            if hasattr(e.response, 'aread'):
                error_body = await e.response.aread()
                error_text = error_body.decode('utf-8', errors='ignore')
            elif hasattr(e.response, 'text'):
                error_text = e.response.text
            else:
                error_text = str(e)
        except Exception:
            error_text = f"Unable to read error response: {str(e)}"
        error_msg = f"HTTP error {e.response.status_code}: {error_text[:500]}"
        logger.error(f"{log_prefix} {error_msg}")
        yield f"[ERROR: {error_msg}]"
    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}")
        yield f"[ERROR: {error_msg}]"
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        yield f"[ERROR: {error_msg}]"