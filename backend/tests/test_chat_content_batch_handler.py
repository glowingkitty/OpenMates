"""Focused regressions for on-demand chat content hydration."""

import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.chat_content_batch_handler import (
    _fetch_complete_embeds_for_chat,
    _send_apps_legacy_embed_page,
)


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_partial_embed_cache_merges_authoritative_parent_and_child() -> None:
    class FakeCache:
        async def get_sync_embeds_for_chat(self, chat_id):
            assert chat_id == "chat-1"
            return [
                {
                    "embed_id": "parent-1",
                    "status": "processing",
                    "embed_ids": None,
                    "encrypted_content": "stale-parent",
                },
                {
                    "embed_id": "live-cache-only",
                    "status": "processing",
                    "encrypted_content": "pending-persistence",
                },
            ]

    class FakeDirectusEmbed:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
            assert hashed_chat_id == "hashed-chat-1"
            return [
                {
                    "embed_id": "parent-1",
                    "status": "finished",
                    "embed_ids": ["child-1"],
                    "encrypted_content": "final-parent",
                },
                {
                    "embed_id": "child-1",
                    "status": "finished",
                    "parent_embed_id": "parent-1",
                    "encrypted_content": "transcript-child",
                },
            ]

    class FakeDirectus:
        embed = FakeDirectusEmbed()

    embeds = await _fetch_complete_embeds_for_chat(
        FakeCache(),
        FakeDirectus(),
        "chat-1",
        "hashed-chat-1",
    )
    by_id = {embed["embed_id"]: embed for embed in embeds}

    assert set(by_id) == {"parent-1", "child-1", "live-cache-only"}
    assert by_id["parent-1"]["status"] == "finished"
    assert by_id["parent-1"]["embed_ids"] == ["child-1"]
    assert by_id["child-1"]["parent_embed_id"] == "parent-1"


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_cached_embeds_remain_available_when_persisted_read_fails() -> None:
    cached = {"embed_id": "cached-1", "status": "finished"}

    class FakeCache:
        async def get_sync_embeds_for_chat(self, chat_id):
            return [cached]

    class FailingDirectusEmbed:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
            raise RuntimeError("unavailable")

    class FakeDirectus:
        embed = FailingDirectusEmbed()

    embeds = await _fetch_complete_embeds_for_chat(
        FakeCache(),
        FakeDirectus(),
        "chat-1",
        "hashed-chat-1",
    )

    assert embeds == [cached]


CHAT_ID = "11000000-0000-4000-8000-000000000000"
REQUEST_ID = "12000000-0000-4000-8000-000000000000"


class _LegacyPageManager:
    def __init__(self) -> None:
        self.sent = []

    async def send_personal_message(self, **kwargs):
        self.sent.append(kwargs["message"]["payload"])


class _LegacyPageDirectus:
    def __init__(self, user_id="owner", team_id=None, rows=None):
        self.user_id = user_id
        self.team_id = team_id
        self.rows = [{"hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
                      "hashed_team_id": hashlib.sha256(team_id.encode()).hexdigest() if team_id else None,
                      **row}
                     for row in (rows or [])]
        self.reads = []
        self.roles = []
        self.chat = self
        self.team = self

    async def require_team_role(self, team_id, user_id, roles):
        self.roles.append((team_id, user_id, roles))
        return {"role": "viewer"}

    async def get_chat_metadata(self, chat_id, admin_required=False):
        assert chat_id == CHAT_ID and admin_required
        return {
            "hashed_user_id": hashlib.sha256(self.user_id.encode()).hexdigest(),
            "hashed_team_id": hashlib.sha256(self.team_id.encode()).hexdigest() if self.team_id else None,
        }

    async def get_items(self, collection, params, **kwargs):
        self.reads.append((collection, params))
        if collection == "embeds":
            return self.rows[params["offset"]:params["offset"] + params["limit"]]
        return []


# contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
@pytest.mark.anyio
async def test_legacy_embeds_only_page_is_bounded_and_omits_messages() -> None:
    rows = [{"embed_id": f"{i:08x}-0000-4000-8000-000000000000", "encrypted_content": "ciphertext"} for i in range(51)]
    directus = _LegacyPageDirectus(rows=rows)
    manager = _LegacyPageManager()
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="owner", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID, "embed_offset": 0, "apps_legacy_embeds_only": True},
    )
    response = manager.sent[0]
    assert "error" not in response
    assert len(response["embeds"]) == 50
    assert response["next_embed_offset"] == 50
    assert response["messages_by_chat_id"] == {}
    assert directus.reads[0][1]["filter[parent_embed_id][_null]"] is True


# contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
@pytest.mark.anyio
async def test_legacy_team_page_requires_verified_chat_scope_before_ciphertext_read() -> None:
    manager = _LegacyPageManager()
    directus = _LegacyPageDirectus(user_id="creator", team_id=None, rows=[{"embed_id": REQUEST_ID}])
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="viewer", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID,
                 "team_id": "13000000-0000-4000-8000-000000000000"},
    )
    assert manager.sent[0]["embeds"] == []
    assert manager.sent[0]["error"]
    assert directus.reads == []
    assert directus.roles[0][2] == {"owner", "admin", "member", "viewer"}

    directus = _LegacyPageDirectus(user_id="creator", team_id="13000000-0000-4000-8000-000000000000",
                                   rows=[{"embed_id": REQUEST_ID, "encrypted_content": "ciphertext"}])
    manager = _LegacyPageManager()
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="viewer", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID, "team_id": directus.team_id},
    )
    assert [row["embed_id"] for row in manager.sent[0]["embeds"]] == [REQUEST_ID]

    # A viewer cannot fetch an unscoped Personal row merely by supplying the
    # hashed ID of a Team chat they can read.
    directus.rows[0]["hashed_team_id"] = None
    manager = _LegacyPageManager()
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="viewer", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID, "team_id": directus.team_id},
    )
    assert manager.sent[0]["embeds"] == []


# contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
@pytest.mark.anyio
async def test_legacy_personal_page_rejects_another_owner_before_ciphertext_read() -> None:
    manager = _LegacyPageManager()
    directus = _LegacyPageDirectus(user_id="another-owner", rows=[{"embed_id": REQUEST_ID}])
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="owner", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID},
    )
    assert manager.sent[0]["error"]
    assert directus.reads == []

    directus = _LegacyPageDirectus(user_id="owner", rows=[{
        "embed_id": REQUEST_ID,
        "hashed_team_id": hashlib.sha256(b"some-team").hexdigest(),
    }])
    manager = _LegacyPageManager()
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=directus, user_id="owner", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID},
    )
    assert manager.sent[0]["embeds"] == []


# contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
@pytest.mark.anyio
async def test_legacy_page_does_not_advance_on_failed_ciphertext_read() -> None:
    class FailedRead(_LegacyPageDirectus):
        async def get_items(self, collection, params, **kwargs):
            return None

    manager = _LegacyPageManager()
    await _send_apps_legacy_embed_page(
        manager=manager, directus_service=FailedRead(), user_id="owner", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID], "request_id": REQUEST_ID, "embed_offset": 50},
    )
    assert manager.sent[0]["error"]
    assert manager.sent[0]["next_embed_offset"] is None
