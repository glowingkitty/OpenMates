"""Notification type and one-line summary produced by the post-processing call.

The existing post-answer LLM call (`handle_postprocessing`) also returns
`notification_type` (done | question | info) and `notification_summary`
(about 90 characters, chat language). This module validates them; it makes no
LLM request. Any invalid or missing value yields `(None, None)`, and every
consumer then falls back to the generic notification text.

The summary is derived from the plaintext assistant answer, which the AI
pipeline already handles transiently. It must never be persisted unsealed;
see `notification_headline_handoff.py` for the short-lived sealed hand-off.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Optional

NOTIFICATION_TYPES = ("done", "question", "info")
NOTIFICATION_ICONS = {"done": "✅", "question": "❓", "info": "ℹ️"}
# The prompt asks for at most 90 characters; tolerate a little overshoot
# before shortening so a good summary is not cut for one extra word.
SUMMARY_PROMPT_LIMIT = 90
SUMMARY_HARD_LIMIT = 100

_MARKDOWN = re.compile(r"[`*_#>\[\]]")
_EDGE_QUOTES_AND_STOPS = " \t\"'“”‘’«».。"


def sanitize_notification_fields(arguments: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Return a valid `(type, summary)` pair, or `(None, None)` when either part is unusable."""
    raw_type = arguments.get("notification_type")
    raw_summary = arguments.get("notification_summary")
    if not isinstance(raw_type, str) or not isinstance(raw_summary, str):
        return None, None
    notification_type = raw_type.strip().lower()
    if notification_type not in NOTIFICATION_TYPES:
        return None, None
    summary = " ".join(_MARKDOWN.sub("", raw_summary).split()).strip(_EDGE_QUOTES_AND_STOPS)
    if not summary:
        return None, None
    return notification_type, _shorten(summary)


def _shorten(summary: str) -> str:
    """Cut at a word boundary within the hard limit and mark the cut."""
    if len(summary) <= SUMMARY_HARD_LIMIT:
        return summary
    cut = summary[: SUMMARY_HARD_LIMIT - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


def notification_headline(notification_type: str, summary: str) -> str:
    """Icon plus summary, for example "✅ Gemini 4 models added, 3 tests pass"."""
    return f"{NOTIFICATION_ICONS[notification_type]} {summary}"


def headline_or_none(notification_type: Any, summary: Any) -> Optional[str]:
    """The icon + summary line when both parts are valid, otherwise None (generic text)."""
    kind, clean = sanitize_notification_fields({"notification_type": notification_type, "notification_summary": summary})
    return notification_headline(kind, clean) if kind and clean else None
