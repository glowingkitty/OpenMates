"""Adapt the pure Inception client to OpenMates' existing typed LLM contract."""
import json
from typing import Any, AsyncIterator

from backend.shared.providers.inception import InceptionClient, InceptionError, InceptionRequest, resolve_api_key
from .openai_shared import (
    OpenAIUsageMetadata, ParsedOpenAIToolCall, RawOpenAIChatCompletionResponse,
    UnifiedOpenAIResponse, _map_tools_to_openai_format,
)


def _usage(result: Any) -> OpenAIUsageMetadata | None:
    if result.usage is None:
        return None
    usage = result.usage
    return OpenAIUsageMetadata(
        input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cache_read_input_tokens=(usage.prompt_tokens_details or {}).get("cached_tokens"),
        reasoning_tokens=(usage.completion_tokens_details or {}).get("reasoning_tokens"),
        inference_host="inception", provider_request_id=result.id,
    )


TRUNCATION_NOTICE = "\n\n---\n*This response was cut short because it reached the model's maximum output length. You can ask the AI to continue.*"


def _text_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten ordinary text-block envelopes without admitting image inputs."""
    normalized = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            if any(not isinstance(block, dict) or block.get("type") != "text"
                   or not isinstance(block.get("text"), str) for block in content):
                raise InceptionError("Inception supports text content only")
            content = "".join(block["text"] for block in content)
            message = {**message, "content": content}
        normalized.append(message)
    return normalized


def _tool(call: dict[str, Any]) -> ParsedOpenAIToolCall:
    function = call.get("function") or {}
    raw = function.get("arguments") or ""
    error = None
    try:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            raise ValueError()
    except (ValueError, TypeError):
        arguments = {}
        error = "Inception tool arguments are not a JSON object"
    return ParsedOpenAIToolCall(
        tool_call_id=call.get("id") or "", function_name=function.get("name") or "",
        function_arguments_raw=raw, function_arguments_parsed=arguments, parsing_error=error,
    )


async def _stream(client: InceptionClient, request: InceptionRequest) -> AsyncIterator[Any]:
    calls: dict[int, dict[str, Any]] = {}
    finished = False
    stream = client.stream(request)
    try:
        async for result in stream:
            for choice in result.choices:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield delta["content"]
                for fragment in delta.get("tool_calls") or []:
                    index = fragment.get("index")
                    if not isinstance(index, int) or index < 0:
                        raise InceptionError("Inception API returned an invalid tool delta")
                    call = calls.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                    if fragment.get("id"):
                        call["id"] = fragment["id"]
                    function = fragment.get("function") or {}
                    for key in ("name", "arguments"):
                        call["function"][key] += function.get(key) or ""
                finish_reason = choice.get("finish_reason")
                if finish_reason and finish_reason not in {"stop", "tool_calls", "length"}:
                    raise InceptionError("Inception completion was blocked or unsupported")
                if finish_reason == "length":
                    if calls:
                        raise InceptionError("Inception tool call exceeded its output limit")
                    yield TRUNCATION_NOTICE
                if finish_reason:
                    finished = True
                    for index in sorted(calls):
                        yield _tool(calls[index])
                    calls.clear()
            usage = _usage(result)
            if usage is not None:
                yield usage
        if calls:
            raise InceptionError("Inception API ended with unfinished tool calls")
        if not finished:
            raise InceptionError("Inception API stream ended without a finish reason")
    finally:
        await stream.aclose()


async def invoke_inception_chat_completions(
    task_id: str, model_id: str, messages: list[dict[str, Any]],
    secrets_manager: Any = None, temperature: float = 0.7,
    max_tokens: int | None = None, tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None, stream: bool = False, reasoning_effort: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> Any:
    try:
        api_key = await resolve_api_key(secrets_manager)
        # Logical-model fallback owns recovery; do not spend its fast-path budget on retries.
        client = InceptionClient(api_key, max_retries=0)
        request = InceptionRequest(
            model=model_id, messages=_text_messages(messages), temperature=temperature,
            max_completion_tokens=min(max_tokens, 131072) if max_tokens is not None else None,
            tools=_map_tools_to_openai_format(tools) if tools else None,
            tool_choice=tool_choice, reasoning_effort=reasoning_effort or "low",
            response_format=response_format,
        )
        if stream:
            return _stream(client, request)
        result = await client.complete(request)
        if not result.choices:
            raise InceptionError("Inception API returned no completion choice")
        finish_reason = result.choices[0].get("finish_reason")
        if finish_reason not in {"stop", "tool_calls", "length"}:
            raise InceptionError("Inception completion was blocked or unsupported")
        message = result.choices[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if finish_reason == "length" and calls:
            raise InceptionError("Inception tool call exceeded its output limit")
        content = message.get("content")
        if not content and not calls:
            raise InceptionError("Inception completion returned no output")
        if finish_reason == "length":
            content = (content or "") + TRUNCATION_NOTICE
        usage = _usage(result)
        return UnifiedOpenAIResponse(
            task_id=task_id, model_id=model_id, success=True,
            direct_message_content=content,
            tool_calls_made=[_tool(call) for call in calls] or None, usage=usage,
            raw_response=RawOpenAIChatCompletionResponse(
                text=message.get("content"), tool_calls=calls or None, usage_metadata=usage,
            ),
        )
    except (InceptionError, ValueError, TypeError) as exc:
        if stream:
            raise InceptionError(
                "Inception request could not be completed",
                kind=exc.kind if isinstance(exc, InceptionError) else "invalid_response",
                status_code=exc.status_code if isinstance(exc, InceptionError) else None,
            ) from None
        error_message = "Inception request could not be completed"
        if isinstance(exc, InceptionError):
            if exc.kind == "http" and exc.status_code is not None:
                error_message = f"Inception API HTTP {exc.status_code}"
            elif exc.kind == "timeout":
                error_message = "Inception API timeout"
            elif exc.kind == "transport":
                error_message = "Inception API transport failure"
            elif exc.kind == "invalid_response":
                error_message = "Inception API returned an invalid response"
        return UnifiedOpenAIResponse(
            task_id=task_id, model_id=model_id, success=False,
            error_message=error_message,
        )
