# backend/apps/ai/processing/external_result_sanitizer.py
#
# Deterministic external result sanitization helpers for app skills.
# Applies prompt-injection scanning to long text fields from external APIs.
# Fails closed if sanitization fails or content is blocked, so issues are visible.
#
# Architecture: docs/architecture/prompt-injection.md
# Tests: covered by skill-level execution paths and url/text sanitization unit tests.

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from backend.apps.ai.processing.content_sanitization import sanitize_external_content
from backend.core.api.app.utils.secrets_manager import SecretsManager


SKIP_FIELD_NAMES = {
    "url",
    "image_url",
    "photo_url",
    "thumbnail",
    "thumbnail_url",
    "favicon",
    "hash",
    "id",
    "place_id",
    "practice_url",
    "booking_url",
    "website_uri",
    "phone_number",
    "datetime",
}


LONG_TEXT_HINTS = {
    "description",
    "summary",
    "content",
    "body",
    "markdown",
    "transcript",
    "review",
    "reviews",
    "snippet",
    "snippets",
    "notes",
    "details",
    "generative_summary",
    "nearby_places",
    "amenities",
}


def _key_name_for_path(path: str) -> str:
    if not path:
        return ""
    if "." in path:
        return path.rsplit(".", 1)[-1].lower()
    return path.lower()


def _should_sanitize_field(path: str, text: str, min_chars: int) -> bool:
    key_name = _key_name_for_path(path)
    if key_name in SKIP_FIELD_NAMES:
        return False
    value = text.strip()
    if not value:
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return False
    if len(value) >= min_chars:
        return True
    if key_name in LONG_TEXT_HINTS and len(value) >= 40:
        return True
    return False


def _collect_string_fields(
    value: Any,
    base_path: str,
    min_chars: int,
    collected: List[Tuple[str, str]],
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = f"{base_path}.{key}" if base_path else str(key)
            _collect_string_fields(nested, next_path, min_chars, collected)
        return

    if isinstance(value, list):
        for idx, nested in enumerate(value):
            next_path = f"{base_path}[{idx}]" if base_path else f"[{idx}]"
            _collect_string_fields(nested, next_path, min_chars, collected)
        return

    if isinstance(value, str) and _should_sanitize_field(base_path, value, min_chars=min_chars):
        collected.append((base_path, value))


def _set_path_value(obj: Any, path: str, new_value: str) -> None:
    current = obj
    parts: List[str] = []
    token = ""
    i = 0
    while i < len(path):
        c = path[i]
        if c == ".":
            if token:
                parts.append(token)
                token = ""
            i += 1
            continue
        if c == "[":
            if token:
                parts.append(token)
                token = ""
            j = path.find("]", i)
            parts.append(path[i : j + 1])
            i = j + 1
            continue
        token += c
        i += 1
    if token:
        parts.append(token)

    for part in parts[:-1]:
        if part.startswith("[") and part.endswith("]"):
            current = current[int(part[1:-1])]
        else:
            current = current[part]

    last = parts[-1]
    if last.startswith("[") and last.endswith("]"):
        current[int(last[1:-1])] = new_value
    else:
        current[last] = new_value


async def sanitize_long_text_fields_in_payload(
    payload: Any,
    task_id: str,
    secrets_manager: Optional[SecretsManager],
    cache_service: Optional[Any] = None,
    min_chars: int = 120,
    max_parallel: int = 4,
) -> Any:
    """
    Sanitize long external text fields in a nested payload.

    This helper scans nested dict/list payloads for long text values and runs
    each candidate through `sanitize_external_content`. It fails closed if any
    sanitization fails or gets blocked.
    """
    candidates: List[Tuple[str, str]] = []
    _collect_string_fields(payload, "", min_chars=min_chars, collected=candidates)
    if not candidates:
        return payload

    semaphore = asyncio.Semaphore(max_parallel)
    sanitized_by_path: Dict[str, str] = {}

    async def _sanitize_one(path: str, text: str, index: int) -> None:
        async with semaphore:
            field_task_id = f"{task_id}_field_{index}"
            sanitized = await sanitize_external_content(
                content=text,
                content_type="text",
                task_id=field_task_id,
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            )
            if sanitized is None:
                raise RuntimeError(f"Sanitization failed for field '{path}' (returned None)")
            if not sanitized.strip():
                raise RuntimeError(
                    f"Sanitization blocked field '{path}' due to high prompt injection risk"
                )
            sanitized_by_path[path] = sanitized

    await asyncio.gather(
        *[_sanitize_one(path, text, idx) for idx, (path, text) in enumerate(candidates)],
    )

    for path, _ in candidates:
        _set_path_value(payload, path, sanitized_by_path[path])

    return payload
