"""Keep model-imagined tool transport out of responses and recover native searches.

Only provider text passes through this guard. Backend-created embed references
are emitted downstream and must never be interpreted as model tool attempts.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs


_PROTOCOL_FENCE = re.compile(r"^```(toon|tool_code)(?:[^\n]*)\n", re.IGNORECASE)
_APP_FIELD = re.compile(r"(?m)^\s*app_id\s*:")
_SKILL_FIELD = re.compile(r"(?m)^\s*skill_id\s*:")
# Recovery never enables writes or a tool omitted by preprocessing/the allow-list.
RECOVERABLE_SEARCH_SKILLS = frozenset({"news-search", "web-search", "images-search"})


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


def recovery_search_tools(
    tools: list[dict[str, Any]], selected_skills: list[str] | None
) -> list[dict[str, Any]]:
    """Return only originally selected, available, read-only search tools."""
    permitted = set(selected_skills or []) & RECOVERABLE_SEARCH_SKILLS
    return [tool for tool in tools if tool.get("function", {}).get("name") in permitted]


def required_fresh_search_tools(
    tools: list[dict[str, Any]], selected_skills: list[str] | None,
    *, requires_fresh_search: bool, total_skill_calls: int, tools_disabled: bool,
) -> list[dict[str, Any]]:
    """Require fresh retrieval only before the first call, within existing budgets."""
    if requires_fresh_search is not True or total_skill_calls or tools_disabled:
        return []
    return recovery_search_tools(tools, selected_skills)


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
