"""
Purpose: Read input and output token counts from the usage chunk of an LLM stream, whatever provider sent it.
Architecture: App skill authors (vector images, images.modify, composed videos) meter their own model calls
    for billing; providers report usage in different shapes, and a shape that is not read is billed as zero.
Shapes: OpenAI and Anthropic style objects carry ``input_tokens`` / ``output_tokens``. Google objects carry
    ``prompt_token_count`` / ``candidates_token_count`` plus ``thoughts_token_count``; Google bills thinking
    tokens as output, so they are added to the output count.
Tests: backend/tests/test_llm_stream_usage.py
"""

from __future__ import annotations

from typing import Any, Optional


def _count(chunk: Any, name: str) -> int:
    value = getattr(chunk, name, None)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def stream_usage_tokens(chunk: Any) -> Optional[tuple[int, int]]:
    """Return ``(input_tokens, output_tokens)`` of a usage chunk, or None when ``chunk`` is not one."""
    if isinstance(chunk, str):
        return None
    if hasattr(chunk, "input_tokens") and hasattr(chunk, "output_tokens"):
        return _count(chunk, "input_tokens"), _count(chunk, "output_tokens")
    if hasattr(chunk, "prompt_token_count") and hasattr(chunk, "candidates_token_count"):
        return (_count(chunk, "prompt_token_count"),
                _count(chunk, "candidates_token_count") + _count(chunk, "thoughts_token_count"))
    return None
