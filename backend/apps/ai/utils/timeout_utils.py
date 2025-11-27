# backend/apps/ai/utils/timeout_utils.py
# Timeout utilities for LLM stream operations.

import asyncio
import logging
from typing import AsyncIterator, TypeVar, Optional

logger = logging.getLogger(__name__)

# Hardcoded timeout for first chunk (10000ms = 10 seconds)
# This is used for streaming requests to detect if the stream is alive
FIRST_CHUNK_TIMEOUT_MS = 10000
FIRST_CHUNK_TIMEOUT_SECONDS = FIRST_CHUNK_TIMEOUT_MS / 1000.0

# Timeout for non-streaming preprocessing requests (10 seconds)
# Preprocessing requests should complete quickly; if they take longer, the provider is likely having issues
PREPROCESSING_TIMEOUT_SECONDS = 10.0

T = TypeVar('T')


async def stream_with_first_chunk_timeout(
    stream: AsyncIterator[T],
    timeout_seconds: float = FIRST_CHUNK_TIMEOUT_SECONDS
) -> AsyncIterator[T]:
    """
    Wrap an async stream iterator with a timeout for the first chunk.
    
    If the first chunk is not received within the timeout period, raises TimeoutError.
    Subsequent chunks are not subject to the timeout.
    
    Args:
        stream: Async iterator to wrap
        timeout_seconds: Timeout in seconds for the first chunk (default: 5.0)
    
    Yields:
        Items from the stream
    
    Raises:
        TimeoutError: If first chunk is not received within timeout
    """
    first_chunk_received = False
    
    async def get_first_chunk():
        """Helper to get first chunk with timeout"""
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
        first_chunk = await asyncio.wait_for(get_first_chunk(), timeout=timeout_seconds)
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
    
    # After first chunk, yield remaining chunks without timeout
    try:
        async for chunk in stream:
            yield chunk
    except StopAsyncIteration:
        # Stream ended - this is normal
        return

