# backend/apps/ai/llm_providers/anthropic_shared.py
# Shared utilities and models for Anthropic implementations

import copy
import json
import logging
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Caching configuration
CACHE_TOKEN_THRESHOLD = 1024  # Minimum tokens required for caching
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate for token counting

# --- Pydantic Models for Structured Anthropic Response ---

class AnthropicUsageMetadata(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    cache_creation_5m_input_tokens: Optional[int] = None
    cache_creation_1h_input_tokens: Optional[int] = None
    user_input_tokens: Optional[int] = None
    system_prompt_tokens: Optional[int] = None
    usage_source: str = "provider_reported"
    inference_host: Optional[str] = "anthropic"
    provider_request_id: Optional[str] = None

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
    provider_transport_state: Optional[List[Dict[str, Any]]] = Field(
        default=None, repr=False, exclude=True,
    )


def _should_cache_content(content: str) -> bool:
    """Determine if content should be cached based on token threshold"""
    if not content:
        return False
    
    # Conservative estimation: ~4 chars per token
    estimated_tokens = len(content) / CHARS_PER_TOKEN_ESTIMATE
    return estimated_tokens >= CACHE_TOKEN_THRESHOLD


def _map_tools_to_anthropic_format(tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Maps tools from internal format to Anthropic's expected format.
    
    Note: Tools should already be sanitized (min/max removed) before being passed here.
    This function only handles format conversion, not schema sanitization.
    """
    if not tools:
        return None
    
    anthropic_tools = []
    for tool_def in tools:
        if tool_def.get("type") == "function":
            func = tool_def.get("function", {})
            anthropic_tools.append({
                "name": func.get("name"),
                "description": func.get("description"),
                "input_schema": func.get("parameters", {})  # Should already be sanitized
            })
    
    return anthropic_tools if anthropic_tools else None


def _prepare_system_with_caching(system_prompt: str, cacheable_system_prefix: Optional[str] = None) -> Union[str, List[Dict[str, Any]]]:
    """Prepare system prompt with caching if it meets threshold"""
    if not system_prompt:
        return system_prompt

    if cacheable_system_prefix:
        if not system_prompt.startswith(cacheable_system_prefix):
            raise ValueError("Cacheable system prefix does not match the system prompt")
        blocks: List[Dict[str, Any]] = [{"type": "text", "text": cacheable_system_prefix}]
        if _should_cache_content(cacheable_system_prefix):
            blocks[0]["cache_control"] = {"type": "ephemeral"}
        suffix = system_prompt[len(cacheable_system_prefix):]
        if suffix:
            blocks.append({"type": "text", "text": suffix})
        return blocks
    
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


def _prepare_messages_with_caching(
    messages: List[Dict[str, Any]],
    native_events: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    index_offset: int = 0,
) -> List[Dict[str, Any]]:
    """Convert canonical history to Anthropic messages without mutating it.

    Canonical tool history uses an assistant message with ``tool_calls`` followed
    by one or more ``role=tool`` messages. Anthropic requires the equivalent
    ``tool_use`` blocks in the assistant turn and all parallel ``tool_result``
    blocks in one following user turn.
    """
    anthropic_messages: List[Dict[str, Any]] = []
    pending_tool_results: List[Dict[str, Any]] = []

    def append_native_events(original_index: int) -> None:
        for event in (native_events or {}).get(original_index, []):
            flush_tool_results()
            blocks: List[Dict[str, Any]] = []
            if event.get("system_suffix"):
                blocks.append({"type": "text", "text": event["system_suffix"]})
            for name in event.get("remove_tools", []):
                blocks.append({
                    "type": "tool_removal",
                    "tool": {"type": "tool_reference", "name": name},
                })
            for tool in event.get("add_tools", []):
                definition = _map_tools_to_anthropic_format([tool])[0]
                blocks.append({
                    "type": "tool_addition",
                    "tool": {"type": "tool_definition", "definition": definition},
                })
            anthropic_messages.append({"role": "system", "content": blocks})

    def flush_tool_results() -> None:
        if not pending_tool_results:
            return
        anthropic_messages.append({
            "role": "user",
            "content": list(pending_tool_results),
        })
        pending_tool_results.clear()

    def tool_input(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        function = tool_call.get("function") or {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, dict):
            return copy.deepcopy(arguments)
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Tool call '{tool_call.get('id', '')}' contains invalid JSON arguments"
                ) from exc
            if isinstance(parsed_arguments, dict):
                return parsed_arguments
            raise ValueError(
                f"Tool call '{tool_call.get('id', '')}' arguments must decode to an object"
            )
        raise ValueError(
            f"Tool call '{tool_call.get('id', '')}' arguments must be an object or JSON string"
        )
    
    for local_index, msg in enumerate(messages):
        original_index = local_index + index_offset
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Handle tool responses — convert to Anthropic's tool_result format.
        # Anthropic requires tool results as a user-role message containing a
        # tool_result block, not a top-level "tool" role.
        # Content can be either:
        #   - str: plain text (TOON/JSON) — wrap directly
        #   - list: multimodal blocks (image_url + text from view skills) — convert each block
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            
            # Build the inner content for the tool_result block
            if isinstance(content, list):
                # Multimodal content from skills like images.view / pdf.view
                # Convert OpenAI image_url blocks → Anthropic image source blocks
                anthropic_tool_content: List[Dict[str, Any]] = []
                for block in content:
                    block_type = block.get("type", "")
                    if block_type == "text":
                        anthropic_tool_content.append({
                            "type": "text",
                            "text": block.get("text", "")
                        })
                    elif block_type == "image_url":
                        image_url_data = block.get("image_url", {})
                        url = image_url_data.get("url", "")
                        # Expect data URI: "data:<mime>;base64,<data>"
                        if url.startswith("data:") and ";base64," in url:
                            header, b64_data = url.split(";base64,", 1)
                            mime_type = header[len("data:"):]  # e.g. "image/webp"
                            anthropic_tool_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": b64_data,
                                }
                            })
                        else:
                            # Non-data URL — fall back to text description
                            logger.warning(
                                f"[anthropic_shared] image_url block has non-data URL "
                                f"(not supported by Anthropic): {url[:60]}"
                            )
                            anthropic_tool_content.append({
                                "type": "text",
                                "text": f"[image: {url[:60]}]"
                            })
                    else:
                        logger.warning(
                            f"[anthropic_shared] Unknown content block type in tool result: {block_type}"
                        )
            else:
                # Plain-text tool result — Anthropic accepts a plain string here
                anthropic_tool_content = [{"type": "text", "text": str(content) if content else ""}]
            
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": anthropic_tool_content,
            })
            append_native_events(original_index)
            continue

        flush_tool_results()

        tool_calls = msg.get("tool_calls")
        if role == "assistant" and native_events is not None:
            state = msg.get("provider_transport_state") or next(
                (call.get("provider_transport_state") for call in (tool_calls or [])
                 if call.get("provider_transport_state")), None,
            )
            if isinstance(state, list) and state and all(isinstance(block, dict) for block in state):
                anthropic_messages.append({"role": "assistant", "content": copy.deepcopy(state)})
                append_native_events(original_index)
                continue
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            assistant_content: List[Dict[str, Any]] = []
            if isinstance(content, str) and content:
                text_block: Dict[str, Any] = {"type": "text", "text": content}
                if _should_cache_content(content):
                    text_block["cache_control"] = {"type": "ephemeral"}
                assistant_content.append(text_block)
            elif isinstance(content, list):
                assistant_content.extend(copy.deepcopy(content))

            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                assistant_content.append({
                    "type": "tool_use",
                    "id": tool_call.get("id", ""),
                    "name": function.get("name", ""),
                    "input": tool_input(tool_call),
                })

            anthropic_messages.append({
                "role": "assistant",
                "content": assistant_content,
            })
            append_native_events(original_index)
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
        append_native_events(original_index)
            
    flush_tool_results()
    return anthropic_messages


def _prepare_messages_for_anthropic(
    messages: List[Dict[str, Any]], cacheable_system_prefix: Optional[str] = None,
    native_events: Optional[Dict[int, List[Dict[str, Any]]]] = None,
) -> Tuple[Optional[Union[str, List[Dict[str, Any]]]], List[Dict[str, Any]]]:
    """Prepare messages for Anthropic API with caching support"""
    system_prompt = None
    processed_messages = list(messages)
    index_offset = 0
    
    # Extract system prompt if present
    if processed_messages and processed_messages[0].get("role") == "system":
        system_prompt_content = processed_messages.pop(0)["content"]
        system_prompt = _prepare_system_with_caching(system_prompt_content, cacheable_system_prefix)
        index_offset = 1

    # Process remaining messages with selective caching
    anthropic_messages = _prepare_messages_with_caching(
        processed_messages, native_events=native_events, index_offset=index_offset,
    )
    if native_events is not None:
        # Automatic caching chooses the latest stable breakpoint. The legacy
        # rolling four-marker policy edits old messages as history grows.
        if isinstance(system_prompt, list):
            for block in system_prompt:
                block.pop("cache_control", None)
        for message in anthropic_messages:
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)
        return system_prompt, anthropic_messages
    # Claude accepts at most four explicit breakpoints. Keep the system marker
    # and the latest history markers, where a later turn has the best reuse odds.
    markers: List[Dict[str, Any]] = []
    if isinstance(system_prompt, list):
        markers.extend(block for block in system_prompt if "cache_control" in block)
    for message in anthropic_messages:
        content = message.get("content")
        if isinstance(content, list):
            markers.extend(block for block in content if isinstance(block, dict) and "cache_control" in block)
    if len(markers) > 4:
        system_has_marker = isinstance(system_prompt, list) and any(
            block is markers[0] for block in system_prompt
        )
        chosen = markers[:1] + markers[-3:] if system_has_marker else markers[-4:]
        keep = {id(block) for block in chosen}
        for block in markers:
            if id(block) not in keep:
                block.pop("cache_control", None)
            
    return system_prompt, anthropic_messages
