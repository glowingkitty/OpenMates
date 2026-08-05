# backend/apps/ai/utils/app_skill_json_cleanup.py
#
# Utilities for reducing app-skill transport metadata to the canonical fields
# needed to reconstruct the permanent execution group after completion/reload.

from __future__ import annotations

import json
import logging
import re


logger = logging.getLogger(__name__)

APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN = re.compile(
    r"```(?:json|json_embed)\s*\n\s*(\{.*?\})\s*\n```",
    re.DOTALL,
)


def canonicalize_app_skill_json_blocks(text: str, log_prefix: str = "") -> str:
    """Keep app-skill identity/order while removing non-canonical request metadata."""
    if not text:
        return text

    canonicalized_count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal canonicalized_count
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
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
