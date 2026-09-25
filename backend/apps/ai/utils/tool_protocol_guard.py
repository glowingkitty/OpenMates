"""Keep model-imagined tool transport out of responses.

Only provider text passes through this guard. Backend-created embed references
are emitted downstream and must never be interpreted as model tool attempts.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs


_PROTOCOL_FENCE = re.compile(r"^```(toon|tool_code)(?:[^\n]*)\n", re.IGNORECASE)
_APP_FIELD = re.compile(r"(?m)^\s*app_id\s*:")
_SKILL_FIELD = re.compile(r"(?m)^\s*skill_id\s*:")

TOOL_PROTOCOL_CONTINUATION_PROMPT = (
    "Continue the preceding assistant response exactly where it stopped. "
    "Do not repeat or summarize text that is already present. Return only the "
    "remaining user-facing prose. Do not emit tool calls, tool-result envelopes, "
    "TOON, or commentary about this continuation instruction. Do not invent or "
    "rely on information from the suppressed tool text."
)
TOOL_PROTOCOL_RESTART_PROMPT = (
    "Answer the preceding user request using only information already verified in "
    "the conversation. The previous assistant output was suppressed and is not "
    "evidence. If a needed tool result is unavailable, say so briefly instead of "
    "inventing it. Return only user-facing prose. Do not emit tool calls, "
    "tool-result envelopes, or TOON."
)


def build_tool_protocol_recovery_messages(safe_text: str) -> list[dict[str, str]]:
    """Continue published text, or restart when the guard suppressed all text."""
    if not safe_text.strip():
        return [{"role": "user", "content": TOOL_PROTOCOL_RESTART_PROMPT}]
    return [
        {"role": "assistant", "content": safe_text},
        {"role": "user", "content": TOOL_PROTOCOL_CONTINUATION_PROMPT},
    ]


@dataclass
class ToolProtocolRecoveryState:
    """Bound one recovery attempt after fabricated provider protocol."""

    attempted: bool = False
    preserved_safe_text: bool = False

    def action(
        self,
        *,
        detected: bool,
        native_call_count: int,
        safe_text: str,
        has_retry_iteration: bool,
    ) -> str:
        """Return ignore, retry, failure, or error for a completed model turn."""
        if not detected or native_call_count:
            return "ignore"

        has_safe_text = bool(safe_text.strip())
        self.preserved_safe_text = self.preserved_safe_text or has_safe_text
        if not self.attempted and has_retry_iteration:
            self.attempted = True
            return "retry"
        if self.preserved_safe_text:
            return "failure"
        return "error"


def is_internal_tool_protocol(language: str, content: str) -> bool:
    """Recognize internal app result envelopes, while preserving ordinary code."""
    if language.lower() == "tool_code":
        return True
    if language.lower() != "toon":
        return False
    return bool(
        (_APP_FIELD.search(content) and _SKILL_FIELD.search(content))
        or '"tool":' in content
        or "tool_code" in content
        or "tool:" in content.lower()
    )


class ToolProtocolGuard:
    """Filter protocol fences before publication; retain native calls and usage.

    Paragraph aggregation assembles arbitrarily split provider fences. Long TOON
    blocks may be split at its buffer limit, so hold those until the closing
    fence (or end of stream). Ordinary code retains its existing streaming path.
    After a fake result, suppress the remaining prose: it may cite invented data.
    """

    def __init__(self) -> None:
        self.detected = False

    async def filter(self, raw_stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        async def text_stream() -> AsyncIterator[Any]:
            async for chunk in raw_stream:
                if isinstance(chunk, UnifiedStreamChunk) and chunk.type == StreamChunkType.TEXT:
                    yield chunk.content or ""
                else:
                    yield chunk

        pending = ""
        language = ""
        async for chunk in aggregate_paragraphs(text_stream()):
            if not isinstance(chunk, str):
                yield chunk
                continue
            if self.detected:
                continue
            opening = _PROTOCOL_FENCE.match(chunk) if not pending else None
            if opening:
                language = opening.group(1)
                pending = chunk
            elif pending:
                pending += chunk
            else:
                yield chunk
                continue
            opening_end = pending.find("\n") + 1
            if "```" not in pending[opening_end:]:
                continue
            if is_internal_tool_protocol(language, pending[opening_end:]):
                self.detected = True
            else:
                yield pending
            pending = ""
        if pending and not self.detected:
            if is_internal_tool_protocol(language, pending):
                self.detected = True
            else:
                yield pending
