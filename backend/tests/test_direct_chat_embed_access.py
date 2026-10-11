"""Regression checks for Team direct-chat embed authorization.

The first scoped chat lookup deliberately selects only routing fields. A
second metadata read identifies private chats and must fail closed when it
cannot return the authoritative row. Both embed-page and reference paths
must enforce the same participant check before exposing embed metadata.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.embeds_api import (
    _reference_target_scope,
    _require_chat_embed_read,
)
from backend.core.api.app.services.directus.team_methods import hash_id


CHAT_ID = "00000000-0000-0000-0000-000000000001"
TEAM_ID = "team"


class FakeTeam:
    async def require_team_role(self, *_args, **_kwargs):
        return {"role": "admin"}


class FakeChat:
    def __init__(self, metadata):
        self.metadata = metadata

    async def get_chat_metadata(self, *_args, **_kwargs):
        return self.metadata


class FakeDirectus:
    def __init__(self, metadata):
        self.team = FakeTeam()
        self.chat = FakeChat(metadata)

    async def get_items(self, collection, *_args, **_kwargs):
        if collection == "chats":
            return [{"id": CHAT_ID, "hashed_team_id": hash_id(TEAM_ID),
                     "hashed_user_id": hash_id("alice"), "storage_state": "hot"}]
        if collection == "team_memberships":
            return [{"id": "active-membership"}]
        if collection == "teams":
            return [{"id": TEAM_ID}]
        raise AssertionError(collection)


def direct_row():
    alice, bob = hash_id("alice"), hash_id("bob")
    return {
        "id": CHAT_ID, "hashed_team_id": hash_id(TEAM_ID),
        "chat_visibility": "direct", "participant_user_hashes": [alice, bob],
        "participant_key_envelopes": {
            alice: {"key_id": "alice-key", "encrypted_chat_key": "OMDM1." + "a" * 40},
            bob: {"key_id": "bob-key", "encrypted_chat_key": "OMDM1." + "b" * 40},
        },
        "encrypted_chat_key": None,
    }


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation
@pytest.mark.anyio
@pytest.mark.parametrize("metadata", [None, {"id": "wrong-chat"}])
async def test_embed_scopes_reject_missing_or_mismatched_second_metadata(metadata):
    directus = FakeDirectus(metadata)
    actor = SimpleNamespace(id="admin")
    with pytest.raises(HTTPException) as read_error:
        await _require_chat_embed_read(CHAT_ID, TEAM_ID, actor, directus)
    assert read_error.value.status_code == 503
    with pytest.raises(HTTPException) as reference_error:
        await _reference_target_scope(CHAT_ID, TEAM_ID, actor, directus, write_required=False)
    assert reference_error.value.status_code == 503


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation
@pytest.mark.anyio
async def test_embed_scopes_allow_participant_and_reject_team_admin():
    directus = FakeDirectus(direct_row())
    participant = SimpleNamespace(id="alice")
    admin = SimpleNamespace(id="admin")
    await _require_chat_embed_read(CHAT_ID, TEAM_ID, participant, directus)
    assert await _reference_target_scope(CHAT_ID, TEAM_ID, participant, directus, write_required=False) == (
        hash_id(CHAT_ID), hash_id("alice"), True, True,
    )
    with pytest.raises(HTTPException) as read_error:
        await _require_chat_embed_read(CHAT_ID, TEAM_ID, admin, directus)
    assert read_error.value.status_code == 404
    with pytest.raises(HTTPException) as reference_error:
        await _reference_target_scope(CHAT_ID, TEAM_ID, admin, directus, write_required=False)
    assert reference_error.value.status_code == 404
