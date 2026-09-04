# backend/apps/ai/testing/caching_llm_wrapper.py
# Wraps LLM provider functions with record-and-replay caching for live mock testing.
#
# When live mock mode is active (per-request via contextvars), this wrapper
# intercepts LLM provider calls and either replays cached responses as simulated
# streams or records real responses for future replay.
#
# When mock mode is NOT active (regular user requests), all calls pass through
# to the real provider with zero overhead beyond a single contextvar check.
#
# Security: Only loaded when MOCK_EXTERNAL_APIS=true env var is set.
#
# Architecture context: See docs/architecture/live-mock-testing.md

import asyncio
import hashlib
import inspect
import importlib
import json
import logging
from typing import Any, AsyncIterator, Callable, List

from backend.shared.testing.api_response_cache import (
    ApiResponseCache,
    MockCacheMiss,
)
from backend.shared.testing.mock_context import (
    MAX_REAL_LLM_OUTPUT_TOKENS,
    conservative_llm_reservation_eur,
    get_mock_group,
    is_mock_active,
    is_real_mode,
    is_record_mode,
    record_cache_miss,
    record_real_provider_call,
    reserve_real_provider_call,
)

logger = logging.getLogger(__name__)

# Speed profiles for stream simulation (reuse from mock_replay.py)
# Maps profile name to inter-chunk delay in seconds
STREAM_SPEED_PROFILES = {
    "instant": 0,       # No delay — fastest test execution
    "fast": 0.005,      # ~500 tokens/s
    "medium": 0.020,    # ~150 tokens/s
    "slow": 0.050,      # ~60 tokens/s
}
DEFAULT_STREAM_SPEED = "instant"

# Average characters per simulated chunk
CHARS_PER_CHUNK = 20

MIXED_STREAM_RESPONSE_TYPE = "mixed_stream"
NON_STREAM_RESPONSE_TYPE = "non_stream"
STREAM_CHUNK_FORMAT_VERSION = 1

def wrap_provider_with_cache(
    provider_fn: Callable,
    cache: ApiResponseCache,
) -> Callable:
    """
    Wrap an LLM provider function (invoke_{server_id}_chat_completions) with caching.

    The wrapped function:
    - If mock mode is OFF: calls the real provider directly (zero overhead).
    - If mode is "mock": returns cached response as simulated stream or raises MockCacheMiss.
    - If mode is "record": calls real provider, records full response, returns it.

    Provider functions are async generators that yield string chunks.
    The wrapper collects all chunks during recording and replays them during mocking.

    Args:
        provider_fn: The original invoke_{server_id}_chat_completions function
        cache: Shared ApiResponseCache instance
    """

    # Streaming wrapper (async generator — uses yield)
    async def _cached_stream(**kwargs: Any) -> AsyncIterator[Any]:
        if not is_mock_active():
            async for chunk in _provider_stream(**kwargs):
                yield chunk
            return

        if is_real_mode():
            await _reserve_real_llm_call(kwargs, "llm")
            record_real_provider_call()
            async for chunk in _provider_stream(**kwargs):
                yield chunk
            return

        group_id = get_mock_group()
        model = _model_from_kwargs(kwargs)
        category = f"llm/{model}"

        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools")
        temperature = kwargs.get("temperature")
        tool_choice = kwargs.get("tool_choice")

        fingerprint = cache.fingerprint_llm_call(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            tool_choice=tool_choice,
        )
        # Recording always captures a fresh live response and never reads cassettes.
        cached = None if is_record_mode() else cache.load(group_id, category, fingerprint)
        if cached is not None:
            response_data = cached.get("response", {})
            response_body = response_data.get("body", "")
            response_type = response_data.get("type", "stream")

            if response_type == MIXED_STREAM_RESPONSE_TYPE:
                for chunk in _deserialize_stream_chunks(response_data.get("chunks", [])):
                    yield chunk
            elif response_type == "structured":
                yield response_body
            else:
                delay = STREAM_SPEED_PROFILES.get(DEFAULT_STREAM_SPEED, 0)
                for chunk in _split_into_chunks(response_body, CHARS_PER_CHUNK):
                    yield chunk
                    if delay > 0:
                        await asyncio.sleep(delay)
            return

        # Cache miss
        if not is_record_mode():
            raise MockCacheMiss(
                category=category,
                fingerprint=fingerprint,
                details=f"model={model}, messages={len(messages)}",
            )

        # Record mode: call real provider, collect all chunks, save to cache
        record_cache_miss()
        await _reserve_real_llm_call(kwargs, "llm")
        record_real_provider_call()
        logger.info(
            f"[LiveMock] LLM Cache MISS (recording): {category}/{fingerprint} "
            f"— model={model}, messages={len(messages)}"
        )

        all_chunks: List[Any] = []
        async for chunk in _provider_stream(**kwargs):
            all_chunks.append(chunk)
            yield chunk

        _save_to_cache(cache, group_id, category, fingerprint, all_chunks, kwargs)

    async def _provider_stream(**kwargs: Any) -> AsyncIterator[Any]:
        stream = provider_fn(**kwargs)
        if inspect.isawaitable(stream):
            stream = await stream
        async for chunk in stream:
            yield chunk

    # Non-streaming wrapper (regular coroutine — returns awaitable result)
    async def _cached_non_stream(**kwargs: Any) -> Any:
        if not is_mock_active():
            return await provider_fn(**kwargs)

        if is_real_mode():
            await _reserve_real_llm_call(kwargs, "llm_non_stream")
            record_real_provider_call()
            return await provider_fn(**kwargs)

        group_id = get_mock_group()
        model = _model_from_kwargs(kwargs)
        category = f"llm_non_stream/{model}"
        messages = kwargs.get("messages", [])
        fingerprint = cache.fingerprint_llm_call(
            model=model,
            messages=messages,
            tools=kwargs.get("tools"),
            temperature=kwargs.get("temperature"),
            tool_choice=kwargs.get("tool_choice"),
        )
        cached = None if is_record_mode() else cache.load(group_id, category, fingerprint)
        if cached is not None:
            return _deserialize_non_stream_response(cached.get("response", {}))

        if not is_record_mode():
            raise MockCacheMiss(
                category=category,
                fingerprint=fingerprint,
                details=f"model={model}, messages={len(messages)}",
            )

        record_cache_miss()
        await _reserve_real_llm_call(kwargs, "llm_non_stream")
        record_real_provider_call()
        response = await provider_fn(**kwargs)
        _save_non_stream_to_cache(cache, group_id, category, fingerprint, response, kwargs)
        return response

    # Dispatcher: provider clients are awaited by llm_utils. Streaming calls must
    # therefore resolve to an async iterator after the await, not return one directly.
    async def cached_provider(**kwargs: Any) -> Any:
        if kwargs.get("stream", True):
            return _cached_stream(**kwargs)
        return await _cached_non_stream(**kwargs)

    setattr(cached_provider, "_live_mock_cache_wrapped", True)
    setattr(cached_provider, "_live_mock_original_provider", provider_fn)
    return cached_provider

