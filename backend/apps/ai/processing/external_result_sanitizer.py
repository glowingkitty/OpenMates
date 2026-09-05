# backend/apps/ai/processing/external_result_sanitizer.py
#
# Deterministic external result sanitization helpers for app skills.
# Applies prompt-injection scanning to long text fields from external APIs.
# Fails closed if sanitization fails or content is blocked, so issues are visible.

from __future__ import annotations

import asyncio
import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling
from backend.shared.python_utils.structured_content_sanitization import (
    MAX_UNIT_CHARS,
    StructuredScanError,
    classify_text_units,
    serialized_units_size,
)


SEMANTIC_SCAN_BATCH_TARGET_CHARS = 50_000
BOUNDARY_CONTEXT_CHARS = 256
PROMPT_INJECTION_PLACEHOLDER = "[PROMPT INJECTION DETECTED & REMOVED]"

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
    "extra_snippets",
    "notes",
    "details",
    "generative_summary",
    "nearby_places",
    "amenities",
}


def _key_name_for_path(path: str) -> str:
    if not path:
        return ""
    key = path.rsplit(".", 1)[-1]
    return re.sub(r"\[\d+\]$", "", key).lower()


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


def _split_text_units(path: str, text: str, first_unit_number: int) -> List[Dict[str, str]]:
    """Preserve text exactly while preferring paragraph and sentence boundaries."""
    chunks: List[str] = []
    remaining = text
    while len(remaining) > MAX_UNIT_CHARS:
        boundary = remaining.rfind("\n\n", 0, MAX_UNIT_CHARS + 1)
        if boundary <= 0:
            boundary = max(remaining.rfind(". ", 0, MAX_UNIT_CHARS + 1), remaining.rfind("\n", 0, MAX_UNIT_CHARS + 1))
        end = boundary + (2 if remaining[boundary:boundary + 2] == ". " else 0) if boundary > 0 else MAX_UNIT_CHARS
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    if remaining:
        chunks.append(remaining)
    return [{
        "id": f"unit-{first_unit_number + index}",
        "path": path,
        "text": chunk,
        "context_before": chunks[index - 1][-BOUNDARY_CONTEXT_CHARS:] if index else "",
        "context_after": chunks[index + 1][:BOUNDARY_CONTEXT_CHARS] if index + 1 < len(chunks) else "",
    } for index, chunk in enumerate(chunks)]


def _batch_candidates(candidates: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    batches: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    for candidate in candidates:
        if current and serialized_units_size([*current, candidate]) > SEMANTIC_SCAN_BATCH_TARGET_CHARS:
            batches.append(current)
            current = []
        current.append(candidate)

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
    app_id: Optional[str] = None,
    skill_id: Optional[str] = None,
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

    if max_parallel < 1:
        raise StructuredScanError("OUTPUT_SAFETY_INVALID")
    units: List[Dict[str, str]] = []
    cleaned_by_path: Dict[str, str] = {}
    for path, text in candidates:
        cleaned, _ = sanitize_text_for_ascii_smuggling(text, include_stats=True)
        cleaned_by_path[path] = cleaned
        if cleaned.strip():
            units.extend(_split_text_units(path, cleaned, len(units)))

    if not units:
        sanitized = copy.deepcopy(payload)
        for path, cleaned in cleaned_by_path.items():
            _set_path_value(sanitized, path, cleaned)
        return sanitized
    semaphore = asyncio.Semaphore(min(max_parallel, 4))

    async def _classify(batch: List[Dict[str, str]], index: int) -> Dict[str, str]:
        async with semaphore:
            return await classify_text_units(
                batch, task_id=f"{task_id}_batch_{index}", secrets_manager=secrets_manager, cache_service=cache_service
            )

    batch_tasks = [asyncio.create_task(_classify(batch, index)) for index, batch in enumerate(_batch_candidates(units))]
    try:
        classified_batches = await asyncio.gather(*batch_tasks)
    except BaseException:
        for batch_task in batch_tasks:
            batch_task.cancel()
        await asyncio.gather(*batch_tasks, return_exceptions=True)
        raise
    decisions_by_id: Dict[str, str] = {}
    for decisions in classified_batches:
        decisions_by_id.update(decisions)
    expected_ids = {unit["id"] for unit in units}
    if set(decisions_by_id) != expected_ids or any(
        decision not in {"safe", "injection"} for decision in decisions_by_id.values()
    ):
        raise StructuredScanError("OUTPUT_SAFETY_INVALID")

    # Build every replacement before touching the original payload, so errors remain atomic.
    replacements: Dict[str, str] = dict(cleaned_by_path)
    unsafe_paths: set[str] = set()
    for path, _ in candidates:
        field_units = [unit for unit in units if unit["path"] == path]
        has_injection = any(decisions_by_id[unit["id"]] == "injection" for unit in field_units)
        if app_id == "web" and skill_id == "search" and has_injection:
            replacements[path] = PROMPT_INJECTION_PLACEHOLDER
        else:
            replacements[path] = "".join(
                PROMPT_INJECTION_PLACEHOLDER if decisions_by_id[unit["id"]] == "injection" else unit["text"]
                for unit in field_units
            )
        if has_injection:
            unsafe_paths.add(path)
    sanitized = copy.deepcopy(payload)
    for path, value in replacements.items():
        _set_path_value(sanitized, path, value)
    if app_id == "web" and skill_id == "search":
        _omit_unsafe_search_results(sanitized, unsafe_paths)
    return sanitized


def _omit_unsafe_search_results(payload: Any, unsafe_paths: set[str]) -> None:
    """Search titles and URLs identify a result, so their unsafe result is omitted."""
    removals: dict[tuple[str, ...], set[int]] = {}
    for path in unsafe_paths:
        if _key_name_for_path(path) not in {"title", "url"}:
            continue
        tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
        if len(tokens) < 2 or not tokens[-2].startswith("["):
            continue
        removals.setdefault(tuple(tokens[:-2]), set()).add(int(tokens[-2][1:-1]))
    for container_tokens, indexes in removals.items():
        current = payload
        for token in container_tokens:
            current = current[int(token[1:-1])] if token.startswith("[") else current[token]
        if isinstance(current, list):
            for index in sorted(indexes, reverse=True):
                if index < len(current):
                    current.pop(index)
