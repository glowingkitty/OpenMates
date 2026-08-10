# backend/apps/ai/utils/app_skill_json_cleanup.py
#
# Utilities for reducing app-skill transport metadata to the canonical fields
# needed to reconstruct the permanent execution group after completion/reload.

from __future__ import annotations

import json
import logging
import re
from collections.abc import Collection


logger = logging.getLogger(__name__)

APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN = re.compile(
    r"```(?:json|json_embed)\s*\n\s*(\{.*?\})\s*\n```",
    re.DOTALL,
)
SMART_JSON_QUOTE_TRANSLATION = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
    }
)


def _load_protocol_json_payload(raw_payload: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        normalized_payload = raw_payload.translate(SMART_JSON_QUOTE_TRANSLATION)
        if normalized_payload == raw_payload:
            return None
        try:
            payload = json.loads(normalized_payload)
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    return payload


def canonicalize_app_skill_json_blocks(text: str, log_prefix: str = "") -> str:
    """Keep app-skill identity/order while removing non-canonical request metadata."""
    if not text:
        return text

    canonicalized_count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal canonicalized_count
        payload = _load_protocol_json_payload(match.group(1))
        if payload is None:
            return match.group(0)

        if payload.get("type") != "app_skill_use":
            return match.group(0)
        embed_id = payload.get("embed_id")
        if not isinstance(embed_id, str) or not embed_id.strip():
            return match.group(0)

        canonical_payload = {
            key: payload[key]
            for key in ("type", "embed_id", "app_id", "skill_id")
            if key in payload
        }
        canonical_payload["embed_id"] = embed_id.strip()
        canonicalized_count += 1
        return f"```json\n{json.dumps(canonical_payload, separators=(',', ':'))}\n```"

    cleaned = APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN.sub(replace_match, text)
    if canonicalized_count == 0:
        return text

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    logger.info(
        "%s [APP_SKILL_JSON_CLEANUP] Canonicalized %s app_skill_use JSON fence(s)",
        log_prefix,
        canonicalized_count,
    )
    return cleaned


def strip_failed_app_skill_json_blocks(
    text: str,
    failed_embed_ids: Collection[str],
    log_prefix: str = "",
) -> tuple[str, int]:
    """Remove app-skill protocol fences for embeds that failed during execution."""
    if not text or not failed_embed_ids:
        return text, 0

    failed_ids = {
        embed_id.strip() for embed_id in failed_embed_ids if embed_id.strip()
    }
    if not failed_ids:
        return text, 0

    stripped_count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal stripped_count
        payload = _load_protocol_json_payload(match.group(1))
        if payload is None:
            return match.group(0)
        if payload.get("type") != "app_skill_use":
            return match.group(0)

        embed_id = payload.get("embed_id")
        if not isinstance(embed_id, str) or embed_id.strip() not in failed_ids:
            return match.group(0)

        stripped_count += 1
        return ""

    cleaned = APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN.sub(replace_match, text)
    if stripped_count == 0:
        return text, 0

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    logger.info(
        "%s [APP_SKILL_JSON_CLEANUP] Stripped %s failed app_skill_use JSON fence(s)",
        log_prefix,
        stripped_count,
    )
    return cleaned, stripped_count
