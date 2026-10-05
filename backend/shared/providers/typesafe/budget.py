"""Conservative Jev input estimates; these are not Jev's native token counts."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Mapping


OPENROUTER_CONTEXT_TOKENS = 32_000
MAX_ESTIMATED_INPUT_TOKENS = 30_000
REQUEST_OVERHEAD_TOKENS = 256
TOKENIZER_CHUNK_CHARS = 512
_sizing_cache: ContextVar[dict[str, int] | None] = ContextVar("jev_sizing_cache", default=None)


@lru_cache(maxsize=1)
def _encodings() -> tuple[Any, ...]:
    # Cache tokenizer tables only, never private request text. Both encodings
    # are proxies: OpenRouter does not publish Jev's native tokenizer.
    import tiktoken

    return tuple(tiktoken.get_encoding(name) for name in ("cl100k_base", "o200k_base"))


def serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def estimate_text_tokens(text: str) -> int:
    """Use the larger proxy count, including literal special-token strings."""
    cache = _sizing_cache.get()
    if cache is not None and text in cache:
        return cache[text]
    # BPE encoders can take quadratic time on long repeated strings. Bound each
    # encoding operation and count the fragments, retaining the proxy headroom.
    if len(text) > TOKENIZER_CHUNK_CHARS:
        count = sum(estimate_text_tokens(text[index:index + TOKENIZER_CHUNK_CHARS])
                    for index in range(0, len(text), TOKENIZER_CHUNK_CHARS))
    else:
        count = max(len(encoding.encode(text, disallowed_special=())) for encoding in _encodings())
    if cache is not None and len(cache) < 256:
        cache[text] = count
    return count


@contextmanager
def sizing_cache():
    """Reuse estimates only during one synchronous packing operation."""
    token = _sizing_cache.set({})
    try:
        yield
    finally:
        _sizing_cache.reset(token)


def estimate_request_tokens(state: Any, questions: Mapping[str, Mapping[str, Any]]) -> int:
    """Include all state, question IDs, instructions, criteria and framing.

    Counting fragments separately also lets packers reuse the shared-state
    estimate. The headroom covers proxy-tokenizer and provider-format uncertainty.
    """
    return (REQUEST_OVERHEAD_TOKENS + estimate_text_tokens(serialize(state))
            + sum(estimate_text_tokens(serialize({key: question}))
                  for key, question in questions.items()))
