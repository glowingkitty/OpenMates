# backend/apps/ai/daily_inspiration/media_coherence.py
#
# Deterministic text/media coherence checks for Daily Inspiration video cards.
# The LLM writes user-facing copy and selects one video candidate; this module
# prevents hallucinated copy from being paired with unrelated media before it
# enters personalized delivery, the shared pool, or public defaults.
#
# See: docs/architecture/frontend/daily-inspiration.md

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping


_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
_MIN_COPY_TOPIC_TOKENS = 3
_MIN_MEDIA_TOPIC_TOKENS = 1

_STOPWORDS = {
    "about",
    "after",
    "also",
    "before",
    "best",
    "could",
    "documentary",
    "does",
    "every",
    "explained",
    "explains",
    "from",
    "full",
    "have",
    "into",
    "learn",
    "life",
    "live",
    "made",
    "make",
    "makes",
    "more",
    "most",
    "minutes",
    "part",
    "short",
    "that",
    "their",
    "them",
    "this",
    "through",
    "video",
    "watch",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "work",
    "works",
    "world",
    "would",
    "youtube",
}

_ACRONYM_EXPANSIONS = {
    "iss": {"international", "space", "station"},
}


def check_inspiration_media_coherence(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return PASS/REJECT for whether video metadata matches generated copy."""
    if (entry.get("content_type") or "video") != "video":
        return {"verdict": "PASS", "reason": "not_video", "overlap": []}
    if not entry.get("youtube_id"):
        return {"verdict": "PASS", "reason": "no_video", "overlap": []}

    media_tokens = _topic_tokens(str(entry.get("video_title") or ""))
    copy_tokens = _topic_tokens(
        " ".join(
            str(entry.get(field) or "")
            for field in ("phrase", "title", "assistant_response")
        )
    )

    if len(media_tokens) < _MIN_MEDIA_TOPIC_TOKENS:
        return {"verdict": "PASS", "reason": "media_inconclusive", "overlap": []}
    if len(copy_tokens) < _MIN_COPY_TOPIC_TOKENS:
        return {"verdict": "PASS", "reason": "copy_inconclusive", "overlap": []}

    overlap = sorted(media_tokens & copy_tokens)
    if overlap:
        return {"verdict": "PASS", "reason": "shared_topic_tokens", "overlap": overlap}

    return {
        "verdict": "REJECT",
        "reason": "no_shared_topic_tokens",
        "media_tokens": sorted(media_tokens),
        "copy_tokens": sorted(copy_tokens),
        "overlap": [],
    }


def is_inspiration_media_coherent(entry: Mapping[str, Any]) -> bool:
    """Return True when a Daily Inspiration video card is safe to publish."""
    return check_inspiration_media_coherence(entry)["verdict"] == "PASS"


def _topic_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    normalized = unicodedata.normalize("NFKD", text).casefold()
    for raw_token in _TOKEN_RE.findall(normalized):
        token = raw_token.strip("'")
        if not token or token.isdigit():
            continue
        token = _stem_token(token)
        if len(token) < 4 or token in _STOPWORDS:
            continue
        tokens.add(token)
        tokens.update(_ACRONYM_EXPANSIONS.get(token, set()))
    return tokens


def _stem_token(token: str) -> str:
    for suffix in ("'s", "ing", "ers", "ies", "ied", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            if suffix in {"ies", "ied"}:
                return f"{token[:-len(suffix)]}y"
            return token[: -len(suffix)]
    return token
