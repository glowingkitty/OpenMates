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


def attach_connected_account_action_metadata(
    *,
    results: Any,
    journal_entries: list[dict[str, Any]],
    undo_available: bool,
) -> None:
    """Attach opaque action IDs to result objects for client-side controls only."""

    action_ids = [
        str(entry.get("action_id"))
        for entry in journal_entries
        if entry.get("action_id")
    ]
    if not action_ids:
        return

    action_id = action_ids[0]
    for result in _iter_result_dicts(results):
        result["connected_account_action_id"] = action_id
        result["connected_account_undo_available"] = undo_available


def _iter_result_dicts(results: Any) -> list[dict[str, Any]]:
    if isinstance(results, list):
        output: list[dict[str, Any]] = []
        for item in results:
            output.extend(_iter_result_dicts(item))
        return output
    if not isinstance(results, dict):
        return []
    nested = results.get("results")
    if isinstance(nested, list):
        output = []
        for item in nested:
            output.extend(_iter_result_dicts(item))
        return output
    return [results]
