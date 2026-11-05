"""Recognize tool calls that a model wrote as plain text (issue S7ZNB).

Some models occasionally "call" a skill by writing the call into the answer
(``<tool_call>{...}</tool_call>``, a JSON function-call block, ``[TOOL_CALLS]``
...) instead of using the native tool-calling interface. Nothing executes, the
block is hidden from the user, and the turn would end without an answer.

Classification is deliberately conservative so ordinary answers that contain
JSON code samples are never treated as calls:

* ``<tool_call>`` markup outside a code fence is provider protocol syntax and is
  always a pseudo call (the paragraph aggregator already withholds it).
* Other call markup (``<function_call>``, ``[TOOL_CALLS]``, ``<invoke ...>``)
  must open the block and name a known tool.
* JSON (fenced as json/plain, or a bare paragraph) must parse completely into a
  call-shaped object -- a name field plus an arguments field -- whose name is a
  known tool of this request.

Whether the turn is *dominated* by the pseudo call is decided after the turn:
substantive visible prose means the block was a stray and the answer stands.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Visible prose beyond this many characters is a real answer, not a preamble
# such as "Let me search for that." in front of a pseudo call.
PSEUDO_TOOL_CALL_MAX_PREAMBLE_CHARS = 280

PSEUDO_TOOL_CALL_RETRY_PROMPT = (
    "Your previous reply wrote a tool call as plain text, so nothing was executed "
    "and the user saw no answer. Do not write tool calls, function-call JSON or "
    "<tool_call> markup into your reply. If you need a tool, call it through the "
    "real tool-calling interface; otherwise answer the user's request directly in "
    "user-facing prose."
)

_FENCE = re.compile(r"^```([\w.+-]*)[^\n]*\n(.*?)\n?```\s*$", re.DOTALL)
_JSON_FENCE_LANGUAGES = frozenset({"", "json", "json5", "jsonc", "tool_call", "function_call", "tool_use"})
_CALL_MARKUP = re.compile(
    r"^\s*(?:<\|?(?:tool_call|tool_calls|function_call|function_calls|tool_use)\|?>"
    r"|\[TOOL_CALLS\]|<\|python_tag\|>|<function=|<invoke\b)",
    re.IGNORECASE,
)
_NAME_KEYS = ("name", "tool", "tool_name", "function_name", "recipient_name")
_ARGUMENT_KEYS = ("arguments", "parameters", "args", "input", "tool_input", "requests")


@dataclass(frozen=True)
class SuppressedToolCallMarkup:
    """``<tool_call>`` text the paragraph aggregator withheld from publication."""

    text: str


def normalize_tool_name(name: str) -> str:
    """Fold separator variants (web.search, web_search, web|search) together."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def known_tool_names(names: Iterable[str]) -> frozenset[str]:
    return frozenset(normalize_tool_name(name) for name in names if isinstance(name, str) and name.strip())


def _call_name(value: Any) -> str | None:
    """Return the normalized name of a call-shaped object, else None."""
    if not isinstance(value, dict):
        return None
    function = value.get("function")
    if isinstance(function, dict):
        return _call_name(function)
    nested = value.get("tool_calls")
    if isinstance(nested, list) and nested:
        names = [_call_name(item) for item in nested]
        return names[0] if all(names) else None
    if not any(key in value for key in _ARGUMENT_KEYS):
        return None
    for key in _NAME_KEYS:
        if isinstance(value.get(key), str):
            return normalize_tool_name(value[key])
    app_id = value.get("app_id", value.get("app"))
    skill_id = value.get("skill_id", value.get("skill"))
    if isinstance(app_id, str) and isinstance(skill_id, str):
        return normalize_tool_name(f"{app_id}-{skill_id}")
    return None


def _json_call_name(text: str, known: frozenset[str]) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    items = parsed if isinstance(parsed, list) else [parsed]
    names = [_call_name(item) for item in items]
    if not names or not all(name in known for name in names):
        return None
    return names[0]


def _mentions_known_tool(text: str, known: frozenset[str]) -> str | None:
    folded = f"-{normalize_tool_name(text)}-"
    return next((name for name in sorted(known) if f"-{name}-" in folded), None)


def pseudo_tool_call_reason(block: str, known: frozenset[str]) -> str | None:
    """Classify one complete paragraph or code block of model text."""
    stripped = block.strip()
    if not stripped or not known:
        return None
    fence = _FENCE.match(stripped)
    if fence:
        language, body = fence.group(1).lower(), fence.group(2).strip()
        if language in _JSON_FENCE_LANGUAGES and _json_call_name(body, known):
            return "json_fence_tool_call"
        return None
    if stripped.startswith("```"):
        return None
    if _CALL_MARKUP.match(stripped):
        return "tool_call_markup" if _mentions_known_tool(stripped, known) else None
    if stripped[0] in "{[" and _json_call_name(stripped, known):
        return "bare_json_tool_call"
    return None


@dataclass
class PseudoToolCallRecovery:
    """Bound recovery for turns that only contain a text pseudo tool call."""

    attempted: bool = False

    def action(
        self,
        *,
        detected: bool,
        native_call_count: int,
        visible_text: str,
        has_retry_iteration: bool,
    ) -> str:
        """Return ``ignore``, ``retry`` or ``error`` for a completed model turn."""
        if not detected or native_call_count:
            return "ignore"
        if len(visible_text.strip()) > PSEUDO_TOOL_CALL_MAX_PREAMBLE_CHARS:
            return "ignore"
        if not self.attempted and has_retry_iteration:
            self.attempted = True
            return "retry"
        return "error"
