"""Keep model-imagined tool transport out of responses.

Only provider text passes through this guard. Backend-created embed references
are emitted downstream and must never be interpreted as model tool attempts.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

from backend.apps.ai.llm_providers.types import StreamChunkType, UnifiedStreamChunk
from backend.apps.ai.utils.pseudo_tool_call import (
    SuppressedToolCallMarkup,
    known_tool_names,
    normalize_tool_name,
    pseudo_tool_call_reason,
)
from backend.apps.ai.utils.stream_utils import PROGRESSIVE_CODE_LANGUAGES, aggregate_paragraphs


_PROTOCOL_FENCE = re.compile(r"^```(toon|tool_code)(?:[^\n]*)\n", re.IGNORECASE)
_APP_FIELD = re.compile(r"(?m)^\s*app_id\s*:")
_SKILL_FIELD = re.compile(r"(?m)^\s*skill_id\s*:")
_FOCUS_ID_FIELD = re.compile(r"(?m)^\s*focus_id\s*:")
_FOCUS_NAME_FIELD = re.compile(r"(?m)^\s*focus_mode_name\s*:")

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


# A model that sees earlier app results as ```toon blocks in chat history can
# imitate one (app_id/skill_id fields) instead of calling the skill. Seen on dev
# in a multi-turn Browse form chat: the user's answer needed a real Browse call,
# so the tools-off answer-only recovery could not do the step and the turn failed.
TOON_RESULT_RETRY_PROMPT = (
    "Your previous reply wrote an app result block (a toon block with app_id and "
    "skill_id) as text, so nothing was executed and the user saw no answer. The toon "
    "blocks in this chat are past results shown to you; never write one. If the next "
    "step needs an app skill, call it through the real tool-calling interface; "
    "otherwise answer the user directly in prose."
)


_APP_VALUE = re.compile(r"(?m)^\s*app_id\s*:\s*([\w.-]+)\s*$")
_SKILL_VALUE = re.compile(r"(?m)^\s*skill_id\s*:\s*([\w.-]+)\s*$")


def imitated_tool_name(content: str) -> str | None:
    """The normalized ``app-skill`` tool an imitated app result names, if any."""
    app, skill = _APP_VALUE.search(content), _SKILL_VALUE.search(content)
    return normalize_tool_name(f"{app.group(1)}-{skill.group(1)}") if app and skill else None


def toon_result_retry_applies(guard: ToolProtocolGuard, available_tools: Iterable[Any] | None) -> bool:
    """True when the imitated app result names a skill offered in this request.

    The model meant to use that skill, so one retry keeps tools on. An imitated
    result of a skill that is not offered keeps the clean answer-only recovery.
    """
    if guard.diagnostics.get("reason") != "toon_app_skill_fields" or not guard.imitated_tool:
        return False
    offered = known_tool_names(
        str((tool.get("function") or {}).get("name") or "")
        for tool in available_tools or []
        if isinstance(tool, dict)
    )
    return guard.imitated_tool in offered


def tool_protocol_reason(language: str, content: str) -> str | None:
    """Recognize internal app result envelopes, while preserving ordinary code."""
    if language.lower() == "tool_code":
        return "tool_code_fence"
    if language.lower() != "toon":
        return None
    for matched, reason in (
        (_APP_FIELD.search(content) and _SKILL_FIELD.search(content), "toon_app_skill_fields"),
        ('"tool":' in content, "toon_json_tool_field"),
        ("tool_code" in content, "toon_tool_code_marker"),
        ("tool:" in content.lower(), "toon_tool_field"),
    ):
        if matched:
            return reason
    return None


def is_focus_activation_echo(language: str, content: str) -> bool:
    """True for a copy of a Focus activation card written as a toon block.

    Chat history shows past Focus activations to the model as toon blocks with
    focus_id and focus_mode_name (GSLQ7). A model that repeats one adds no data
    and runs nothing, so only the block is dropped; the reply itself stays.
    """
    return (
        language.lower() == "toon"
        and bool(_FOCUS_ID_FIELD.search(content))
        and bool(_FOCUS_NAME_FIELD.search(content))
    )


def is_internal_tool_protocol(language: str, content: str) -> bool:
    """Keep classification unchanged; diagnostics expose fixed codes only."""
    return tool_protocol_reason(language, content) is not None


class ToolProtocolGuard:
    """Filter protocol fences before publication; retain native calls and usage.

    Paragraph aggregation assembles arbitrarily split provider fences while
    releasing ordinary prose as soon as it cannot form a protocol delimiter.
    Long TOON blocks may be split at its buffer limit, so hold those until the
    closing fence (or end of stream). Ordinary code retains its existing path.
    After a fake result, suppress the remaining prose: it may cite invented data.

    A pseudo tool *call* written as text (S7ZNB) is different: only that block
    is withheld and recorded in ``pseudo_tool_call``; surrounding prose still
    streams, and the caller decides after the turn whether it was a real answer.
    """

    def __init__(self, known_tools: Iterable[str] = ()) -> None:
        self.detected = False
        self.diagnostics: dict[str, str | int | bool] = {}
        self.known_tools = known_tool_names(known_tools)
        self.pseudo_tool_call = False
        self.pseudo_tool_call_diagnostics: dict[str, str | int] = {}
        # Echoed Focus activation cards dropped from the reply (GSLQ7).
        self.focus_activation_echoes = 0
        # Internal only, never logged: the app-skill an imitated result names.
        self.imitated_tool: str | None = None

    def _record_pseudo_tool_call(self, reason: str, block: str) -> None:
        if not self.pseudo_tool_call:
            self.pseudo_tool_call_diagnostics = {"reason": reason, "body_chars": len(block)}
        self.pseudo_tool_call = True

    async def filter(self, raw_stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        async def text_stream() -> AsyncIterator[Any]:
            async for chunk in raw_stream:
                if isinstance(chunk, UnifiedStreamChunk) and chunk.type == StreamChunkType.TEXT:
                    yield chunk.content or ""
                else:
                    yield chunk

        pending = ""
        language = ""
        async for chunk in aggregate_paragraphs(
            text_stream(), early_prose=True, progressive_code_languages=PROGRESSIVE_CODE_LANGUAGES,
        ):
            if isinstance(chunk, SuppressedToolCallMarkup):
                self._record_pseudo_tool_call("tool_call_markup", chunk.text)
                continue
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
                pseudo_reason = pseudo_tool_call_reason(chunk, self.known_tools)
                if pseudo_reason:
                    self._record_pseudo_tool_call(pseudo_reason, chunk)
                else:
                    yield chunk
                continue
            opening_end = pending.find("\n") + 1
            if "```" not in pending[opening_end:]:
                continue
            if is_focus_activation_echo(language, pending[opening_end:]):
                self.focus_activation_echoes += 1
            elif is_internal_tool_protocol(language, pending[opening_end:]):
                self.detected = True
                self.diagnostics = {"reason": tool_protocol_reason(language, pending[opening_end:]), "language": language.lower(), "closed": True, "body_chars": len(pending) - opening_end}
                self.imitated_tool = imitated_tool_name(pending[opening_end:])
            else:
                yield pending
            pending = ""
        if pending and not self.detected:
            if is_focus_activation_echo(language, pending):
                self.focus_activation_echoes += 1
            elif is_internal_tool_protocol(language, pending):
                self.detected = True
                self.diagnostics = {"reason": tool_protocol_reason(language, pending), "language": language.lower(), "closed": False, "body_chars": len(pending)}
                self.imitated_tool = imitated_tool_name(pending)
            else:
                yield pending
