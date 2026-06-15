# backend/apps/ai/processing/connected_account_receipts.py
#
# Publishes redacted connected-account operation receipts to active clients.
# Clients encrypt these receipts with the chat key before persisting them as
# system messages, preserving zero-knowledge chat storage.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import logging
from typing import Any

from backend.apps.ai.processing.connected_account_permission_request import (
    _assert_no_connected_account_secrets,
)

logger = logging.getLogger(__name__)


async def publish_connected_account_action_receipt(
    *,
    cache_service: Any,
    user_id: str,
    payload: dict[str, Any],
) -> bool:
    """Publish a redacted receipt request for client-side encrypted persistence."""

    _assert_no_connected_account_secrets(payload)
    try:
        redis_client = await cache_service.client
        if not redis_client:
            return False
        await redis_client.publish(
            f"user_cache_events:{user_id}",
            json.dumps(
                {
                    "event_type": "send_connected_account_action_receipt",
                    "payload": payload,
                }
            ),
        )
        return True
    except Exception as exc:
        logger.warning("Could not publish connected-account action receipt: %s", exc)
        return False
