"""Bind scheduled Jev approval to the exact public video copy and source.

Semantic decisions happen during generation/selection, never anonymous reads.
A changed or legacy unreviewed row is withheld until the selector reviews it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# Bump whenever editorial or visual requirements change.
REVIEW_VERSION = "daily-editorial-v5"
_REVIEW_FIELDS = (
    "language", "youtube_id", "video_title", "video_description", "video_thumbnail_url",
    "video_channel_name", "title", "phrase", "assistant_response", "category",
)


def editorial_review_digest(entry: Mapping[str, Any]) -> str:
    evidence = {field: entry.get(field) or "" for field in _REVIEW_FIELDS}
    suggestions = entry.get("follow_up_suggestions") or []
    if isinstance(suggestions, str):
        suggestions = json.loads(suggestions)
    if not isinstance(suggestions, list) or any(not isinstance(item, str) for item in suggestions):
        raise ValueError("Invalid reviewed follow-ups")
    evidence["follow_up_suggestions"] = suggestions
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return REVIEW_VERSION + ":" + hashlib.sha256(encoded.encode()).hexdigest()


def is_inspiration_media_coherent(entry: Mapping[str, Any]) -> bool:
    """Require the selector's semantic/image review proof for public videos."""
    if (entry.get("content_type") or "video") != "video":
        return True
    try:
        return bool(entry.get("youtube_id")) and entry.get("editorial_review") == editorial_review_digest(entry)
    except (TypeError, ValueError):
        return False
