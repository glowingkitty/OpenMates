"""Focused regressions for on-demand chat content hydration."""

import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_content_batch_handler as handler
from backend.core.api.app.routes.handlers.websocket_handlers.chat_content_batch_handler import (
    _send_apps_legacy_embed_page,
)


class _WindowManager:
    def __init__(self):
        self.sent = []

    async def send_personal_message(self, **kwargs):
        self.sent.append(kwargs["message"]["payload"])


class _WindowCache:
    def __init__(self):
        self.removed = []

    async def remove_chat_from_ids_versions(self, user_id, chat_id):
        self.removed.append((user_id, chat_id))
        return True

    async def get_chat_versions(self, user_id, chat_id):
        return None

    async def get_sync_embeds_for_chat(self, chat_id):
        raise AssertionError("bounded hydration must not materialize the whole cache")


class _WindowDirectus:
    def __init__(self, embed_window):
        self.embed_window = embed_window
        self.chat = self
        self.embed = self
        self.chat_key_wrapper = self
        self.embed_reads = []

    async def get_items(self, collection, params, **kwargs):
        assert collection == "chats" and kwargs["raise_on_error"] is True
        assert params["limit"] == len(params["filter"]["id"]["_in"]) <= 5
        return [{"id": chat_id, "hashed_user_id": hashlib.sha256(b"owner").hexdigest(),
                 "storage_state": "hot", "messages_v": 3}
                for chat_id in params["filter"]["id"]["_in"]]


    async def check_chat_ownership(self, chat_id, user_id):
        raise AssertionError("cache membership must not authorize batch content")

    async def get_chat_metadata(self, chat_id):
        return {"messages_v": 3}

    async def get_embed_window_by_hashed_chat_id(self, hashed_chat_id):
        self.embed_reads.append(hashed_chat_id)
        if isinstance(self.embed_window, Exception):
            raise self.embed_window
        return self.embed_window

    async def get_sync_embed_key_window_for_page(self, hashed_chat_id, owner_hash, embed_hashes):
        assert hashed_chat_id == hashlib.sha256(CHAT_ID.encode()).hexdigest()
        assert owner_hash == hashlib.sha256(b"owner").hexdigest()
        assert embed_hashes == [hashlib.sha256(row["embed_id"].encode()).hexdigest()
                                for row in self.embed_window["embeds"]]
        return {"embed_keys": [{"id": "key-1", "encrypted_embed_key": "cipher"}],
                "has_more_before": False, "start_cursor": None, "oversized_key_id": None}

    async def get_sync_wrapper_window_for_chat(self, hashed_chat_id, *, hashed_user_id=None, hashed_team_id=None):
        assert hashed_chat_id == hashlib.sha256(CHAT_ID.encode()).hexdigest()
        if hashed_team_id:
            assert hashed_user_id is None and hashed_team_id == hashlib.sha256(b"team").hexdigest()
        else:
            assert hashed_user_id == hashlib.sha256(b"owner").hexdigest()
        return {"wrappers": [{"key_type": "team", "encrypted_chat_key": "cipher"}] if hashed_team_id else [],
                "has_more_before": False, "start_cursor": None,
                "oversized_wrapper_id": None}


