"""Throughline helpline directory client.

Official API: https://developer.throughlinecare.com. The key lives in Vault at
kv/data/providers/throughline under `api_key`. Without it `fetch_helplines`
returns None and the caller builds the emergency-only card.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SECRET_PATH = "kv/data/providers/throughline"
SECRET_KEY = "api_key"
HELPLINES_URL = "https://api.throughlinecare.com/v1/helplines"
REQUEST_TIMEOUT_SECONDS = 2.5
MAX_LINES = 4


class ThroughlineError(RuntimeError):
    """The directory answered with an error or an unreadable body."""


async def _api_key(secrets_manager: Any) -> str | None:
    if secrets_manager is None:
        return None
    key = await secrets_manager.get_secret(secret_path=SECRET_PATH, secret_key=SECRET_KEY)
    return key if key and key != "IMPORTED_TO_VAULT" else None


def _text(value: Any) -> str | None:
    return value.strip()[:200] if isinstance(value, str) and value.strip() else None


def normalize_line(row: Any) -> dict[str, Any] | None:
    """Reduce one directory row to the card line shape, or None when it has no contact route."""
    if not isinstance(row, dict) or not _text(row.get("name")):
        return None
    topics = row.get("topics")
    line = {
        "name": _text(row.get("name")), "phone": _text(row.get("phone")), "sms": _text(row.get("sms")),
        "chat_url": _text(row.get("chat_url")), "hours": _text(row.get("hours")),
        "topics": [t for t in topics if isinstance(t, str)][:4] if isinstance(topics, list) else [],
    }
    return line if line["phone"] or line["sms"] or line["chat_url"] else None


async def fetch_helplines(secrets_manager: Any, country: str, language: str) -> list[dict[str, Any]] | None:
    """Return up to four crisis lines for the country, or None when the key is not configured."""
    key = await _api_key(secrets_manager)
    if key is None:
        logger.info("Helpline directory key not configured; using the emergency-only card")
        return None
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                HELPLINES_URL, params={"country": country, "language": language, "topic": "crisis"},
                headers={"Authorization": f"Bearer {key}"},
            )
            response.raise_for_status()
            rows = response.json().get("helplines")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise ThroughlineError(f"helpline directory request failed: {type(exc).__name__}") from exc
    if not isinstance(rows, list):
        raise ThroughlineError("helpline directory returned no list")
    return [line for line in (normalize_line(row) for row in rows) if line][:MAX_LINES]
