"""Participant access to Team direct chats is independent of Team role."""

import json

import pytest

from backend.core.api.app.services.direct_chat_access import (
    filter_direct_chat_metadata,
    is_direct_chat,
    is_personal_retention_chat,
    project_direct_chat_metadata,
    require_direct_chat_access,
    validate_direct_chat_metadata,
)
from backend.core.api.app.services.directus.team_methods import hash_id


def direct_row():
    alice, bob = hash_id("alice"), hash_id("bob")
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "hashed_team_id": hash_id("team"),
        "chat_visibility": "direct",
        "participant_user_hashes": [alice, bob],
        "participant_key_envelopes": {
            alice: {"key_id": "key-alice", "encrypted_chat_key": "OMDM1." + "a" * 40},
            bob: {"key_id": "key-bob", "encrypted_chat_key": "OMDM1." + "b" * 40},
        },
        "encrypted_chat_key": None,
    }


class FakeDirectus:
    def __init__(self, *, active=True):
        self.active = active

    async def get_items(self, collection, params, **_kwargs):
        if not self.active:
            return []
        if collection == "team_memberships":
            return [{"id": "membership"}]
        if collection == "teams":
            return [{"id": "team"}]
        raise AssertionError(collection)


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation
@pytest.mark.anyio
async def test_only_active_participant_gets_own_envelope():
    row = direct_row()
    projected = await require_direct_chat_access(FakeDirectus(), row, "alice", "team")
    assert projected["encrypted_chat_key"] == "OMDM1." + "a" * 40
    assert projected["participant_user_hashes"] == [hash_id("alice"), hash_id("bob")]
    assert "participant_key_envelopes" not in projected
    assert await require_direct_chat_access(FakeDirectus(), projected, "alice", "team") == projected
    with pytest.raises(PermissionError):
        await require_direct_chat_access(FakeDirectus(), row, "admin", "team")
    with pytest.raises(PermissionError):
        await require_direct_chat_access(FakeDirectus(active=False), row, "alice", "team")
    with pytest.raises(PermissionError):
        await require_direct_chat_access(FakeDirectus(), row, "alice", "other-team")


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation
@pytest.mark.anyio
async def test_malformed_marked_rows_are_restricted_and_filtered():
    row = direct_row()
    malformed = dict(row, chat_visibility=None)
    assert is_direct_chat(malformed)
    with pytest.raises(ValueError):
        project_direct_chat_metadata(malformed, "alice")
    malformed = dict(row, participant_user_hashes=json.dumps([["nested"], hash_id("bob")]))
    with pytest.raises(ValueError):
        validate_direct_chat_metadata(malformed)
    ordinary = {"id": "ordinary", "chat_visibility": "team"}
    assert await filter_direct_chat_metadata(FakeDirectus(), [ordinary, row], "admin", "team") == [ordinary]


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation
def test_personal_retention_excludes_team_and_direct_chats():
    owner = hash_id("alice")
    personal = {"id": "personal", "hashed_user_id": owner, "hashed_team_id": None}
    team = {**personal, "id": "team", "hashed_team_id": hash_id("team")}
    malformed_direct = {**personal, "id": "malformed", "participant_user_hashes": []}
    assert is_personal_retention_chat(personal, owner)
    assert not is_personal_retention_chat(team, owner)
    assert not is_personal_retention_chat(direct_row(), owner)
    assert not is_personal_retention_chat(malformed_direct, owner)
    assert not is_personal_retention_chat(personal, hash_id("bob"))