def _save_to_cache(
    cache: ApiResponseCache,
    group_id: str,
    category: str,
    fingerprint: str,
    all_chunks: List[Any],
    kwargs: dict,
) -> None:
    """Save collected LLM response chunks to the cache for future replay."""
    text_chunks = [chunk for chunk in all_chunks if isinstance(chunk, str)]
    full_response = "".join(text_chunks)

    # Determine response type
    response_type = "stream"
    try:
        parsed = json.loads(full_response)
        if isinstance(parsed, dict) and ("tool_calls" in parsed or "function_call" in parsed):
            response_type = "structured"
    except (json.JSONDecodeError, TypeError):
        pass

    request_summary = _build_llm_request_summary(kwargs, _model_from_kwargs(kwargs))

    response_data = {
        "type": response_type,
        "body": full_response,
        "chunk_count": len(all_chunks),
    }

    if len(text_chunks) != len(all_chunks):
        response_data = {
            "type": MIXED_STREAM_RESPONSE_TYPE,
            "body": full_response,
            "chunk_count": len(all_chunks),
            "chunk_format_version": STREAM_CHUNK_FORMAT_VERSION,
            "chunks": [_serialize_stream_chunk(chunk) for chunk in all_chunks],
        }

    _save_cache_entry(
        cache,
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary=request_summary,
        response_data=response_data,
    )


def _save_non_stream_to_cache(
    cache: ApiResponseCache,
    group_id: str,
    category: str,
    fingerprint: str,
    response: Any,
    kwargs: dict,
) -> None:
    request_summary = _build_llm_request_summary(kwargs, _model_from_kwargs(kwargs))
    _save_cache_entry(
        cache,
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary=request_summary,
        response_data={
            "type": NON_STREAM_RESPONSE_TYPE,
            "value": _serialize_stream_chunk(response),
        },
    )


def _save_cache_entry(
    cache: ApiResponseCache,
    *,
    group_id: str,
    category: str,
    fingerprint: str,
    request_summary: dict[str, Any],
    response_data: dict[str, Any],
) -> None:
    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary=request_summary,
        response_data=response_data,
    )


