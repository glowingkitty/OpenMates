# backend/apps/ai/utils/timeout_utils.py
# Timeout utilities for LLM stream operations.
#
# This module provides timeout protection for LLM streaming operations to prevent:
# 1. Dead streams where the provider never starts sending (first-chunk timeout)
# 2. Hung streams where the provider stops sending mid-stream (inter-chunk timeout)
#
# Both scenarios can cause tasks to hang indefinitely, blocking resources and
# leaving users without responses.

import asyncio
import logging
import os
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
# Reasoning models (like o1, thinking models) may take 30-60+ seconds to start.
REASONING_FIRST_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_REASONING_FIRST_CHUNK_TIMEOUT_SECONDS", 60.0)

# Inter-chunk timeout (in seconds).
# Used to detect hung streams where the provider stops sending mid-stream.
# This is more generous than first-chunk timeout because some providers have
# variable latency between chunks, especially during complex generation.
# Default: 30 seconds - if no chunk is received within 30s, the stream is likely dead.
INTER_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_INTER_CHUNK_TIMEOUT_SECONDS", 30.0)

# Inter-chunk timeout for reasoning models (in seconds).
# Reasoning models may have longer pauses between chunks as they "think".
REASONING_INTER_CHUNK_TIMEOUT_SECONDS = _get_env_float("AI_REASONING_INTER_CHUNK_TIMEOUT_SECONDS", 90.0)


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
    Wrap an async stream iterator with timeout protection.
    
    Provides two levels of timeout protection:
    1. First-chunk timeout: Detects dead streams where provider never starts sending
    2. Inter-chunk timeout: Detects hung streams where provider stops mid-stream
    
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
        yield first_chunk
    except asyncio.TimeoutError:
        if not first_chunk_received:
            logger.error(f"Stream timeout: First chunk not received within {timeout_seconds}s")
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
        logger.debug(f"Stream completed successfully after {chunk_count} chunks")
        return
