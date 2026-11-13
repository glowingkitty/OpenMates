"""Fence detection for slides decks (```slides blocks).

stream_consumer.py defers the fence until it closes,
then creates one finished deck embed from the normalised markup.
"""

from __future__ import annotations

SLIDES_FENCE_LANGUAGE = "slides"


def _is_slides_fence(language: str | None) -> bool:
    return (language or "").strip().lower() == SLIDES_FENCE_LANGUAGE
