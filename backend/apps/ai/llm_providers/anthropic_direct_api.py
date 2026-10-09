# backend/apps/ai/llm_providers/anthropic_direct_api.py
# Direct API implementation for Anthropic Claude models

import logging
import json
import copy
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
from .openai_shared import calculate_token_breakdown
from .native_cache_context import (
    NativeCacheProviderOutput, safe_native_provider_error, validate_native_cache_context,
)

logger = logging.getLogger(__name__)


def _raw_anthropic_block(block: Any) -> Dict[str, Any]:
    """Copy a provider block without publishing private thinking/signatures."""
    if isinstance(block, dict):
        return copy.deepcopy(block)
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return copy.deepcopy(vars(block))


def _append_anthropic_delta(raw_blocks: Dict[int, Dict[str, Any]], event: Any) -> None:
    """Assemble replayable Anthropic content from its streamed deltas."""
    index = getattr(event, "index", None)
    if index not in raw_blocks:
        raise ValueError("Anthropic content delta has no preceding block")
    delta = event.delta
    kind = delta.type
    block = raw_blocks[index]
    if kind == "text_delta":
        block["text"] = block.get("text", "") + delta.text
    elif kind == "thinking_delta":
        block["thinking"] = block.get("thinking", "") + delta.thinking
    elif kind == "signature_delta":
        block["signature"] = block.get("signature", "") + delta.signature
    elif kind == "input_json_delta":
        # Parsed at content_block_stop, after all partial JSON has arrived.
        pass
    elif kind == "citations_delta":
        block.setdefault("citations", []).append(_raw_anthropic_block(delta.citation))
    else:
        raise ValueError(f"Unsupported Anthropic replay delta type: {kind}")


def _cache_creation_ttl_tokens(usage: Any) -> Dict[str, int]:
    """Read TTL counters from typed or forward-compatible SDK usage data."""
    creation = getattr(usage, "cache_creation", None)
    if creation is None:
        return {}
    fields = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
    values = {field: creation.get(field) if isinstance(creation, dict) else getattr(creation, field, None)
              for field in fields}
    return {field: value for field, value in values.items() if value is not None}


async def invoke_direct_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    anthropic_client: anthropic.Anthropic,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
    cacheable_system_prefix: Optional[str] = None,
    native_cache_context: Optional[Dict[str, Any]] = None,
) -> Union[UnifiedAnthropicResponse, AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]]:
    """Handle requests using Anthropic's direct API"""
    log_prefix = f"[{task_id}] Anthropic Direct API ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        native_events = None
        if native_cache_context is not None:
            baseline, native_events, _active_names = validate_native_cache_context(native_cache_context, messages)
            if not model_id.startswith(("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5")):
                raise ValueError("Anthropic inline tools require a direct Claude 5.5 model")
        system_prompt, anthropic_messages = _prepare_messages_for_anthropic(
            messages,
            None if native_cache_context is not None else cacheable_system_prefix,
            native_events=native_events,
        )
        
        if not anthropic_messages:
            err_msg = "Message history is empty after processing."
            if stream:
                raise ValueError(err_msg)
            return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

        anthropic_tools = _map_tools_to_anthropic_format(baseline if native_cache_context is not None else tools)
        
        # Prepare the request for direct API
        request_kwargs = {
            "model": model_id,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 16384
        }

        # Adaptive-thinking Claude models do not accept `temperature`.
        # Strip the model ID prefix (e.g. "eu.anthropic.") to normalise Bedrock IDs.
        bare_model = model_id.rsplit(".", 1)[-1] if model_id.startswith("eu.") else model_id
        temperature_unsupported = bare_model.startswith((
            "claude-fable-5",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-5-5",
            "claude-opus-4-7",
            "claude-opus-4-8",
        ))
        if not temperature_unsupported:
            request_kwargs["temperature"] = temperature
        
        if system_prompt:
            request_kwargs["system"] = system_prompt
            
        if native_cache_context is not None:
            # An empty, immutable baseline is valid for conversations that
            # start without tools. Later selected tools arrive inline by value.
            request_kwargs["tools"] = anthropic_tools or []
        elif anthropic_tools:
            request_kwargs["tools"] = anthropic_tools
        if anthropic_tools:
            if tool_choice and tool_choice != "auto":
                if tool_choice == "required":
                    # Sonnet 5.5 rejects forced tool choice. Enforce the
                    # caller's required-tool contract on the response below.
                    choice = "auto" if bare_model.startswith("claude-sonnet-5-5") else "any"
                    request_kwargs["tool_choice"] = {"type": choice}
                elif tool_choice == "none":
                    request_kwargs["tool_choice"] = {"type": "auto"}

        if native_cache_context is not None:
            request_kwargs["betas"] = ["inline-tools-2026-09-15"]
            # The pinned Anthropic SDK accepts beta headers but predates the
            # top-level automatic cache_control parameter. extra_body merges it
            # into the wire JSON without changing legacy request typing.
            request_kwargs["extra_body"] = {"cache_control": {"type": "ephemeral"}}

        logger.debug(f"{log_prefix} Request prepared with caching optimizations.")

        require_tool = bool(anthropic_tools and tool_choice == "required" and bare_model.startswith("claude-sonnet-5-5"))
        if stream:
            response_stream = _iterate_direct_api_stream(task_id, model_id, request_kwargs, anthropic_client, messages, log_prefix, tools=tools, native_cache_context=native_cache_context)
            return _require_tool_call_stream(response_stream) if require_tool else response_stream
        else:
            response = await _process_direct_api_response(task_id, model_id, request_kwargs, anthropic_client, messages, log_prefix, tools=tools, native_cache_context=native_cache_context)
            if require_tool and response.success and not response.tool_calls_made:
                response.success = False
                response.direct_message_content = None
                response.error_message = "Anthropic response omitted the required tool call"
            return response

    except Exception as e:
        if native_cache_context is not None:
            safe_error = safe_native_provider_error(e)
            logger.error("%s Direct API preparation failed: %s", log_prefix, safe_error)
            if stream:
                raise ValueError(safe_error) from None
            return UnifiedAnthropicResponse(
                task_id=task_id, model_id=model_id, success=False,
                error_message=safe_error,
            )
        err_msg = f"Error during direct API request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream:
            raise ValueError(err_msg)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)


