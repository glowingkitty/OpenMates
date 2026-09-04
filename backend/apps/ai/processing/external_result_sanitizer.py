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


SEMANTIC_SCAN_BATCH_TARGET_CHARS = 50_000
SEMANTIC_SCAN_FIELD_SEPARATOR = "\n\n--- OPENMATES EXTERNAL FIELD ---\n\n"

SKIP_FIELD_NAMES = {
    "url",
    "image_url",
    "photo_url",
    "thumbnail",
    "thumbnail_url",
    "favicon",
    "hash",
    "id",
    "s3_key",
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


def _should_sanitize_field(
    path: str,
    text: str,
    min_chars: int,
    skip_field_names: Optional[set[str]] = None,
) -> bool:
    key_name = _key_name_for_path(path)
    if key_name in SKIP_FIELD_NAMES or (skip_field_names and key_name in skip_field_names):
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


def _should_sanitize_field_with_overrides(
    path: str,
    text: str,
    min_chars: int,
    always_sanitize_field_names: Optional[set[str]],
    skip_field_names: Optional[set[str]] = None,
) -> bool:
    key_name = _key_name_for_path(path)
    value = text.strip()
    if not value or key_name in SKIP_FIELD_NAMES or (skip_field_names and key_name in skip_field_names):
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return False
    if always_sanitize_field_names and key_name in always_sanitize_field_names:
        return True
    return _should_sanitize_field(
        path,
        text,
        min_chars=min_chars,
        skip_field_names=skip_field_names,
    )


def _collect_string_fields_with_overrides(
    value: Any,
    base_path: str,
    min_chars: int,
    collected: List[Tuple[str, str]],
    always_sanitize_field_names: Optional[set[str]],
    skip_field_names: Optional[set[str]] = None,
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = f"{base_path}.{key}" if base_path else str(key)
            _collect_string_fields_with_overrides(
                nested,
                next_path,
                min_chars,
                collected,
                always_sanitize_field_names,
                skip_field_names,
            )
        return

    if isinstance(value, list):
        for idx, nested in enumerate(value):
            next_path = f"{base_path}[{idx}]" if base_path else f"[{idx}]"
            _collect_string_fields_with_overrides(
                nested,
                next_path,
                min_chars,
                collected,
                always_sanitize_field_names,
                skip_field_names,
            )
        return

    if isinstance(value, str) and _should_sanitize_field_with_overrides(
        base_path,
        value,
        min_chars=min_chars,
        always_sanitize_field_names=always_sanitize_field_names,
        skip_field_names=skip_field_names,
    ):
        collected.append((base_path, value))


def _collect_string_fields(
    value: Any,
    base_path: str,
    min_chars: int,
    collected: List[Tuple[str, str]],
    skip_field_names: Optional[set[str]] = None,
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = f"{base_path}.{key}" if base_path else str(key)
            _collect_string_fields(nested, next_path, min_chars, collected, skip_field_names)
        return

    if isinstance(value, list):
        for idx, nested in enumerate(value):
            next_path = f"{base_path}[{idx}]" if base_path else f"[{idx}]"
            _collect_string_fields(nested, next_path, min_chars, collected, skip_field_names)
        return

    if isinstance(value, str) and _should_sanitize_field(
        base_path,
        value,
        min_chars=min_chars,
        skip_field_names=skip_field_names,
    ):
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


def _batch_candidates(candidates: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
    batches: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    current_chars = 0
    separator_chars = len(SEMANTIC_SCAN_FIELD_SEPARATOR)

    for candidate in candidates:
        candidate_chars = len(candidate[1]) + (separator_chars if current else 0)
        if current and current_chars + candidate_chars > SEMANTIC_SCAN_BATCH_TARGET_CHARS:
            batches.append(current)
            current = []
            current_chars = 0
            candidate_chars = len(candidate[1])
        current.append(candidate)
        current_chars += candidate_chars

    if current:
        batches.append(current)
    return batches


async def sanitize_long_text_fields_in_payload(
    payload: Any,
    task_id: str,
    secrets_manager: Optional[SecretsManager],
    cache_service: Optional[Any] = None,
    min_chars: int = 120,
    max_parallel: int = 4,
    always_sanitize_field_names: Optional[set[str]] = None,
    skip_field_names: Optional[set[str]] = None,
) -> Any:
    """
    Sanitize long external text fields in a nested payload.

    This helper scans nested dict/list payloads for long text values. Safe fields
    share target-sized semantic scans; an individual long field remains intact
    and is chunked by `sanitize_external_content`. Changed batches fall back to
    field-level scans so redaction behavior remains isolated. It fails closed if
    any scan fails or gets blocked.
    """
    candidates: List[Tuple[str, str]] = []
    normalized_skip = {field.lower() for field in skip_field_names or set()}
    if always_sanitize_field_names:
        normalized_always = {field.lower() for field in always_sanitize_field_names}
        _collect_string_fields_with_overrides(
            payload,
            "",
            min_chars=min_chars,
            collected=candidates,
            always_sanitize_field_names=normalized_always,
            skip_field_names=normalized_skip,
        )
    else:
        _collect_string_fields(
            payload,
            "",
            min_chars=min_chars,
            collected=candidates,
            skip_field_names=normalized_skip,
        )
    if not candidates:
        return payload

    semaphore = asyncio.Semaphore(max_parallel)
    sanitized_by_path: Dict[str, str] = {}

    async def _scan(content: str, scan_task_id: str, field_label: str) -> str:
        async with semaphore:
            sanitized = await sanitize_external_content(
                content=content,
                content_type="text",
                task_id=scan_task_id,
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            )
            if sanitized is None:
                raise RuntimeError(f"Sanitization failed for {field_label} (returned None)")
            if not sanitized.strip():
                raise RuntimeError(f"Sanitization blocked {field_label} due to high prompt injection risk")
            return sanitized

    async def _sanitize_one(path: str, text: str, scan_task_id: str) -> Tuple[str, str]:
        sanitized = await _scan(text, scan_task_id, f"field '{path}'")
        return path, sanitized

    async def _sanitize_batch(
        batch: List[Tuple[str, str]],
        batch_index: int,
    ) -> List[Tuple[str, str]]:
        combined = SEMANTIC_SCAN_FIELD_SEPARATOR.join(text for _, text in batch)
        sanitized = await _scan(
            combined,
            f"{task_id}_batch_{batch_index}",
            f"batch {batch_index}",
        )
        if len(batch) == 1:
            return [(batch[0][0], sanitized)]
        if sanitized == combined:
            return batch

        return await asyncio.gather(
            *[
                _sanitize_one(
                    path,
                    text,
                    f"{task_id}_batch_{batch_index}_field_{field_index}",
                )
                for field_index, (path, text) in enumerate(batch)
            ]
        )

    sanitized_batches = await asyncio.gather(
        *[
            _sanitize_batch(batch, batch_index)
            for batch_index, batch in enumerate(_batch_candidates(candidates))
        ]
    )
    for sanitized_batch in sanitized_batches:
        sanitized_by_path.update(sanitized_batch)

    for path, _ in candidates:
        _set_path_value(payload, path, sanitized_by_path[path])

    return payload