def _deserialize_non_stream_response(response_data: Any) -> Any:
    if not isinstance(response_data, dict) or response_data.get("type") != NON_STREAM_RESPONSE_TYPE:
        logger.warning("[LiveMock] Non-streaming LLM cache entry has unsupported response data")
        return None
    return _deserialize_stream_chunk(response_data.get("value"))


def _split_into_chunks(text: str, chunk_size: int) -> List[str]:
    """
    Split text into chunks for stream simulation.

    Tries to split at word/sentence boundaries for natural-looking streaming.
    Falls back to fixed-size chunks if text has no natural break points.
    """
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + chunk_size, len(text))

        # Try to find a natural break point (space, period, newline)
        if end < len(text):
            # Look for break points within the chunk
            for break_char in ["\n", ". ", " "]:
                break_pos = text.rfind(break_char, pos, end + 5)
                if break_pos > pos:
                    end = break_pos + len(break_char)
                    break

        chunks.append(text[pos:end])
        pos = end

    return chunks


def _serialize_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Convert a streamed provider chunk into JSON-safe cache data."""
    if isinstance(chunk, str):
        return {"kind": "text", "value": chunk}

    if isinstance(chunk, dict):
        return {"kind": "json", "value": _json_safe(chunk)}

    class_name = chunk.__class__.__name__
    module_name = chunk.__class__.__module__

    if hasattr(chunk, "model_dump") or hasattr(chunk, "json"):
        value = _model_to_jsonable_dict(chunk)
        tool_call = getattr(chunk, "tool_call", None)
        if tool_call is not None:
            value["tool_call"] = _serialize_stream_chunk(tool_call)
        return {
            "kind": "pydantic",
            "module": module_name,
            "class": class_name,
            "value": value,
        }

    return {
        "kind": "repr",
        "module": module_name,
        "class": class_name,
        "value": str(chunk),
    }


def _deserialize_stream_chunks(chunks: Any) -> List[Any]:
    """Restore cached mixed stream chunks in provider order."""
    if not isinstance(chunks, list):
        logger.warning("[LiveMock] Mixed LLM cache entry has no chunk list; replaying empty stream")
        return []
    return [_deserialize_stream_chunk(chunk) for chunk in chunks]


def _deserialize_stream_chunk(chunk_data: Any) -> Any:
    if not isinstance(chunk_data, dict):
        return chunk_data

    kind = chunk_data.get("kind")
    if kind == "text":
        return chunk_data.get("value", "")
    if kind == "json":
        return chunk_data.get("value")
    if kind == "pydantic":
        value = chunk_data.get("value", {})
        if not isinstance(value, dict):
            value = {}

        if isinstance(value.get("tool_call"), dict):
            value = dict(value)
            value["tool_call"] = _deserialize_stream_chunk(value["tool_call"])

        chunk_class = _load_chunk_class(chunk_data.get("module"), chunk_data.get("class"))
        if chunk_class is None:
            return _deserialize_portable_provider_chunk(chunk_data.get("class"), value)

        try:
            if hasattr(chunk_class, "model_validate"):
                return chunk_class.model_validate(value)
            if hasattr(chunk_class, "parse_obj"):
                return chunk_class.parse_obj(value)
            return chunk_class(**value)
        except Exception as exc:
            logger.warning(
                "[LiveMock] Failed to rebuild cached %s.%s chunk: %s",
                chunk_data.get("module"),
                chunk_data.get("class"),
                exc,
            )
            return value

    if kind == "repr":
        return chunk_data.get("value", "")
    return chunk_data


def _deserialize_portable_provider_chunk(class_name: Any, value: dict[str, Any]) -> Any:
    """Restore provider chunks when optional provider modules are unavailable.

    Some cached Gemini chunks point at google_client.py, which imports optional
    provider dependencies that are not present in every test runtime. Replay only
    needs the common tool-call/usage attributes, so map those chunks to the
    shared OpenAI-compatible models instead of returning plain dicts.
    """
    if not isinstance(class_name, str):
        return value

    try:
        from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata, ParsedOpenAIToolCall
        from pydantic import BaseModel

        class PortableParsedToolCall(ParsedOpenAIToolCall):
            thought_signature: str | None = None

        class PortableUnifiedProviderResponse(BaseModel):
            task_id: str = ""
            model_id: str = ""
            success: bool = False
            error_message: str | None = None
            direct_message_content: str | None = None
            tool_calls_made: list[PortableParsedToolCall] | None = None
            usage: Any | None = None
            raw_response: Any | None = None

        if class_name.startswith("Parsed") and class_name.endswith("ToolCall"):
            required = {"tool_call_id", "function_name", "function_arguments_raw", "function_arguments_parsed"}
            if required.issubset(value):
                return PortableParsedToolCall.model_validate(value)

        if class_name.startswith("Unified") and class_name.endswith("Response"):
            response_value = dict(value)
            tool_calls = response_value.get("tool_calls_made")
            if isinstance(tool_calls, list):
                response_value["tool_calls_made"] = [
                    PortableParsedToolCall.model_validate(tool_call)
                    for tool_call in tool_calls
                    if isinstance(tool_call, dict)
                ]
            return PortableUnifiedProviderResponse.model_validate(response_value)

        if class_name == "GoogleUsageMetadata":
            return OpenAIUsageMetadata(
                input_tokens=int(value.get("prompt_token_count") or 0),
                output_tokens=int(value.get("candidates_token_count") or 0),
                total_tokens=int(value.get("total_token_count") or 0),
                user_input_tokens=value.get("user_input_tokens"),
                system_prompt_tokens=value.get("system_prompt_tokens"),
            )
    except Exception as exc:
        logger.warning("[LiveMock] Failed to rebuild portable cached chunk %s: %s", class_name, exc)

    return value


def _model_to_jsonable_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        try:
            return model.model_dump(mode="json")
        except TypeError:
            return _json_safe(model.model_dump())

    if hasattr(model, "json"):
        return json.loads(model.json())

    if hasattr(model, "dict"):
        return _json_safe(model.dict())

    return _json_safe(model)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _load_chunk_class(module_name: Any, class_name: Any) -> Any:
    if not isinstance(module_name, str) or not isinstance(class_name, str):
        return None
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name, None)
    except Exception as exc:
        logger.warning("[LiveMock] Failed to import cached chunk class %s.%s: %s", module_name, class_name, exc)
        return None


def _model_from_kwargs(kwargs: dict[str, Any]) -> str:
    """Return the provider model name regardless of the caller's parameter spelling."""
    model = kwargs.get("model") or kwargs.get("model_id") or "unknown"
    return str(model)