async def _require_tool_call_stream(
    response_stream: AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]],
) -> AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]:
    """Withhold a text-only answer when Sonnet cannot force a required tool."""
    pending: List[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]] = []
    tool_seen = False
    async for item in response_stream:
        if not tool_seen:
            if not isinstance(item, ParsedAnthropicToolCall):
                pending.append(item)
                continue
            tool_seen = True
            for buffered in pending:
                yield buffered
            pending.clear()
        yield item
    if not tool_seen:
        # Preserve paid provider usage for settlement, but never present the
        # unsolicited text as a successful answer to a required-tool request.
        for buffered in pending:
            if isinstance(buffered, AnthropicUsageMetadata):
                yield buffered
        raise IOError("Anthropic response omitted the required tool call")


async def _process_direct_api_response(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    anthropic_client: anthropic.Anthropic,
    messages: List[Dict[str, str]],
    log_prefix: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    native_cache_context: Optional[Dict[str, Any]] = None,
) -> UnifiedAnthropicResponse:
    """Process non-streaming response from Anthropic direct API"""
    try:
        # Log the actual request details for debugging
        logger.info(f"{log_prefix} Making request to Anthropic API with model '{model_id}'")
        endpoint = anthropic_client.beta.messages if native_cache_context is not None else anthropic_client.messages
        response = endpoint.create(**request_kwargs)
        logger.info(f"{log_prefix} Received non-streamed response from Anthropic direct API.")
        
        # Calculate token breakdown from input messages (estimate)
        token_breakdown = calculate_token_breakdown(messages, model_id, tools=tools)

        # Parse direct API response
        creation_details = _cache_creation_ttl_tokens(response.usage)
        usage_metadata = AnthropicUsageMetadata(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            cache_creation_input_tokens=getattr(response.usage, 'cache_creation_input_tokens', None),
            cache_read_input_tokens=getattr(response.usage, 'cache_read_input_tokens', None),
            cache_creation_5m_input_tokens=creation_details.get("ephemeral_5m_input_tokens"),
            cache_creation_1h_input_tokens=creation_details.get("ephemeral_1h_input_tokens"),
            provider_request_id=getattr(response, "id", None),
            user_input_tokens=token_breakdown.get("user_input_tokens"),
            system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
        )
        
        raw_response_pydantic = RawAnthropicChatCompletionResponse(
            usage_metadata=usage_metadata
        )

        unified_resp = UnifiedAnthropicResponse(
            task_id=task_id, model_id=model_id, success=True,
            raw_response=raw_response_pydantic, usage=usage_metadata
        )
        if native_cache_context is not None:
            unified_resp.provider_transport_state = [
                _raw_anthropic_block(block) for block in response.content
            ]
        
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
        if (usage_metadata.cache_read_input_tokens or 0) > 0:
            logger.info(f"{log_prefix} Cache hit: {usage_metadata.cache_read_input_tokens} tokens read from cache.")
        if (usage_metadata.cache_creation_input_tokens or 0) > 0:
            logger.info(f"{log_prefix} Cache write: {usage_metadata.cache_creation_input_tokens} tokens written to cache.")
            
        return unified_resp
        
    except Exception as e:
        if native_cache_context is not None:
            safe_error = safe_native_provider_error(e)
            logger.error("%s Direct API response failed: %s", log_prefix, safe_error)
            return UnifiedAnthropicResponse(
                task_id=task_id, model_id=model_id, success=False,
                error_message=safe_error,
            )
        logger.error(f"{log_prefix} Failed to process direct API response: {e}", exc_info=True)
        return UnifiedAnthropicResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))


