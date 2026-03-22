# backend/apps/ai/utils/timeout_utils.py
# Timeout utilities for LLM stream operations.
#
# This module provides timeout protection for LLM streaming operations to prevent:
# 1. Dead streams where the provider never starts sending (first-chunk timeout)
# 2. Hung streams where the provider stops sending mid-stream (inter-chunk timeout)
#
# Both scenarios can cause tasks to hang indefinitely, blocking resources and
# leaving users without responses.
#
# When a timeout fires on the first chunk, call_main_llm_stream() catches the
# TimeoutError and automatically falls through to the next server in the fallback
# chain (e.g., Google AI Studio → Vertex AI → OpenRouter).  This makes timeouts
# a lightweight provider-health signal: a provider that can't start in time is
# treated the same as a hard 5xx error and we move on immediately.
#
# TTFT (Time To First Token) instrumentation:
# stream_with_first_chunk_timeout() measures and logs the actual elapsed time
# between stream creation and the first chunk arrival.  This gives us concrete
# data on provider latency for alerting and debugging.

import asyncio
import logging
import os
import time
from typing import AsyncIterator, TypeVar, Optional

logger = logging.getLogger(__name__)


def _get_env_float(name: str, default: float) -> float:
    """
    Get a float value from environment variable with fallback to default.
    
    Args:
        name: Environment variable name
        default: Default value if env var is not set or invalid
    
    Returns:
        Float value from env var or default
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"Invalid env var {name}={raw!r}; using default {default}")
        return default


# Default timeout for first streamed chunk (in seconds).
# Used to detect "dead" streams where the provider never starts sending.
FIRST_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_FIRST_CHUNK_TIMEOUT_SECONDS", 10.0)

# Timeout for reasoning models where the provider may take longer to start streaming.
# Even the heaviest reasoning models (o1, DeepSeek R1, Gemini thinking) typically
# start yielding thinking tokens within 3–12 seconds under normal load.  We allow
# 15 s, giving 2–3× headroom for burst traffic.  If a provider can't begin
# streaming in 15 s it is almost certainly experiencing an outage or severe
# throttling — we should fall through to the next server rather than waiting.
#
# This intentionally replaces the previous 60 s value which was far too generous:
# 43–91 s TTFTs were observed for Gemini 3.1 Pro Preview on Google AI Studio
# during periods of instability, and the 60 s limit failed to trigger a fallback.
#
# Override via env: AI_REASONING_FIRST_CHUNK_TIMEOUT_SECONDS
REASONING_FIRST_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_REASONING_FIRST_CHUNK_TIMEOUT_SECONDS", 15.0)

# Inter-chunk timeout (in seconds).
# Used to detect hung streams where the provider stops sending mid-stream.
# Default: 30 seconds - if no chunk is received within 30s, the stream is likely dead.
INTER_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_INTER_CHUNK_TIMEOUT_SECONDS", 30.0)

# Inter-chunk timeout for reasoning models (in seconds).
# Reasoning models may have longer pauses between chunks as they "think".
# Reduced from 90 s to 45 s — a 45-second pause mid-stream is still unusual
# and almost certainly indicates a hung connection rather than normal thinking.
#
# Override via env: AI_REASONING_INTER_CHUNK_TIMEOUT_SECONDS
REASONING_INTER_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_REASONING_INTER_CHUNK_TIMEOUT_SECONDS", 45.0)


def get_first_chunk_timeout_seconds(*, is_reasoning: bool = False) -> float:
    """
    Resolve first-chunk streaming timeout for a given provider/model.

    Env vars:
      - AI_FIRST_CHUNK_TIMEOUT_SECONDS (global default, seconds)
      - AI_REASONING_FIRST_CHUNK_TIMEOUT_SECONDS (reasoning models, seconds)
    
    Args:
        is_reasoning: Whether this is a reasoning model (longer timeout)
    
    Returns:
        Timeout in seconds for first chunk
    """
    return REASONING_FIRST_CHUNK_TIMEOUT_SECONDS if is_reasoning else FIRST_CHUNK_TIMEOUT_SECONDS


def get_inter_chunk_timeout_seconds(*, is_reasoning: bool = False) -> float:
    """
    Resolve inter-chunk streaming timeout for a given provider/model.
    
    This timeout applies to each subsequent chunk after the first.
    It prevents hung streams where the provider stops sending mid-stream.

    Env vars:
      - AI_INTER_CHUNK_TIMEOUT_SECONDS (global default, seconds)
      - AI_REASONING_INTER_CHUNK_TIMEOUT_SECONDS (reasoning models, seconds)
    
    Args:
        is_reasoning: Whether this is a reasoning model (longer timeout)
    
    Returns:
        Timeout in seconds for inter-chunk waiting
    """
    return REASONING_INTER_CHUNK_TIMEOUT_SECONDS if is_reasoning else INTER_CHUNK_TIMEOUT_SECONDS


# Timeout for non-streaming preprocessing requests (10 seconds)
# Preprocessing requests should complete quickly; if they take longer, the provider is likely having issues
PREPROCESSING_TIMEOUT_SECONDS = 10.0

T = TypeVar('T')


async def stream_with_first_chunk_timeout(
    stream: AsyncIterator[T],
    timeout_seconds: float = FIRST_CHUNK_TIMEOUT_SECONDS,
    inter_chunk_timeout_seconds: Optional[float] = None
) -> AsyncIterator[T]:
    """
    Wrap an async stream iterator with timeout protection and TTFT instrumentation.
    
    Provides two levels of timeout protection:
    1. First-chunk timeout: Detects dead streams where provider never starts sending
    2. Inter-chunk timeout: Detects hung streams where provider stops mid-stream
    
    Additionally, measures and logs the actual TTFT (Time To First Token) — the
    elapsed wall-clock time between stream creation and first chunk arrival.  This
    gives operational visibility into provider latency without any additional code
    in the provider clients.
    
    Args:
        stream: Async iterator to wrap
        timeout_seconds: Timeout in seconds for the first chunk (default: AI_FIRST_CHUNK_TIMEOUT_SECONDS or 10.0)
        inter_chunk_timeout_seconds: Timeout in seconds for each subsequent chunk.
                                     If None, uses AI_INTER_CHUNK_TIMEOUT_SECONDS (default: 30.0).
                                     Set to 0 or negative to disable inter-chunk timeout.
    
    Yields:
        Items from the stream
    
    Raises:
        TimeoutError: If first chunk is not received within timeout, or
                      if any subsequent chunk is not received within inter-chunk timeout
    """
    first_chunk_received = False
    stream_start_time = time.monotonic()
    
    # Resolve inter-chunk timeout
    # Use default if not specified, disable if 0 or negative
    effective_inter_chunk_timeout = inter_chunk_timeout_seconds
    if effective_inter_chunk_timeout is None:
        effective_inter_chunk_timeout = INTER_CHUNK_TIMEOUT_SECONDS
    enable_inter_chunk_timeout = effective_inter_chunk_timeout > 0
    
    async def get_next_chunk():
        """Helper to get next chunk from stream"""
        nonlocal first_chunk_received
        try:
            chunk = await stream.__anext__()
            first_chunk_received = True
            return chunk
        except StopAsyncIteration:
            first_chunk_received = True
            raise
    
    # Wait for first chunk with timeout
    try:
        first_chunk = await asyncio.wait_for(get_next_chunk(), timeout=timeout_seconds)
        
        # TTFT instrumentation: measure and log actual time-to-first-token
        ttft_seconds = time.monotonic() - stream_start_time
        logger.info(
            f"Stream TTFT: first chunk received in {ttft_seconds:.2f}s "
            f"(timeout was {timeout_seconds:.1f}s)"
        )
        
        yield first_chunk
    except asyncio.TimeoutError:
        if not first_chunk_received:
            elapsed = time.monotonic() - stream_start_time
            logger.error(
                f"Stream timeout: First chunk not received within {timeout_seconds}s "
                f"(elapsed: {elapsed:.2f}s). Provider is likely overloaded or down."
            )
            raise TimeoutError(f"Stream did not produce first chunk within {timeout_seconds} seconds")
        else:
            # This shouldn't happen, but handle gracefully
            raise
    except StopAsyncIteration:
        # Stream ended immediately - this is fine, just don't yield anything
        return
    
    # After first chunk, yield remaining chunks WITH inter-chunk timeout
    chunk_count = 1  # Already received first chunk
    try:
        while True:
            try:
                if enable_inter_chunk_timeout:
                    # Wait for next chunk with inter-chunk timeout
                    chunk = await asyncio.wait_for(
                        get_next_chunk(),
                        timeout=effective_inter_chunk_timeout
                    )
                else:
                    # No inter-chunk timeout - wait indefinitely (legacy behavior)
                    chunk = await get_next_chunk()
                
                chunk_count += 1
                yield chunk
                
            except asyncio.TimeoutError:
                # Inter-chunk timeout exceeded - stream is likely hung
                logger.error(
                    f"Stream timeout: No chunk received within {effective_inter_chunk_timeout}s "
                    f"after chunk #{chunk_count}. Stream appears to be hung."
                )
                raise TimeoutError(
                    f"Stream hung: No chunk received within {effective_inter_chunk_timeout} seconds "
                    f"after {chunk_count} chunks"
                )
                
    except StopAsyncIteration:
        # Stream ended normally
        total_elapsed = time.monotonic() - stream_start_time
        logger.debug(
            f"Stream completed successfully after {chunk_count} chunks "
            f"(total stream duration: {total_elapsed:.2f}s)"
        )
        return
