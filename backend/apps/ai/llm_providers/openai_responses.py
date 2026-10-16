# Stateless OpenAI Responses transport for models requiring Responses tool calls.
# Adapts provider events to the existing OpenMates text/tool/usage boundary.
# Opaque reasoning is replayed only with the current tool continuation history.
# Provider storage is always disabled; no previous_response_id is used.
# See docs/architecture/ai/ai-model-selection.md for model routing boundaries.

import json
from typing import Any

from .openai_shared import OpenAIUsageMetadata, ParsedOpenAIToolCall, UnifiedOpenAIResponse, openai_cache_read_tokens, openai_cache_write_tokens
from .native_cache_context import (
    NativeCacheProviderOutput, openai_function_tool,
    reject_openai_schema_changes, validate_native_cache_context,
)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else value.model_dump(exclude_none=True)


def responses_input(messages: list[dict]) -> list[dict]:
    """Translate chat history, replaying complete provider items once per turn."""
    result = []
    for message in messages:
        role = message.get("role")
        calls = message.get("tool_calls") or []
        state = message.get("provider_transport_state") or next((c.get("provider_transport_state") for c in calls if c.get("provider_transport_state")), None)
        if role == "assistant" and isinstance(state, list) and state and all(isinstance(item, dict) for item in state):
            result.extend(state)
            continue
        if role == "tool":
            result.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": message.get("content") or ""})
            continue
        content = message.get("content")
        if content:
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        text_part = {"type": "output_text" if role == "assistant" else "input_text", "text": part["text"]}
                        if role == "system" and part.get("prompt_cache_breakpoint"):
                            text_part["prompt_cache_breakpoint"] = part["prompt_cache_breakpoint"]
                        parts.append(text_part)
                    elif part.get("type") == "image_url":
                        image = part["image_url"]
                        parts.append({"type": "input_image", "image_url": image["url"], "detail": image.get("detail", "auto")})
                    else:
                        raise ValueError("Unsupported Responses input content type")
                content = parts
            result.append({"role": role, "content": content})
        for call in calls:
            result.append({"type": "function_call", "call_id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]})
    return result


def native_responses_input(
    messages: list[dict], events: dict[int, list[dict]],
) -> list[dict]:
    """Insert native instructions and selected tools after their original turns."""
    result: list[dict] = []
    for index, message in enumerate(messages):
        result.extend(responses_input([message]))
        for event in events.get(index, []):
            if event.get("system_suffix"):
                result.append({"role": "developer", "content": event["system_suffix"]})
            if event.get("add_tools"):
                result.append({
                    "type": "additional_tools", "role": "developer",
                    "tools": [openai_function_tool(tool) for tool in event["add_tools"]],
                })
    return result


def _tool_calls(output: list[dict]) -> list[ParsedOpenAIToolCall]:
    calls = []
    for item in output:
        if item.get("type") != "function_call":
            continue
        raw = item.get("arguments") or "{}"
        error = None
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be an object")
        except (ValueError, TypeError):
            args, error = {}, "Invalid JSON object in Responses tool arguments"
        calls.append(ParsedOpenAIToolCall(tool_call_id=item["call_id"], function_name=item["name"], function_arguments_raw=raw, function_arguments_parsed=args, parsing_error=error, provider_transport_state=output if not calls else None))
    return calls


def _usage(response: dict) -> OpenAIUsageMetadata | None:
    usage = response.get("usage")
    if not usage:
        return None
    return OpenAIUsageMetadata(
        input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
        cache_read_input_tokens=openai_cache_read_tokens(usage, responses=True),
        cache_creation_input_tokens=openai_cache_write_tokens(usage, responses=True),
        inference_host="openai", provider_request_id=response.get("id"),
    )


async def invoke_responses(*, client: Any, task_id: str, model_id: str, messages: list[dict], reasoning_effort: str, tools: list[dict] | None = None, tool_choice: Any = None, max_tokens: int | None = None, stream: bool = False, native_cache_context: dict | None = None) -> Any:
    payload = {"model": model_id, "input": responses_input(messages), "reasoning": {"effort": reasoning_effort}, "store": False, "stream": stream}
    if max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    if native_cache_context is not None:
        baseline, events, active_names = validate_native_cache_context(native_cache_context, messages)
        reject_openai_schema_changes(baseline, events)
        payload["input"] = native_responses_input(messages, events)
        if baseline:
            payload["tools"] = [openai_function_tool(tool) for tool in baseline]
        # Responses has no tool-removal input item. Keep the exact earlier input
        # and restrict only this turn's callable names when a removal occurred.
        has_removal = any(event.get("remove_tools") for group in events.values() for event in group)
        if has_removal:
            if tool_choice == "none":
                payload["tool_choice"] = "none"
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                if tool_choice.get("name") not in active_names:
                    raise ValueError("Forced Responses tool is unavailable in native cache context")
                payload["tool_choice"] = tool_choice
            elif isinstance(tool_choice, dict) and "function" in tool_choice:
                name = tool_choice["function"]["name"]
                if name not in active_names:
                    raise ValueError("Forced Responses tool is unavailable in native cache context")
                payload["tool_choice"] = {"type": "function", "name": name}
            elif tool_choice in (None, "auto", "required"):
                if tool_choice == "required" and not active_names:
                    raise ValueError("Required Responses tool is unavailable in native cache context")
                payload["tool_choice"] = (
                    {"type": "allowed_tools", "mode": "required" if tool_choice == "required" else "auto",
                     "tools": [{"type": "function", "name": name} for name in active_names]}
                    if active_names else "none"
                )
            else:
                raise ValueError("Unsupported Responses tool choice for native cache context")
        elif tool_choice is not None and (baseline or events):
            payload["tool_choice"] = ({"type": "function", "name": tool_choice["function"]["name"]} if isinstance(tool_choice, dict) and "function" in tool_choice else tool_choice)
    elif tools:
        payload["tools"] = [openai_function_tool(tool) for tool in tools]
        if tool_choice is not None:
            payload["tool_choice"] = ({"type": "function", "name": tool_choice["function"]["name"]} if isinstance(tool_choice, dict) else tool_choice)

    async def iterate():
        events = await client.responses.create(**payload)
        completed = False
        try:
            async for event in events:
                event = _dict(event)
                kind = event.get("type")
                if kind in {"response.created", "response.in_progress", "response.output_item.added", "response.output_item.done", "response.function_call_arguments.delta", "response.function_call_arguments.done"}:
                    # Forward actual provider activity to the timeout wrapper.
                    # Empty text is ignored by the product stream consumer; never
                    # fabricate heartbeat timers or expose opaque reasoning.
                    yield ""
                elif kind == "response.output_text.delta":
                    yield event["delta"]
                elif kind == "response.refusal.delta":
                    yield event["delta"]
                elif kind == "response.completed":
                    response = event["response"]
                    if response.get("status") != "completed":
                        raise RuntimeError("Responses request did not complete")
                    for call in _tool_calls(response.get("output") or []):
                        yield call
                    if native_cache_context is not None:
                        yield NativeCacheProviderOutput(
                            provider_prefix="openai", model_id=model_id,
                            output=response.get("output") or [],
                        )
                    usage = _usage(response)
                    if usage:
                        yield usage
                    completed = True
                elif kind in {"response.failed", "response.incomplete", "error"}:
                    raise RuntimeError(f"Responses stream ended with {kind}")
            if not completed:
                raise RuntimeError("Responses stream closed without completion")
        finally:
            close = getattr(events, "close", None)
            if close:
                await close()

    if stream:
        return iterate()
    response = _dict(await client.responses.create(**payload))
    if response.get("status") != "completed":
        raise RuntimeError("Responses request incomplete or failed")
    output = response.get("output") or []
    text = "".join(part.get("text", part.get("refusal", "")) for item in output if item.get("type") == "message" for part in item.get("content", []))
    return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=True, direct_message_content=text, tool_calls_made=_tool_calls(output), usage=_usage(response))
