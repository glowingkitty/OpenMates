# backend/apps/ai/processing/audio_recording_guard.py
# Shared guardrail for web UI voice recordings in AI tool routing.
#
# Web UI recordings are transcribed before they are sent to the assistant.
# Once a recording has a transcript, the main model must use that transcript as
# user input instead of calling audio.transcribe again. This keeps voice notes
# from being mistaken for manually uploaded audio files that still need OCR-like
# processing.

from __future__ import annotations

import json
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
_TARGET_FIELDS = ("embed_ref", "file_path", "filename", "embed_id", "s3_key")
_EMBED_FIELDS = ("type", "transcript", "transcription_source", "transcription_status", "mime_type", *_TARGET_FIELDS)


def _audio_embed_records(message_history: Iterable[Any]) -> Iterable[dict[str, Any]]:
    """Read individual resolved embeds without mixing fields across attachments."""
    def json_records(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            if "type" in value:
                yield value
            for child in value.values():
                yield from json_records(child)
        elif isinstance(value, list):
            for child in value:
                yield from json_records(child)

    for message in message_history:
        content = _message_content(message)
        if not content:
            continue
        blocks = re.findall(r"```(?:toon|json)\s*\n(.*?)```", content, re.DOTALL)
        for block in blocks or [content]:
            try:
                decoded = json.loads(block)
            except (ValueError, TypeError):
                # Resolved TOON embeds have top-level scalar metadata. Split
                # unfenced fixtures at each type so a manual file cannot lend
                # its filename or local marker to another attachment.
                sections = (re.split(r"(?m)(?=^type:\s*)", block)
                            if len(re.findall(r"(?m)^type:", block)) > 1 else [block])
                for section in sections:
                    record = {}
                    for field in _EMBED_FIELDS:
                        match = re.search(rf"(?m)^{field}:[ \t]*(.*)$", section)
                        if match:
                            raw = match.group(1).strip()
                            try:
                                record[field] = json.loads(raw)
                            except ValueError:
                                record[field] = raw
                    if record.get("type"):
                        yield record
            else:
                yield from json_records(decoded)


def should_block_local_audio_transcription(
    arguments: Any, message_history: Iterable[Any],
) -> bool:
    """Allow only explicit manual audio targets when local recordings coexist.

    Local completion, silence, or failure never authorizes provider fallback.
    An ambiguous or mixed batch is refused before any request is dispatched.
    """
    records = list(_audio_embed_records(message_history))
    local = [record for record in records if (
        record.get("type") == AUDIO_RECORDING_TYPE
        and record.get("transcription_source") == "local"
    )]
    if not local:
        return False
    local_targets = {
        value for record in local for field in _TARGET_FIELDS
        if isinstance(value := record.get(field), str) and value
    }
    manual_targets = {
        value for record in records
        if record.get("type") == "file-attachment"
        and str(record.get("mime_type", "")).startswith("audio/")
        for field in _TARGET_FIELDS
        if isinstance(value := record.get(field), str) and value
    }
    requests = arguments.get("requests") if isinstance(arguments, dict) else None
    if not isinstance(requests, list) or not requests:
        return True
    for request in requests:
        if not isinstance(request, dict):
            return True
        targets = {
            value for field in _TARGET_FIELDS
            if isinstance(value := request.get(field), str) and value
        }
        # Every supplied target must identify manual audio. A manual filename
        # must not authorize an unknown storage key belonging to a local note.
        if targets & local_targets or not targets or not targets <= manual_targets:
            return True
    return False


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
    """Return True when recording-only audio must avoid provider transcription."""
    message_history = list(message_history)
    records = list(_audio_embed_records(message_history))
    if any(record.get("type") == "file-attachment"
           and str(record.get("mime_type", "")).startswith("audio/")
           for record in records):
        return False
    local_recording = any(
        record.get("type") == AUDIO_RECORDING_TYPE
        and record.get("transcription_source") == "local"
        for record in records
    )
    found_transcribed_recording = any(
        record.get("type") == AUDIO_RECORDING_TYPE
        and isinstance(record.get("transcript"), str)
        and record["transcript"].strip().casefold() not in _EMPTY_TRANSCRIPT_VALUES
        for record in records
    )
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
    return local_recording or found_transcribed_recording


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
