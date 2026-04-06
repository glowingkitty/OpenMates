"""
backend/shared/python_utils/discord_webhook.py

Minimal Discord webhook poster used for test-run and smoke-test notifications
(OPE-76). A standalone httpx POST keeps this independent of any MJML / email
pipeline so Discord remains a working fallback channel even when the primary
email path is broken.

Design notes
------------
- Failures are caught and logged, never raised. A down Discord webhook must NOT
  break the calling Celery task or CI workflow — it's the *fallback* channel.
- Truncation is enforced for both `content` and embed `description` fields to
  stay within Discord's hard limits (2000 chars content, 4096 chars description).
- Colors are encoded as integers to match Discord's embed API.

Usage:
    from backend.shared.python_utils.discord_webhook import post_discord_message
    await post_discord_message(
        webhook_url=...,
        content="Prod smoke test failed at 14:00 CEST",
        embeds=[{
            "title": "prod-smoke 14:00 FAILED",
            "description": "login-chat spec timed out",
            "color": 0xEF4444,
        }],
    )
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Discord hard limits (see https://discord.com/developers/docs/resources/webhook)
_MAX_CONTENT_LEN = 2000
_MAX_EMBED_DESCRIPTION_LEN = 4096
_HTTP_TIMEOUT_SECONDS = 10.0


async def post_discord_message(
    webhook_url: str,
    content: Optional[str] = None,
    embeds: Optional[List[Dict[str, Any]]] = None,
    username: Optional[str] = None,
) -> bool:
    """
    Post a message to a Discord webhook.

    Args:
        webhook_url: Full Discord webhook URL. If empty/None, the call is a
            no-op (returns False) — useful so callers can pass a possibly-unset
            env var without branching.
        content: Optional plain-text content (truncated to 2000 chars).
        embeds: Optional list of Discord embed dicts. Each embed's description
            is truncated to 4096 chars.
        username: Optional username override displayed in Discord.

    Returns:
        True if the webhook accepted the payload (HTTP 2xx), False otherwise.
        Never raises — this function is designed as a best-effort fallback.
    """
    if not webhook_url:
        logger.debug("post_discord_message called with empty webhook_url — skipping")
        return False

    if not content and not embeds:
        logger.warning("post_discord_message called with no content or embeds — skipping")
        return False

    payload: Dict[str, Any] = {}

    if content:
        payload["content"] = content[:_MAX_CONTENT_LEN]

    if embeds:
        truncated_embeds: List[Dict[str, Any]] = []
        for embed in embeds:
            embed_copy = dict(embed)
            description = embed_copy.get("description")
            if isinstance(description, str) and len(description) > _MAX_EMBED_DESCRIPTION_LEN:
                embed_copy["description"] = description[: _MAX_EMBED_DESCRIPTION_LEN - 3] + "..."
            truncated_embeds.append(embed_copy)
        payload["embeds"] = truncated_embeds

    if username:
        payload["username"] = username

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(webhook_url, json=payload)
        if 200 <= response.status_code < 300:
            logger.info(f"Discord webhook POST succeeded (status={response.status_code})")
            return True
        logger.error(
            f"Discord webhook POST failed: HTTP {response.status_code} — {response.text[:300]}"
        )
        return False
    except httpx.HTTPError as exc:
        logger.error(f"Discord webhook POST raised HTTP error: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - fallback channel must never raise
        logger.error(f"Discord webhook POST raised unexpected error: {exc}", exc_info=True)
        return False
