# backend/apps/ai/utils/app_skill_json_cleanup.py
#
# Utilities for removing app-skill transport metadata from assistant-visible
# markdown. App-skill embed records are persisted separately; the raw JSON fence
# is only a streaming transport detail and should not be saved as message text.

from __future__ import annotations

import json
import logging
import re


logger = logging.getLogger(__name__)

APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN = re.compile(
    r'```(?:json|json_embed)\s*\n\s*(\{[^`]*?"embed_id"\s*:\s*"([^"]+)"[^`]*?\})\s*\n```',
    re.DOTALL,
)


def strip_successful_app_skill_json_blocks(text: str, log_prefix: str = "") -> str:
    """Remove assistant-visible app-skill transport fences after embeds are persisted."""
    if not text:
        return text

    stripped_count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal stripped_count
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(0)

        if payload.get("type") != "app_skill_use":
            return match.group(0)
        embed_id = payload.get("embed_id")
        if not isinstance(embed_id, str) or not embed_id.strip():
            return match.group(0)

        stripped_count += 1
        return ""

    cleaned = APP_SKILL_EMBED_REFERENCE_FENCE_PATTERN.sub(replace_match, text)
    if stripped_count == 0:
        return text

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    logger.info(
        "%s [APP_SKILL_JSON_CLEANUP] Stripped %s app_skill_use JSON fence(s) from assistant text",
        log_prefix,
        stripped_count,
    )
    return cleaned