async def _run_window_request(monkeypatch, directus, cache=None):
    async def message_window(**kwargs):
        return {"messages": ["encrypted-message"], "has_more_before": True,
                "start_cursor": {"created_at": 1, "id": "message-1"},
                "oversized_message": None, "server_message_count": 3}

    async def sidecars(*args, **kwargs):
        return [], {}

    async def checkpoint(*args, **kwargs):
        return None

    monkeypatch.setattr(handler, "load_bounded_sync_message_window", message_window)
    monkeypatch.setattr(handler, "load_sync_sidecars_for_chats", sidecars)
    monkeypatch.setattr(handler, "get_latest_chat_compression_checkpoint", checkpoint)
    manager = _WindowManager()
    await handler.handle_chat_content_batch(
        cache_service=cache or _WindowCache(), directus_service=directus, encryption_service=None,
        manager=manager, user_id="owner", device_fingerprint_hash="device",
        payload={"chat_ids": [CHAT_ID]},
    )
    assert len(manager.sent) == 1
    return manager.sent[0]


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("state", ["absent", "deleting"])
async def test_stale_cached_chat_is_skipped_before_content_reads(monkeypatch, state):
    directus = _WindowDirectus({})
    original = directus.get_items

    async def current_rows(*args, **kwargs):
        rows = await original(*args, **kwargs)
        return [] if state == "absent" else [{**rows[0], "storage_state": "deleting"}]

    directus.get_items = current_rows
    cache = _WindowCache()
    response = await _run_window_request(monkeypatch, directus, cache)
    assert response["messages_by_chat_id"] == {CHAT_ID: []}
    assert response["versions_by_chat_id"] == {}
    assert not response.get("partial_error")
    assert directus.embed_reads == []
    assert cache.removed == [("owner", CHAT_ID)]


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_transient_ownership_failure_preserves_cached_chat(monkeypatch):
    directus = _WindowDirectus({})

    async def unavailable(*args, **kwargs):
        raise RuntimeError("CMS under pressure")

    directus.get_items = unavailable
    cache = _WindowCache()
    response = await _run_window_request(monkeypatch, directus, cache)
    assert response["messages_by_chat_id"] == {CHAT_ID: []}
    assert response["partial_error"] is True
    assert directus.embed_reads == []
    assert cache.removed == []


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("authority", ["viewer", "removed", "suspended", "unavailable"])
async def test_team_batch_requires_current_membership_and_active_team(monkeypatch, authority):
    directus = _WindowDirectus({"embeds": [], "has_more_before": False, "start_cursor": None,
                                "oversized_embed_id": None})
    original = directus.get_items
    team_hash = hashlib.sha256(b"team").hexdigest()

    async def current_rows(collection, params, **kwargs):
        assert kwargs["raise_on_error"] and params["limit"] == 1
        if collection == "chats":
            rows = await original(collection, params, **kwargs)
            # Team authority takes precedence even on legacy dual-owner rows.
            return [{**rows[0], "hashed_team_id": team_hash}]
        if authority == "unavailable":
            raise RuntimeError("CMS under pressure")
        if collection == "teams":
            return [{"hashed_team_id": team_hash, "status": "active"}] if authority != "suspended" else []
        assert collection == "team_memberships"
        return [{"hashed_team_id": team_hash, "hashed_user_id": hashlib.sha256(b"owner").hexdigest(),
                 "status": "active", "role": "viewer"}] if authority != "removed" else []

    directus.get_items = current_rows
    cache = _WindowCache()
    response = await _run_window_request(monkeypatch, directus, cache)
    if authority == "viewer":
        assert response["messages_by_chat_id"][CHAT_ID] == ["encrypted-message"]
        assert response["versions_by_chat_id"][CHAT_ID]["server_message_count"] == 3
        assert response["chat_key_wrappers"] == [{"key_type": "team", "encrypted_chat_key": "cipher"}]
        assert not response.get("partial_error")
        assert cache.removed == []
    else:
        assert response["messages_by_chat_id"][CHAT_ID] == []
        assert response["versions_by_chat_id"] == {}
        assert directus.embed_reads == []
        assert cache.removed == ([] if authority == "unavailable" else [("owner", CHAT_ID)])
        assert bool(response.get("partial_error")) == (authority == "unavailable")


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_on_demand_embed_window_preserves_parent_child_and_cursors(monkeypatch) -> None:
    directus = _WindowDirectus({
        "embeds": [
            {"embed_id": "parent-1", "status": "finished", "embed_ids": ["child-1"],
             "encrypted_content": "final-parent"},
            {"embed_id": "child-1", "status": "finished", "parent_embed_id": "parent-1",
             "encrypted_content": "transcript-child"},
        ],
        "has_more_before": True, "start_cursor": {"created_at": 2, "id": "parent-1"},
        "oversized_embed_id": None,
    })
    response = await _run_window_request(monkeypatch, directus)
    assert directus.embed_reads == [hashlib.sha256(CHAT_ID.encode()).hexdigest()]
    assert [embed["embed_id"] for embed in response["embeds"]] == ["parent-1", "child-1"]
    assert response["embeds"][0]["encrypted_content"] == "final-parent"
    assert response["embeds"][1]["parent_embed_id"] == "parent-1"
    assert response["embed_windows_by_chat_id"][CHAT_ID] == {
        "has_more_before": True, "start_cursor": {"created_at": 2, "id": "parent-1"},
        "oversized_embed_id": None, "oversized_embed_cursor": None,
    }
    assert response["embed_key_windows_by_chat_id"][CHAT_ID]["embed_ids"] == ["parent-1", "child-1"]
    assert [key["id"] for key in response["embed_keys"]] == ["key-1"]
    assert response["message_windows_by_chat_id"][CHAT_ID]["has_more_before"] is True
    assert response["versions_by_chat_id"][CHAT_ID] == {"messages_v": 3, "server_message_count": 3}
    assert "partial_error" not in response


# contract-test: supporting surface=gui.apple assertions=videos.transcript.surface-parity
@pytest.mark.anyio
async def test_failed_authoritative_embed_window_reports_partial_error(monkeypatch) -> None:
    directus = _WindowDirectus(RuntimeError("Directus unavailable"))
    response = await _run_window_request(monkeypatch, directus)
    assert directus.embed_reads == [hashlib.sha256(CHAT_ID.encode()).hexdigest()]
    assert response["embeds"] == []
    assert response["embed_keys"] == []
    assert response["partial_error"] is True
    assert response["message_windows_by_chat_id"][CHAT_ID]["has_more_before"] is True
    assert CHAT_ID not in response["embed_windows_by_chat_id"]


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
