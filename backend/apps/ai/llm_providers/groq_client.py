# backend/apps/ai/llm_providers/groq_client.py
# Client for interacting with Groq AI models via direct API.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import json

from backend.core.api.app.utils.secrets_manager import SecretsManager
from .openai_shared import (
    UnifiedOpenAIResponse,
    ParsedOpenAIToolCall,
    OpenAIUsageMetadata,
    RawOpenAIChatCompletionResponse,
    _map_tools_to_openai_format,
    calculate_token_breakdown,
)

logger = logging.getLogger(__name__)

# Try to import AsyncGroq from groq SDK
try:
    from groq import AsyncGroq  # type: ignore
except Exception:  # pragma: no cover
    AsyncGroq = None  # type: ignore

# Global state for Groq client
_groq_client_initialized: bool = False
_groq_direct_client: Optional["AsyncGroq"] = None
_groq_api_key: Optional[str] = None

# Groq API base URL (default, can be overridden)
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"


async def initialize_groq_client(secrets_manager: SecretsManager) -> None:
    """
    Initialize AsyncGroq client from Vault secrets.
    
    Args:
        secrets_manager: SecretsManager instance for accessing Vault
    """
    global _groq_client_initialized, _groq_direct_client, _groq_api_key

    if _groq_client_initialized:
        logger.debug("Groq client already initialized.")
        return

    if AsyncGroq is None:
        logger.error("Groq SDK missing; install 'groq' package.")
        _groq_client_initialized = False
        return

    secret_path = "kv/data/providers/groq"
    try:
        _groq_api_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="api_key")
        base_url = await secrets_manager.get_secret(secret_path=secret_path, secret_key="base_url")

        if not _groq_api_key:
            logger.error("Groq API key not found in Vault; direct API disabled.")
            _groq_client_initialized = False
            return

        # Initialize AsyncGroq client
        # Groq SDK uses base_url parameter, but defaults to their API
        _groq_direct_client = AsyncGroq(
            api_key=_groq_api_key,
            base_url=base_url or None,  # Use custom base_url if provided, otherwise use Groq default
        )
        _groq_client_initialized = True
        logger.info("Groq direct client initialized successfully.")
    except Exception as exc:
        logger.error("Failed to initialize Groq client: %s", exc, exc_info=True)
        _groq_client_initialized = False
        _groq_direct_client = None


def _parse_tool_calls_from_choice(choice: Dict[str, Any]) -> Optional[List[ParsedOpenAIToolCall]]:
    """
    Parse tool calls from a Groq API response choice.
    
    Groq uses OpenAI-compatible format, so this follows the same pattern as OpenAI.
    
    Args:
        choice: The choice object from Groq API response
        
    Returns:
        List of parsed tool calls, or None if no tool calls
    """
    message = choice.get("message", {})
    tool_calls = message.get("tool_calls")
    
    if not tool_calls:
        return None
    
    parsed_calls = []
    for tc in tool_calls:
        function_data = tc.get("function", {})
        function_name = function_data.get("name", "")
        function_args_raw = function_data.get("arguments", "{}")
        
        # Parse JSON arguments
        function_args_parsed = {}
        parsing_error = None
        try:
            function_args_parsed = json.loads(function_args_raw)
        except json.JSONDecodeError as e:
            parsing_error = f"JSONDecodeError: {e}"
            logger.warning(f"Failed to parse tool call arguments: {function_args_raw}")
        
        parsed_calls.append(ParsedOpenAIToolCall(
            tool_call_id=tc.get("id", ""),
            function_name=function_name,
            function_arguments_raw=function_args_raw,
            function_arguments_parsed=function_args_parsed,
            parsing_error=parsing_error
        ))
    
    return parsed_calls if parsed_calls else None


