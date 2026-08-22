"""Teams V1 realtime fanout contract tests.

Team collaboration events target all active members, not only the sender's
devices. The relay carries client ciphertext and safe operational state without
introducing message plaintext into backend payloads or logs.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.team_realtime_service import broadcast_team_event, connected_team_member_user_ids


class RecordingManager:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.active_connections = {"alice": {"a": object()}, "bob": {"b": object()}, "outsider": {"x": object()}}

    async def broadcast_to_user_specific_event(self, user_id: str, event_name: str, payload: dict) -> None:
        self.events.append((user_id, event_name, payload))


class RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


class RecordingCache:
    def __init__(self) -> None:
        self.redis = RecordingRedis()

    @property
    async def client(self) -> RecordingRedis:
        return self.redis


# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_active_members_receive_encrypted_human_message_event() -> None:
    manager = RecordingManager()
    payload = {
        "team_id": "team-1",
        "chat_id": "chat-1",
        "message_id": "message-1",
        "encrypted_content": "client-ciphertext",
    }

    await broadcast_team_event(
        manager=manager,
        active_member_user_ids=["alice", "bob", "alice"],
        event_name="team_chat_message_created",
        payload=payload,
    )

    assert manager.events == [
        ("alice", "team_chat_message_created", payload),
        ("bob", "team_chat_message_created", payload),
    ]
    assert "content" not in payload


# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync
@pytest.mark.anyio
async def test_processing_and_final_events_reach_every_active_member() -> None:
    manager = RecordingManager()

    for event_name in ("team_ai_processing", "team_ai_response_completed"):
        await broadcast_team_event(
            manager=manager,
            active_member_user_ids=["alice", "bob"],
            event_name=event_name,
            payload={"team_id": "team-1", "chat_id": "chat-1", "message_id": "message-2"},
        )

    assert [(user_id, event_name) for user_id, event_name, _payload in manager.events] == [
        ("alice", "team_ai_processing"),
        ("bob", "team_ai_processing"),
        ("alice", "team_ai_response_completed"),
        ("bob", "team_ai_response_completed"),
    ]


# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync
def test_connected_recipients_are_intersected_with_active_membership_hashes() -> None:
    manager = RecordingManager()

    recipients = connected_team_member_user_ids(manager, {hash_id("alice"), hash_id("bob"), hash_id("offline")})

    assert recipients == ("alice", "bob")


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_realtime_rejects_plaintext_message_fields() -> None:
    with pytest.raises(ValueError, match="unapproved fields"):
        await broadcast_team_event(
            manager=RecordingManager(),
            active_member_user_ids=["alice"],
            event_name="team_chat_message_created",
            payload={"team_id": "team-1", "content": "private"},
        )

    with pytest.raises(ValueError, match="unapproved fields"):
        await broadcast_team_event(
            manager=RecordingManager(),
            active_member_user_ids=["alice"],
            event_name="team_chat_message_created",
            payload={"team_id": "team-1", "message_history": [{"content": "private"}]},
        )


# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync
@pytest.mark.anyio
async def test_team_event_uses_cross_process_user_channel_when_cache_is_available() -> None:
    cache = RecordingCache()
    payload = {"team_id": "team-1", "chat_id": "chat-1", "message_id": "message-1", "ai_task_id": "task-1", "status": "processing_started"}

    await broadcast_team_event(
        manager=RecordingManager(),
        active_member_user_ids=["alice"],
        event_name="team_ai_processing",
        payload=payload,
        cache_service=cache,
        active_member_hashes={hash_id("alice")},
    )

    assert cache.redis.published[0][0] == f"websocket:user:{hash_id('alice')}"
    assert "user_id_uuid" not in cache.redis.published[0][1]