async def _iterate_direct_api_stream(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    anthropic_client: anthropic.Anthropic,
    messages: List[Dict[str, str]],
    log_prefix: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    native_cache_context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[Union[str, ParsedAnthropicToolCall, AnthropicUsageMetadata]]:
    """Handle streaming response from Anthropic direct API"""
    logger.info(f"{log_prefix} Stream connection initiated.")
    
    output_buffer = ""
    usage = None
    usage_parts: Dict[str, Any] = {}
    provider_request_id = None
    current_tool_calls: Dict[int, Dict[str, Any]] = {}
    raw_blocks: Dict[int, Dict[str, Any]] = {}
    native_output_complete = False
    
    try:
        request_kwargs["stream"] = True
        endpoint = anthropic_client.beta.messages if native_cache_context is not None else anthropic_client.messages
        stream = endpoint.create(**request_kwargs)
        
        # Calculate token breakdown from input messages (estimate)
        token_breakdown = calculate_token_breakdown(messages, model_id, tools=tools)

        for event in stream:
            if event.type == "message_start":
                start_message = getattr(event, "message", None)
                provider_request_id = getattr(start_message, "id", None)
                start_usage = getattr(start_message, "usage", None)
                if start_usage is not None:
                    for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                        value = getattr(start_usage, field, None)
                        if value is not None:
                            usage_parts[field] = value
                    usage_parts.update(_cache_creation_ttl_tokens(start_usage))
            elif event.type == "content_block_delta":
                if native_cache_context is not None:
                    _append_anthropic_delta(raw_blocks, event)
                if event.delta.type == "text_delta":
                    text_chunk = event.delta.text
                    output_buffer += text_chunk
                    yield text_chunk
                elif event.delta.type == "input_json_delta":
                    block_index = getattr(event, "index", None)
                    if block_index not in current_tool_calls:
                        raise ValueError(
                            "Received Anthropic tool input JSON for an unknown "
                            f"content block index: {block_index}"
                        )
                    current_tool_calls[block_index]["input_json_parts"].append(
                        event.delta.partial_json
                    )
            
            elif event.type == "content_block_start":
                if native_cache_context is not None:
                    block_index = getattr(event, "index", None)
                    if block_index is None or block_index in raw_blocks:
                        raise ValueError("Anthropic content block has an invalid stream index")
                    raw_blocks[block_index] = _raw_anthropic_block(event.content_block)
                if event.content_block.type == "tool_use":
                    block_index = getattr(event, "index", None)
                    if block_index is None:
                        raise ValueError(
                            "Anthropic tool content block is missing its stream index"
                        )
                    tool_id = event.content_block.id
                    tool_name = event.content_block.name
                    current_tool_calls[block_index] = {
                        "id": tool_id,
                        "name": tool_name,
                        "initial_input": event.content_block.input,
                        "input_json_parts": [],
                    }
            
            elif event.type == "content_block_stop":
                block_index = getattr(event, "index", None)
                tool_call = current_tool_calls.pop(block_index, None)
                if tool_call is not None:
                    input_json_parts = tool_call["input_json_parts"]
                    if input_json_parts:
                        arguments_raw = "".join(input_json_parts)
                        try:
                            args_dict = json.loads(arguments_raw)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"Anthropic tool '{tool_call['name']}' emitted invalid JSON arguments"
                            ) from exc
                    else:
                        args_dict = tool_call["initial_input"]
                        arguments_raw = json.dumps(args_dict)

                    if not isinstance(args_dict, dict):
                        raise ValueError(
                            f"Anthropic tool '{tool_call['name']}' arguments must decode to an object"
                        )

                    if native_cache_context is not None:
                        raw_blocks[block_index]["input"] = copy.deepcopy(args_dict)

                    parsed_tool_call = ParsedAnthropicToolCall(
                        tool_call_id=tool_call["id"],
                        function_name=tool_call["name"],
                        function_arguments_parsed=args_dict,
                        function_arguments_raw=arguments_raw,
                    )
                    logger.info(f"{log_prefix} Yielding a tool call from stream: {tool_call['name']}")
                    yield parsed_tool_call
            
            elif event.type == "message_delta":
                # Check stop_reason for truncation/blocking detection.
                # Anthropic sends stop_reason in message_delta: "end_turn", "max_tokens",
                # "stop_sequence", or "tool_use". If max_tokens, the response was truncated.
                stop_reason = getattr(event.delta, 'stop_reason', None)
                if native_cache_context is not None and stop_reason in ("end_turn", "tool_use"):
                    native_output_complete = True
                if stop_reason and stop_reason not in ("end_turn", "tool_use"):
                    logger.warning(f"{log_prefix} Response ended with stop_reason='{stop_reason}'")
                    if stop_reason == "max_tokens":
                        yield "\n\n---\n*This response was cut short because it reached the model's maximum output length. You can ask the AI to continue.*"

                # The SDK puts cumulative usage on the event, alongside delta.
                # Replace reported totals rather than summing successive deltas.
                usage_data = getattr(event, "usage", None)
                if usage_data is not None:
                    for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                        value = getattr(usage_data, field, None)
                        if value is not None:
                            usage_parts[field] = value
                    usage_parts.update(_cache_creation_ttl_tokens(usage_data))

        if native_cache_context is not None:
            if not native_output_complete:
                raise ValueError("Anthropic native stream ended without a complete response")
            yield NativeCacheProviderOutput(
                provider_prefix="anthropic", model_id=model_id,
                output=[raw_blocks[index] for index in sorted(raw_blocks)],
            )

        if usage_parts:
            input_tokens = int(usage_parts.get("input_tokens") or 0)
            output_tokens = int(usage_parts.get("output_tokens") or 0)
            usage = AnthropicUsageMetadata(
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_creation_input_tokens=usage_parts.get("cache_creation_input_tokens"),
                cache_read_input_tokens=usage_parts.get("cache_read_input_tokens"),
                cache_creation_5m_input_tokens=usage_parts.get("ephemeral_5m_input_tokens"),
                cache_creation_1h_input_tokens=usage_parts.get("ephemeral_1h_input_tokens"),
                user_input_tokens=token_breakdown.get("user_input_tokens"),
                system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
                provider_request_id=provider_request_id,
            )

        # Yield final usage information
        if usage:
            if (usage.cache_read_input_tokens or 0) > 0:
                logger.info(f"{log_prefix} Stream cache hit: {usage.cache_read_input_tokens} tokens read from cache.")
            if (usage.cache_creation_input_tokens or 0) > 0:
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
                    usage_source="estimated",
                    user_input_tokens=token_breakdown.get("user_input_tokens"),
                    system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
                )
                yield usage
            except Exception as e:
                if native_cache_context is not None:
                    logger.error("%s Usage estimate failed: %s", log_prefix,
                                 safe_native_provider_error(e))
                else:
                    logger.error(f"{log_prefix} Failed to estimate tokens with tiktoken: {e}", exc_info=True)

        logger.info(f"{log_prefix} Stream finished.")

    except Exception as e_stream:
        if native_cache_context is not None:
            safe_error = safe_native_provider_error(e_stream)
            logger.error("%s Direct API stream failed: %s", log_prefix, safe_error)
            raise IOError(safe_error) from None
        err_msg = f"Unexpected error during direct API streaming: {e_stream}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        raise IOError(f"Anthropic Direct API Streaming Error: {e_stream}") from e_stream
