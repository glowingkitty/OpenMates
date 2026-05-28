# backend/apps/ai/processing/audio_recording_guard.py
# Shared guardrail for web UI voice recordings in AI tool routing.
#
# Web UI recordings are transcribed before they are sent to the assistant.
# Once a recording has a transcript, the main model must use that transcript as
# user input instead of calling audio.transcribe again. This keeps voice notes
# from being mistaken for manually uploaded audio files that still need OCR-like
# processing.

from __future__ import annotations

import re
from typing import Any, Iterable


AUDIO_TRANSCRIBE_SKILL_ID = "audio-transcribe"
AUDIO_RECORDING_TYPE = "audio-recording"

_AUDIO_RECORDING_MARKERS = (
    f"type: {AUDIO_RECORDING_TYPE}",
    f'"type": "{AUDIO_RECORDING_TYPE}"',
    f'"type":"{AUDIO_RECORDING_TYPE}"',
)
_GENERIC_AUDIO_FILE_MARKERS = (
    "type: file-attachment",
    '"type": "file-attachment"',
    '"type":"file-attachment"',
)
_AUDIO_MIME_MARKERS = ("mime_type: audio/", '"mime_type": "audio/', '"mime_type":"audio/')
_TOON_TRANSCRIPT_LINE = re.compile(r"(?im)^transcript:\s*(.*)$")
_JSON_TRANSCRIPT_FIELD = re.compile(r'"transcript"\s*:\s*("(?:[^"\\]|\\.)*"|null)', re.IGNORECASE)
_EMPTY_TRANSCRIPT_VALUES = {"", "null", "none", "undefined"}


def _message_content(message: Any) -> str | None:
    if hasattr(message, "content"):
        content = message.content
    elif isinstance(message, dict):
        content = message.get("content")
    else:
        content = None
    return content if isinstance(content, str) else None


def _has_audio_recording_marker(content: str) -> bool:
    return any(marker in content for marker in _AUDIO_RECORDING_MARKERS)


def _has_generic_audio_file_marker(content: str) -> bool:
    return (
        any(marker in content for marker in _GENERIC_AUDIO_FILE_MARKERS)
        and any(marker in content for marker in _AUDIO_MIME_MARKERS)
    )


def _has_non_empty_transcript(content: str) -> bool:
    toon_match = _TOON_TRANSCRIPT_LINE.search(content)
    if toon_match:
        value = toon_match.group(1).strip().strip('"')
        return value.casefold() not in _EMPTY_TRANSCRIPT_VALUES

    json_match = _JSON_TRANSCRIPT_FIELD.search(content)
    if not json_match:
        return False
    raw_value = json_match.group(1).strip()
    if raw_value.casefold() == "null":
        return False
    value = raw_value.strip('"').strip()
    return value.casefold() not in _EMPTY_TRANSCRIPT_VALUES


def has_transcribed_web_audio_recording(message_history: Iterable[Any]) -> bool:
    """Return True when only web UI recording audio needs no transcription."""
    found_transcribed_recording = False
    for message in message_history:
        content = _message_content(message)
        if not content:
            continue
        if _has_generic_audio_file_marker(content):
            return False
        if not _has_audio_recording_marker(content):
            continue
        if _has_non_empty_transcript(content):
            found_transcribed_recording = True
    return found_transcribed_recording


def remove_audio_transcribe_for_transcribed_recordings(
    skills: list[str],
    message_history: Iterable[Any],
) -> tuple[list[str], bool]:
    """Remove audio.transcribe when web UI recordings already provide transcripts."""
    if AUDIO_TRANSCRIBE_SKILL_ID not in skills:
        return skills, False
    if not has_transcribed_web_audio_recording(message_history):
        return skills, False
    return [skill for skill in skills if skill != AUDIO_TRANSCRIBE_SKILL_ID], True