async def _reserve_real_llm_call(kwargs: dict[str, Any], category_prefix: str) -> str:
    model = _model_from_kwargs(kwargs)
    requested_max_tokens = kwargs.get("max_tokens")
    kwargs["max_tokens"] = min(
        requested_max_tokens
        if isinstance(requested_max_tokens, int) and requested_max_tokens > 0
        else MAX_REAL_LLM_OUTPUT_TOKENS,
        MAX_REAL_LLM_OUTPUT_TOKENS,
    )
    request_input_token_upper_bound = _real_request_input_token_upper_bound(kwargs)
    reservation = conservative_llm_reservation_eur(
        model,
        input_token_upper_bound=request_input_token_upper_bound,
        max_output_tokens=kwargs["max_tokens"],
    )
    await reserve_real_provider_call(f"{category_prefix}/{model}", reservation)
    return model


def _real_request_input_token_upper_bound(kwargs: dict[str, Any]) -> int:
    return len(
        json.dumps(
            {"messages": kwargs.get("messages", []), "tools": kwargs.get("tools")},
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    )


def _build_llm_request_summary(kwargs: dict[str, Any], model: str) -> dict[str, Any]:
    messages = kwargs.get("messages", [])
    tools = kwargs.get("tools")
    request_summary: dict[str, Any] = {
        "model": model,
        "messages_count": len(messages),
        "tools_count": len(tools) if tools else 0,
        "temperature": kwargs.get("temperature"),
        "tool_choice": kwargs.get("tool_choice"),
    }
    tool_names = _tool_function_names(tools)
    if tool_names:
        request_summary["tool_names"] = tool_names
    if messages:
        last_msg = messages[-1]
        content = last_msg.get("content", "")
        canonical_content = ApiResponseCache._normalize_llm_text_for_match(content)
        canonical_last_message = json.dumps(
            {"role": last_msg.get("role", ""), "content": canonical_content},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        request_summary["last_message_hash"] = hashlib.sha256(
            canonical_last_message.encode("utf-8")
        ).hexdigest()[:16]
        if isinstance(canonical_content, str):
            content = canonical_content
        if isinstance(content, str) and len(content) > 200:
            content = content[:200] + "..."
        request_summary["last_message_preview"] = {
            "role": last_msg.get("role", ""),
            "content": content,
        }
    return request_summary


def _tool_function_names(tools: Any) -> list[str]:
    """Return stable function names for cache compatibility matching."""
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function_def = tool.get("function")
        if not isinstance(function_def, dict):
            continue
        name = function_def.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names
