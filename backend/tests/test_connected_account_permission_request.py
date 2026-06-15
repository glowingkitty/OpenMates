# backend/tests/test_connected_account_permission_request.py
#
# Tests for redacted connected-account permission request creation.
# Permission prompts may include action/account refs, but must never persist or
# broadcast refresh/access tokens or provider plaintext identifiers.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class FakeCache:
    def __init__(self) -> None:
        self.redis = FakeRedis()
        self.pending: dict[str, dict] = {}
        self.ttls: dict[str, int] = {}

    @property
    async def client(self):
        return self.redis

    async def store_pending_connected_account_permission_request(
        self,
        request_id: str,
        context: dict,
        ttl: int,
    ) -> bool:
        self.pending[request_id] = context
        self.ttls[request_id] = ttl
        return True


@pytest.mark.asyncio
async def test_connected_account_permission_request_is_redacted_and_published() -> None:
    from backend.apps.ai.processing.connected_account_permission_request import (
        CONNECTED_ACCOUNT_PERMISSION_TTL_SECONDS,
        create_connected_account_permission_request,
    )

    cache = FakeCache()

    request_id = await create_connected_account_permission_request(
        cache_service=cache,
        user_id="user-1",
        chat_id="chat-1",
        message_id="message-1",
        user_id_hash="hash-1",
        app_id="calendar",
        skill_id="create-event",
        action="write",
        skill_arguments={
            "requests": [
                {
                    "calendar_id": "primary",
                    "summary": "Planning meeting",
                    "start": "2026-06-15T10:00:00Z",
                    "end": "2026-06-15T11:00:00Z",
                }
            ]
        },
        connected_account_directory=[
            {
                "connected_account_id": "acct-1",
                "app_id": "calendar",
                "account_ref": "acct-ref",
                "label": "Work calendar",
                "capabilities": ["read", "write"],
                "runtime_modes": {"write": "always_ask"},
            }
        ],
        reason="Always ask is enabled for this action.",
        task_id="task-1",
    )

    assert request_id is not None
    assert request_id in cache.pending
    assert cache.ttls[request_id] == CONNECTED_ACCOUNT_PERMISSION_TTL_SECONDS
    assert len(cache.redis.published) == 1

    channel, message = cache.redis.published[0]
    event = json.loads(message)
    payload = event["payload"]

    assert channel == "user_cache_events:user-1"
    assert event["event_type"] == "send_connected_account_permission_request"
    assert payload["request_id"] == request_id
    assert payload["accounts"][0]["connected_account_id"] == "acct-1"
    assert payload["requests"][0]["action"] == "write"
    assert "Planning meeting" in json.dumps(payload)
    serialized = json.dumps({"payload": payload, "pending": cache.pending[request_id]})
    assert "refresh_token" not in serialized
    assert "access_token" not in serialized
    assert "provider_account_id" not in serialized


@pytest.mark.asyncio
async def test_connected_account_permission_request_rejects_secret_fields() -> None:
    from backend.apps.ai.processing.connected_account_permission_request import create_connected_account_permission_request

    with pytest.raises(ValueError, match="forbidden field"):
        await create_connected_account_permission_request(
            cache_service=FakeCache(),
            user_id="user-1",
            chat_id="chat-1",
            message_id="message-1",
            user_id_hash="hash-1",
            app_id="calendar",
            skill_id="get-events",
            action="read",
            skill_arguments={"requests": [{"calendar_id": "primary", "access_token_handle": "ath_secret"}]},
            connected_account_directory=[],
            reason="test",
            task_id="task-1",
        )
