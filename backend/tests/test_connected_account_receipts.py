# backend/tests/test_connected_account_receipts.py
#
# Tests for redacted connected-account receipt event publishing.
# Receipt payloads are sent to clients for chat-key encryption and must never
# carry provider tokens or plaintext account identities.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json

import pytest

from backend.tests.test_connected_account_permission_request import FakeCache


@pytest.mark.asyncio
async def test_connected_account_receipt_is_published_without_secrets() -> None:
    from backend.apps.ai.processing.connected_account_receipts import (
        publish_connected_account_action_receipt,
    )

    cache = FakeCache()
    ok = await publish_connected_account_action_receipt(
        cache_service=cache,
        user_id="user-1",
        payload={
            "chat_id": "chat-1",
            "message_id": "message-1",
            "action_id": "action-1",
            "receipt": {
                "app_id": "calendar",
                "skill_id": "create-event",
                "action": "write",
                "decision": "completed",
                "undo_available": True,
            },
        },
    )

    assert ok is True
    channel, message = cache.redis.published[0]
    event = json.loads(message)
    assert channel == "user_cache_events:user-1"
    assert event["event_type"] == "send_connected_account_action_receipt"
    assert event["payload"]["action_id"] == "action-1"


@pytest.mark.asyncio
async def test_connected_account_receipt_rejects_secret_fields() -> None:
    from backend.apps.ai.processing.connected_account_receipts import (
        publish_connected_account_action_receipt,
    )

    with pytest.raises(ValueError, match="forbidden field"):
        await publish_connected_account_action_receipt(
            cache_service=FakeCache(),
            user_id="user-1",
            payload={
                "chat_id": "chat-1",
                "action_id": "action-1",
                "receipt": {"access_token": "secret"},
            },
        )
