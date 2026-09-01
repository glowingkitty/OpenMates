# backend/apps/ai/assistant_speech/projection.py
#
# Deterministic projection for assistant-response speech.
# This module selects only prerecorded acknowledgements and producer-provided
# semantic text; it never invokes a cleanup model or stores segment plaintext.
# Returned segments are transient request data for the speech worker.

from __future__ import annotations

import re
from hashlib import sha256
from collections.abc import Iterable, Mapping
from typing import Any

_FENCED_CODE = re.compile(r"^```[\s\S]*```$", re.MULTILINE)
_FENCED_CODE_BLOCK = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_JSON_INLINE = re.compile(r"(?:\{[^{}]*\}|\[[^\[\]]*\])")
_URL = re.compile(r"(?:https?|ftp)://[^\s)\]>]+|[a-z][a-z0-9+.-]*://[^\s)\]>]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_MARKDOWN_SYNTAX = re.compile(r"(?:^|\s)[#>*_~]+|[_~]{1,3}")


def select_prerecorded_acknowledgement(
    *,
    clips: Iterable[Mapping[str, Any]],
    voice_profile_id: str,
    voice_profile_version: int,
    language: str,
    request_category: str,
    selection_seed: str,
) -> dict[str, object] | None:
    """Select a stable prerecorded acknowledgement without runtime generation."""
    candidates = [
        clip
        for clip in clips
        if clip.get("voice_profile_id") == voice_profile_id
        and clip.get("voice_profile_version") == voice_profile_version
    ]
    language_candidates = _matching_language(candidates, language)
    category_candidates = [
        clip for clip in language_candidates if clip.get("request_category") == request_category
    ]
    if not category_candidates:
        category_candidates = [
            clip for clip in language_candidates if clip.get("request_category") == "general"
        ]
    if not category_candidates:
        return None

    ordered_candidates = sorted(category_candidates, key=lambda clip: str(clip.get("clip_id", "")))
    selection_identity = ":".join(
        (selection_seed, voice_profile_id, str(voice_profile_version), language, request_category)
    )
    digest = sha256(selection_identity.encode("utf-8")).digest()
    selected = ordered_candidates[int.from_bytes(digest[:8], "big") % len(ordered_candidates)]
    return {
        "clip_id": selected["clip_id"],
        "runtime_generation": False,
        "runtime_credits_charged": 0,
    }


def project_speech_segments(*, blocks: Iterable[Mapping[str, Any]], language: str) -> list[dict[str, object]]:
    """Project semantic response blocks into ordered, transient speech segments."""
    del language  # Localization belongs to producer summaries for this first core.
    segments: list[dict[str, object]] = []
    for block in blocks:
        projected = _project_block(block)
        if projected is None:
            continue
        kind, text = projected
        segments.append(
            {"sequence": len(segments), "kind": kind, "speakable_text": text},
        )
    return segments


def project_streaming_speech_segment(markdown: str) -> tuple[str, str] | None:
    """Create a safe deterministic fallback when streaming lacks semantic blocks."""
    text = markdown.strip()
    if not text:
        return None
    if _FENCED_CODE.fullmatch(text):
        return "code_summary", "A code example is available."
    if _is_markdown_table(text):
        return "table_summary", "A table is available."
    if text.startswith(("{", "[")):
        return "embed_summary", "Structured data is available."
    # Streaming responses are encrypted client history, so the server cannot
    # recover producer block metadata here. Never turn raw structured syntax into speech.
    text = _FENCED_CODE_BLOCK.sub(" A code example is available. ", text)
    text = _TABLE_ROW.sub(" A table is available. ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub("", text)
    text = _JSON_INLINE.sub(" structured data ", text)
    text = _URL.sub("", text)
    text = _MARKDOWN_SYNTAX.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return ("prose_paragraph", text) if text else None


def _matching_language(clips: list[Mapping[str, Any]], language: str) -> list[Mapping[str, Any]]:
    exact = [clip for clip in clips if clip.get("language") == language]
    if exact:
        return exact
    base_language = language.split("-", maxsplit=1)[0].lower()
    return [
        clip
        for clip in clips
        if str(clip.get("language", "")).split("-", maxsplit=1)[0].lower() == base_language
    ]


def _project_block(block: Mapping[str, Any]) -> tuple[str, str] | None:
    block_type = str(block.get("type", ""))
    if block_type == "prose":
        return _text_segment("prose_paragraph", block.get("text"))
    if block_type in {"link", "citation"}:
        return _text_segment("prose_paragraph", block.get("label"))
    if block_type == "code":
        return _text_segment("code_summary", block.get("summary"))
    if block_type == "table":
        return _text_segment("table_summary", block.get("summary"))
    if block_type in {"map", "calendar", "embed", "unknown_embed"}:
        return _text_segment("embed_summary", block.get("summary"))
    if block_type == "app_use":
        return _text_segment("app_use_announcement", block.get("announcement"))
    return None


def _text_segment(kind: str, value: object) -> tuple[str, str] | None:
    text = str(value or "").strip()
    return (kind, text) if text else None


def _is_markdown_table(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and all(_TABLE_ROW.match(line) for line in lines)
