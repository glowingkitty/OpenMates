"""Adapt direct Baseten Model APIs to the existing AI provider contract."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from backend.shared.providers.baseten import (
    BasetenClient,
    BasetenError,
    BasetenRequest,
    resolve_api_key,
)
from .openai_shared import (
    OpenAIUsageMetadata,
    ParsedOpenAIToolCall,
    UnifiedOpenAIResponse,
    _map_tools_to_openai_format,
    merge_openai_usage,
    openai_usage_details,
)
from .types import StreamChunkType, UnifiedStreamChunk


def _usage(raw: dict[str, Any], request_id: str | None) -> OpenAIUsageMetadata:
    return OpenAIUsageMetadata(
        input_tokens=raw.get("prompt_tokens", 0),
        output_tokens=raw.get("completion_tokens", 0),
        total_tokens=raw.get("total_tokens", 0),
        **openai_usage_details(
            raw, inference_host="baseten", provider_request_id=request_id
        ),
    )


def _tool(call: dict[str, Any]) -> ParsedOpenAIToolCall:
    function = call.get("function") or {}
    raw = function.get("arguments") or ""
    error = None
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError()
    except (ValueError, TypeError):
        args, error = {}, "Baseten tool arguments must be a JSON object"
    return ParsedOpenAIToolCall(
        tool_call_id=call.get("id") or "",
        function_name=function.get("name") or "",
        function_arguments_raw=raw,
        function_arguments_parsed=args,
        parsing_error=error,
    )


async def _stream(client: BasetenClient, request: BasetenRequest) -> AsyncIterator[Any]:
    calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    request_id, finished = None, False
    stream = client.stream(request)
    try:
        async for event in stream:
            request_id = event.id or request_id
            merge_openai_usage(usage, event.usage)
            for choice in event.choices:
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    yield UnifiedStreamChunk(
                        type=StreamChunkType.THINKING,
                        content=delta["reasoning_content"],
                    )
                if delta.get("content"):
                    yield delta["content"]
                for fragment in delta.get("tool_calls") or []:
                    index = fragment.get("index")
                    if not isinstance(index, int) or index < 0:
                        raise BasetenError("Baseten returned an invalid tool index")
                    call = calls.setdefault(
                        index, {"id": "", "function": {"name": "", "arguments": ""}}
                    )
                    call["id"] = fragment.get("id") or call["id"]
                    for key in ("name", "arguments"):
                        call["function"][key] += (fragment.get("function") or {}).get(
                            key
                        ) or ""
                reason = choice.get("finish_reason")
                if reason:
                    if reason not in {"stop", "tool_calls", "length"}:
                        raise BasetenError("Baseten completion was blocked")
                    if reason == "length" and calls:
                        raise BasetenError(
                            "Baseten tool call exceeded its output limit"
                        )
                    if reason == "length":
                        yield "\n\nThis response reached its output limit."
                    for index in sorted(calls):
                        yield _tool(calls[index])
                    calls.clear()
                    finished = True
        if not finished or calls:
            raise BasetenError("Baseten returned an unfinished completion")
    except Exception:
        if usage:
            yield _usage(usage, request_id)
        raise
    finally:
        await stream.aclose()
    if usage:
        yield _usage(usage, request_id)


async def invoke_baseten_chat_completions(
    task_id: str,
    model_id: str,
    messages: list[dict[str, Any]],
    secrets_manager: Any = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    stream: bool = False,
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> Any:
    key = await resolve_api_key(secrets_manager)
    client = BasetenClient(key, session_affinity=prompt_cache_key)
    try:
        request = BasetenRequest(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=_map_tools_to_openai_format(tools) if tools else None,
            tool_choice=tool_choice,
            reasoning_effort=reasoning_effort,
            response_format=response_format,
        )
    except (ValueError, TypeError):
        raise BasetenError("Invalid Baseten request configuration") from None
    if stream:
        return _stream(client, request)
    result = await client.complete(request)
    if not result.choices:
        raise BasetenError("Baseten returned no completion")
    choice = result.choices[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    if choice.get("finish_reason") not in {"stop", "tool_calls", "length"}:
        raise BasetenError("Baseten returned an unfinished or blocked completion")
    if choice.get("finish_reason") == "length" and calls:
        raise BasetenError("Baseten tool call exceeded its output limit")
    return UnifiedOpenAIResponse(
        task_id=task_id,
        model_id=model_id,
        success=True,
        direct_message_content=message.get("content"),
        tool_calls_made=[_tool(call) for call in calls] or None,
        usage=_usage(result.usage, result.id) if result.usage is not None else None,
    )
