"""Bind scheduled approval to exact public video/wiki source evidence and copy.

Semantic decisions happen during generation/selection, never anonymous reads.
A changed or legacy unreviewed external row is withheld until the selector reviews
it. Trusted static builders run separately after the persisted-default filter.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# Bump whenever editorial or visual requirements change.
REVIEW_VERSION = "daily-editorial-v6"
_REVIEW_FIELDS = (
    "language", "youtube_id", "video_title", "video_description", "video_thumbnail_url",
    "video_channel_name", "title", "phrase", "assistant_response", "category",
)


def canonical_wiki_review_source(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Require actual source identity/edition and passage; never borrow output copy.

    Directus may return the same metadata as JSON text or an object. Parse it
    once, preserve every metadata field and let sorted digest encoding normalize
    key order. Missing source editions cannot be inferred from the output locale.
    """
    metadata = entry.get("wiki_metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        raise ValueError("Missing wiki source metadata")
    for field in ("wiki_title", "source_language", "title", "extract"):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing wiki source {field}")
    if metadata.get("description") is not None and not isinstance(metadata["description"], str):
        raise ValueError("Invalid wiki source description")
    return dict(metadata)


def editorial_review_digest(entry: Mapping[str, Any]) -> str:
    evidence = {field: entry.get(field) or "" for field in _REVIEW_FIELDS}
    content_type = entry.get("content_type") or "video"
    evidence["content_type"] = content_type
    if content_type == "wiki":
        evidence["wiki_metadata"] = canonical_wiki_review_source(entry)
    suggestions = entry.get("follow_up_suggestions") or []
    if isinstance(suggestions, str):
        suggestions = json.loads(suggestions)
    if not isinstance(suggestions, list) or any(not isinstance(item, str) for item in suggestions):
        raise ValueError("Invalid reviewed follow-ups")
    evidence["follow_up_suggestions"] = suggestions
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return REVIEW_VERSION + ":" + hashlib.sha256(encoded.encode()).hexdigest()


def is_inspiration_media_coherent(entry: Mapping[str, Any]) -> bool:
    """Require current scheduled proof for persisted external videos and wiki."""
    content_type = entry.get("content_type") or "video"
    if content_type == "feature":
        return True
    if content_type not in {"video", "wiki"}:
        return False
    try:
        if content_type == "video" and not entry.get("youtube_id"):
            return False
        return bool(entry.get("editorial_review")) and entry["editorial_review"] == editorial_review_digest(entry)
    except (TypeError, ValueError):
        return False