async def _invoke_groq_direct_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Invoke Groq API directly using AsyncGroq SDK.
    
    Args:
        task_id: Unique identifier for this task
        model_id: Model identifier (e.g., "openai/gpt-oss-20b")
        messages: List of message dicts with "role" and "content"
        temperature: Sampling temperature (0.0 to 2.0)
        max_tokens: Maximum tokens to generate
        tools: List of tool definitions (OpenAI format)
        tool_choice: Tool choice strategy ("auto", "none", "required", or specific tool)
        stream: Whether to stream the response
        
    Returns:
        UnifiedOpenAIResponse for non-streaming, or AsyncIterator for streaming
    """
    if not _groq_direct_client:
        error_msg = "Groq client not initialized"
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    log_prefix = f"[{task_id}] Groq Client ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Tool choice: {tool_choice}")

    try:
        # Prepare request parameters
        request_params: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        
        if max_tokens is not None:
            request_params["max_tokens"] = max_tokens
        
        # Handle tools and tool_choice
        if tools:
            # Map tools to OpenAI format (Groq uses OpenAI-compatible format)
            mapped_tools = _map_tools_to_openai_format(tools)
            if mapped_tools:
                request_params["tools"] = mapped_tools
                
                # Handle tool_choice parameter
                # Groq supports: "auto", "none", "required", or {"type": "function", "function": {"name": "function_name"}}
                if tool_choice:
                    if tool_choice == "required":
                        # For "required", if there's exactly one tool, specify it explicitly
                        # Otherwise, use "auto" to let the model decide
                        if len(mapped_tools) == 1:
                            function_name = mapped_tools[0].get("function", {}).get("name")
                            if function_name:
                                request_params["tool_choice"] = {
                                    "type": "function",
                                    "function": {"name": function_name}
                                }
                            else:
                                request_params["tool_choice"] = "auto"
                        else:
                            request_params["tool_choice"] = "auto"
                    else:
                        # For "auto" or "none", pass as-is
                        request_params["tool_choice"] = tool_choice
                else:
                    request_params["tool_choice"] = "auto"

        logger.debug(f"{log_prefix} Request params: {json.dumps({k: v for k, v in request_params.items() if k != 'messages'}, indent=2)}")

        # Make API call
        if stream:
            # Streaming response
            async def _stream_response() -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
                try:
                    stream_response = await _groq_direct_client.chat.completions.create(**request_params)
                    
                    current_tool_call_id: Optional[str] = None
                    current_tool_function_name: Optional[str] = None
                    current_tool_function_args_buffer: str = ""
                    aggregated_content = ""
                    usage_info: Optional[Dict[str, int]] = None
                    
                    async for chunk in stream_response:
                        if not chunk.choices:
                            continue
                            
                        choice = chunk.choices[0]
                        delta = choice.delta if hasattr(choice, 'delta') else {}
                        
                        # Handle content deltas
                        if hasattr(delta, 'content') and delta.content:
                            content_chunk = delta.content
                            aggregated_content += content_chunk
                            yield content_chunk
                        
                        # Handle tool call deltas
                        if hasattr(delta, 'tool_calls') and delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                if hasattr(tc_delta, 'id') and tc_delta.id:
                                    # New tool call starting
                                    if current_tool_function_name and current_tool_call_id:
                                        # Finish previous tool call
                                        parsed_args, err_msg = None, None
                                        try:
                                            parsed_args = json.loads(current_tool_function_args_buffer)
                                        except json.JSONDecodeError as e:
                                            err_msg = f"JSONDecodeError: {e}"
                                        yield ParsedOpenAIToolCall(
                                            tool_call_id=current_tool_call_id,
                                            function_name=current_tool_function_name,
                                            function_arguments_raw=current_tool_function_args_buffer,
                                            function_arguments_parsed=parsed_args,
                                            parsing_error=err_msg
                                        )
                                    
                                    current_tool_call_id = tc_delta.id
                                    if hasattr(tc_delta, 'function'):
                                        current_tool_function_name = tc_delta.function.name if hasattr(tc_delta.function, 'name') else None
                                        current_tool_function_args_buffer = tc_delta.function.arguments if hasattr(tc_delta.function, 'arguments') else ""
                                elif hasattr(tc_delta, 'function') and current_tool_function_name:
                                    # Continue accumulating arguments
                                    if hasattr(tc_delta.function, 'arguments'):
                                        current_tool_function_args_buffer += tc_delta.function.arguments
                        
                        # Check for finish reason and finalize tool calls
                        if hasattr(choice, 'finish_reason') and choice.finish_reason == "tool_calls":
                            if current_tool_function_name and current_tool_call_id:
                                parsed_args, err_msg = None, None
                                try:
                                    parsed_args = json.loads(current_tool_function_args_buffer)
                                except json.JSONDecodeError as e:
                                    err_msg = f"JSONDecodeError: {e}"
                                yield ParsedOpenAIToolCall(
                                    tool_call_id=current_tool_call_id,
                                    function_name=current_tool_function_name,
                                    function_arguments_raw=current_tool_function_args_buffer,
                                    function_arguments_parsed=parsed_args,
                                    parsing_error=err_msg
                                )
                                current_tool_call_id = None
                                current_tool_function_name = None
                                current_tool_function_args_buffer = ""
                        
                        # Handle usage metadata (usually in final chunk)
                        if hasattr(chunk, 'usage') and chunk.usage:
                            # Calculate token breakdown from input messages (estimate)
                            breakdown = calculate_token_breakdown(messages, model_id)
                            usage_info = {
                                "prompt_tokens": chunk.usage.prompt_tokens if hasattr(chunk.usage, 'prompt_tokens') else 0,
                                "completion_tokens": chunk.usage.completion_tokens if hasattr(chunk.usage, 'completion_tokens') else 0,
                                "total_tokens": chunk.usage.total_tokens if hasattr(chunk.usage, 'total_tokens') else 0,
                                "user_input_tokens": breakdown.get("user_input_tokens"),
                                "system_prompt_tokens": breakdown.get("system_prompt_tokens")
                            }
                    
                    # Yield final usage metadata if available
                    if usage_info:
                        yield OpenAIUsageMetadata(
                            input_tokens=usage_info.get("prompt_tokens", 0),
                            output_tokens=usage_info.get("completion_tokens", 0),
                            total_tokens=usage_info.get("total_tokens", 0),
                            user_input_tokens=usage_info.get("user_input_tokens"),
                            system_prompt_tokens=usage_info.get("system_prompt_tokens")
                        )
                except Exception as e:
                    logger.error(f"{log_prefix} Error during streaming: {e}", exc_info=True)
                    raise
            
            return _stream_response()
        else:
            # Non-streaming response
            response = await _groq_direct_client.chat.completions.create(**request_params)
            
            # Parse response
            choice = response.choices[0] if response.choices else None
            if not choice:
                error_msg = "No choices in Groq API response"
                logger.error(f"{log_prefix} {error_msg}")
                return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)
            
            message = choice.message
            
            # Extract usage metadata
            usage_metadata = None
            if hasattr(response, 'usage') and response.usage:
                # Calculate token breakdown from input messages (estimate)
                breakdown = calculate_token_breakdown(messages, model_id)
                usage_metadata = OpenAIUsageMetadata(
                    input_tokens=response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 0,
                    output_tokens=response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 0,
                    total_tokens=response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0,
                    user_input_tokens=breakdown.get("user_input_tokens"),
                    system_prompt_tokens=breakdown.get("system_prompt_tokens")
                )
            
            # Check for tool calls
            tool_calls_made = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls_made = []
                for tc in message.tool_calls:
                    function_data = tc.function
                    function_args_raw = function_data.arguments if hasattr(function_data, 'arguments') else "{}"
                    
                    function_args_parsed = {}
                    parsing_error = None
                    try:
                        function_args_parsed = json.loads(function_args_raw)
                    except json.JSONDecodeError as e:
                        parsing_error = f"JSONDecodeError: {e}"
                    
                    tool_calls_made.append(ParsedOpenAIToolCall(
                        tool_call_id=tc.id if hasattr(tc, 'id') else "",
                        function_name=function_data.name if hasattr(function_data, 'name') else "",
                        function_arguments_raw=function_args_raw,
                        function_arguments_parsed=function_args_parsed,
                        parsing_error=parsing_error
                    ))
            
            # Extract direct message content
            direct_message_content = None
            if hasattr(message, 'content') and message.content:
                direct_message_content = message.content
            
            # Build unified response
            raw_response = RawOpenAIChatCompletionResponse(
                text=direct_message_content,
                tool_calls=[tc.model_dump() for tc in tool_calls_made] if tool_calls_made else None,
                usage_metadata=usage_metadata,
            )
            
            return UnifiedOpenAIResponse(
                task_id=task_id,
                model_id=model_id,
                success=True,
                direct_message_content=direct_message_content,
                tool_calls_made=tool_calls_made,
                raw_response=raw_response,
                usage=usage_metadata,
            )

    except Exception as exc:
        error_msg = f"Groq API error: {str(exc)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        if stream:
            raise
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)


async def invoke_groq_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Main entry point for Groq chat completions.
    
    This function initializes the Groq client if needed and then invokes the API.
    
    Args:
        task_id: Unique identifier for this task
        model_id: Model identifier (may include provider prefix, e.g., "groq/openai/gpt-oss-20b")
        messages: List of message dicts with "role" and "content"
        secrets_manager: SecretsManager instance for accessing Vault
        temperature: Sampling temperature (0.0 to 2.0)
        max_tokens: Maximum tokens to generate
        tools: List of tool definitions (OpenAI format)
        tool_choice: Tool choice strategy ("auto", "none", "required", or specific tool)
        stream: Whether to stream the response
        
    Returns:
        UnifiedOpenAIResponse for non-streaming, or AsyncIterator for streaming
    """
    if secrets_manager and not _groq_client_initialized:
        await initialize_groq_client(secrets_manager)

    if not _groq_client_initialized:
        error_msg = "Groq client initialization failed. Check logs for details."
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    # Remove "groq/" prefix from model_id if present (Groq API expects model ID without provider prefix)
    # For example: "groq/openai/gpt-oss-20b" -> "openai/gpt-oss-20b"
    if model_id.startswith("groq/"):
        model_id = model_id[len("groq/"):]
    
    return await _invoke_groq_direct_api(
        task_id=task_id,
        model_id=model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
    )

