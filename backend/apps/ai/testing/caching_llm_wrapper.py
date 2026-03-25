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
import json
import logging
from typing import Any, AsyncIterator, Callable, List

from backend.shared.testing.api_response_cache import (
    ApiResponseCache,
    MockCacheMiss,
)
from backend.shared.testing.mock_context import (
    get_mock_group,
    is_mock_active,
    is_record_mode,
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
    async def _cached_stream(**kwargs: Any) -> AsyncIterator[str]:
        if not is_mock_active():
            async for chunk in provider_fn(**kwargs):
                yield chunk
            return

        group_id = get_mock_group()
        model = kwargs.get("model", "unknown")
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

        # Try cache first
        cached = cache.load(group_id, category, fingerprint)
        if cached is not None:
            response_data = cached.get("response", {})
            response_body = response_data.get("body", "")
            response_type = response_data.get("type", "stream")

            if response_type == "structured":
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
        logger.info(
            f"[LiveMock] LLM Cache MISS (recording): {category}/{fingerprint} "
            f"— model={model}, messages={len(messages)}"
        )

        all_chunks: List[str] = []
        async for chunk in provider_fn(**kwargs):
            all_chunks.append(chunk)
            yield chunk

        _save_to_cache(cache, group_id, category, fingerprint, all_chunks, kwargs)

    # Non-streaming wrapper (regular coroutine — returns awaitable result)
    async def _cached_non_stream(**kwargs: Any) -> Any:
        if not is_mock_active():
            return await provider_fn(**kwargs)

        # Mock/record mode with stream=False: not supported yet, fall through to real provider
        logger.debug("[LiveMock] Non-streaming mock not implemented, calling real provider")
        return await provider_fn(**kwargs)

    # Dispatcher: returns the right type based on stream kwarg.
    # When stream=False, provider returns a regular awaitable (UnifiedResponse).
    # When stream=True (default), provider returns an async iterator of chunks.
    # The dispatcher preserves this contract so health checks (stream=False) can await.
    def cached_provider(**kwargs: Any) -> Any:
        if kwargs.get("stream", True):
            return _cached_stream(**kwargs)
        return _cached_non_stream(**kwargs)

    return cached_provider


def _save_to_cache(
    cache: ApiResponseCache,
    group_id: str,
    category: str,
    fingerprint: str,
    all_chunks: List[str],
    kwargs: dict,
) -> None:
    """Save collected LLM response chunks to the cache for future replay."""
    full_response = "".join(all_chunks)

    # Determine response type
    response_type = "stream"
    try:
        parsed = json.loads(full_response)
        if isinstance(parsed, dict) and ("tool_calls" in parsed or "function_call" in parsed):
            response_type = "structured"
    except (json.JSONDecodeError, TypeError):
        pass

    # Build request summary for debugging
    messages = kwargs.get("messages", [])
    tools = kwargs.get("tools")
    request_summary: dict = {
        "model": kwargs.get("model", "unknown"),
        "messages_count": len(messages),
        "tools_count": len(tools) if tools else 0,
        "temperature": kwargs.get("temperature"),
        "tool_choice": kwargs.get("tool_choice"),
    }
    if messages:
        last_msg = messages[-1]
        content = last_msg.get("content", "")
        if isinstance(content, str) and len(content) > 200:
            content = content[:200] + "..."
        request_summary["last_message_preview"] = {
            "role": last_msg.get("role", ""),
            "content": content,
        }

    response_data = {
        "type": response_type,
        "body": full_response,
        "chunk_count": len(all_chunks),
    }

    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary=request_summary,
        response_data=response_data,
    )


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
