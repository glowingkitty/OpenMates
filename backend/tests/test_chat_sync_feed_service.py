"""Chat sync feed API: hydration, scoping, capability gating and hints (architecture.sync@2).

Pure tests over ChatSyncFeedService/hydrate_page with in-memory fakes for the
internal chat-sync extension; the extension and triggers are exercised against
a disposable database in test_chat_sync_feed_db.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes import chat_sync_feed as routes
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.handlers.websocket_handlers.chat_sync_cold_start import begin_cold_start
from backend.core.api.app.services import chat_sync_feed_service as svc
from backend.core.api.app.services.limiter import limiter

USER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
TEAM = str(uuid.uuid4())


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def chat_row(chat_id: str, **extra):
    row = {"id": chat_id, "hashed_user_id": h(USER), "hashed_team_id": None, "encrypted_title": "cipher-title",
           "encrypted_chat_key": "wrapped-key", "messages_v": 4, "title_v": 2, "metadata_v": 3, "pinned": False,
           "last_edited_overall_timestamp": 50, "updated_at": 49}
    row.update(extra)
    return row


class FakeSocket:
    def __init__(self, capable: bool = True):
        caps = "chat_metadata_recovery,chat_sync_feed_v1" if capable else "chat_metadata_recovery"
        self.query_params = {"client_capabilities": caps}
        self.sent: list[dict] = []

    async def send_json(self, message):
        self.sent.append(message)


def service(raw_pages=None, team_error=None):
    calls = []
    pages = list(raw_pages or [])

    async def call(path, body):
        calls.append((path, body))
        if path == "clock":
            return {"cursor": "e1:7|e2:3"}
        if path == "overview":
            return {"chat": None, "saved_items": []}
        return pages.pop(0)

    team = SimpleNamespace(require_team_role=AsyncMock(side_effect=team_error))
    reminder = SimpleNamespace(get_user_reminders=AsyncMock(return_value=[]))
    feed = svc.ChatSyncFeedService(SimpleNamespace(team=team, reminder=reminder), SimpleNamespace(), SimpleNamespace())
    feed._call = call  # replaces the internal Directus hop
    return feed, calls


# contract-test: direct surface=rest_api assertions=sync.delta.metadata-only
def test_page_carries_encrypted_metadata_and_scoped_wrappers_only():
    chat = str(uuid.uuid4())
    raw = {"reset": False, "has_more": False, "next_cursor": "e1:9|e2:3",
           "changes": [{"lane": "scope", "chat_id": chat, "hashed_chat_id": h(chat), "kinds": ["metadata", "messages"]}],
           "chats": [chat_row(chat)], "drafts": [], "existing_chat_ids": [],
           "wrappers": [{"id": "w1", "hashed_chat_id": h(chat), "encrypted_chat_key": "wrap", "window_position": 1}]}
    page = svc.hydrate_page(raw, USER, None)
    [entry] = page["changes"]
    assert entry["chat_id"] == chat and entry["kinds"] == ["messages", "metadata"]
    assert entry["versions"]["messages_v"] == 4 and entry["versions"]["metadata_v"] == 3
    assert entry["chat_details"]["encrypted_title"] == "cipher-title"
    assert entry["chat_key_wrappers"] == [{"id": "w1", "hashed_chat_id": h(chat), "encrypted_chat_key": "wrap"}]
    serialized = json.dumps(page)
    for forbidden in ("\"messages\":", "embeds", "embed_keys", "code_run_outputs", "compression_checkpoints"):
        assert forbidden not in serialized


# contract-test: direct surface=rest_api assertions=sync.delta.scope-revocation,sync.deletion.partial-window-not-authoritative
def test_removals_are_hash_only_and_revoked_direct_chats_hide_their_id():
    deleted, moved, direct = (str(uuid.uuid4()) for _ in range(3))
    envelopes = {h(OTHER): {"encrypted_chat_key": "peer-key"}}
    raw = {"reset": False, "has_more": False, "next_cursor": "c",
           "changes": [
               {"lane": "scope", "chat_id": deleted, "hashed_chat_id": h(deleted), "kinds": ["deleted"]},
               {"lane": "scope", "chat_id": moved, "hashed_chat_id": h(moved), "kinds": ["moved"]},
               {"lane": "scope", "chat_id": direct, "hashed_chat_id": h(direct), "kinds": ["metadata"]},
               {"lane": "scope", "chat_id": str(uuid.uuid4()), "hashed_chat_id": "x", "kinds": ["metadata"]},
           ],
           "chats": [chat_row(direct, hashed_team_id=h(TEAM), chat_visibility="direct",
                              participant_user_hashes=[h(OTHER)], participant_key_envelopes=envelopes)],
           "drafts": [], "wrappers": [], "existing_chat_ids": []}
    page = svc.hydrate_page(raw, USER, TEAM)
    assert page["changes"] == [
        {"hashed_chat_id": h(deleted), "kinds": ["deleted"]},
        {"hashed_chat_id": h(moved), "kinds": ["moved"]},
        {"hashed_chat_id": h(direct), "kinds": ["revoked"]},
    ]
    assert "peer-key" not in json.dumps(page)


# contract-test: direct surface=rest_api assertions=sync.phase2.drafts.authoritative-encrypted
def test_draft_lane_respects_context_and_emits_explicit_deletions():
    visible, draft_only, team_chat = (str(uuid.uuid4()) for _ in range(3))
    changes = [{"lane": "user", "chat_id": cid, "hashed_chat_id": h(cid), "kinds": ["draft"]}
               for cid in (visible, draft_only, team_chat)]
    raw = {"reset": False, "has_more": False, "next_cursor": "c", "changes": changes, "wrappers": [],
           "chats": [chat_row(visible)], "existing_chat_ids": [team_chat],
           "drafts": [{"chat_id": draft_only, "encrypted_content": "cipher-draft", "version": 5}]}
    page = svc.hydrate_page(raw, USER, None)
    by_id = {entry["chat_id"]: entry for entry in page["changes"]}
    assert by_id[visible]["draft"] == {"draft_v": 0, "encrypted_draft_md": None, "encrypted_draft_preview": None}
    assert by_id[draft_only]["draft"]["encrypted_draft_md"] == "cipher-draft"
    assert team_chat not in by_id
    team_page = svc.hydrate_page({**raw, "chats": [], "existing_chat_ids": []}, USER, TEAM)
    assert team_page["changes"] == []  # no draft-only discovery in a Team context


# contract-test: direct surface=rest_api assertions=sync.overview.cross-device,sync.overview.priority-order
def test_last_opened_is_synchronized_with_ordering_fields():
    opened = str(uuid.uuid4())
    raw = {"reset": False, "has_more": False, "next_cursor": "c", "changes": [], "wrappers": [], "drafts": [],
           "chats": [chat_row(opened, pinned=True)], "existing_chat_ids": [], "last_opened": {"chat_id": opened}}
    page = svc.hydrate_page(raw, USER, None)
    assert page["overview"] == {"last_opened_chat_id": opened}
    [entry] = page["changes"]
    assert entry["kinds"] == ["last_opened"]
    details = entry["chat_details"]
    # Every input of the deterministic overview comparator is present.
    for field in ("pinned", "draft_v", "last_edited_overall_timestamp", "updated_at", "id"):
        assert field in details
    outside = svc.hydrate_page({**raw, "chats": []}, USER, None)
    assert outside["overview"] == {"last_opened_chat_id": None} and outside["changes"] == []


# contract-test: direct surface=rest_api assertions=sync.delta.reset
def test_reset_and_null_cursor_never_carry_changes():
    feed, calls = service()
    page = asyncio.run(feed.read_page(USER, None, None, 50))
    assert page == {"reset": True, "has_more": False, "next_cursor": None, "changes": [], "overview": None}
    assert calls == []
    assert svc.hydrate_page({"reset": True, "changes": [{"chat_id": "x"}]}, USER, None)["changes"] == []


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_request_validation_bounds():
    assert svc.validate_request({"limit": 200}) == (None, None, 200)
    for bad in ({"limit": 0}, {"limit": 201}, {"limit": True}, {"cursor": "x" * 161}, {"team_id": ""}, {"team_id": 3}):
        with pytest.raises(svc.ChatSyncFeedError):
            svc.validate_request({"limit": 10, **bad})


# contract-test: direct surface=rest_api assertions=sync.access.first-party-authenticated,sync.delta.scope-revocation
def test_ws_requires_capability_and_team_membership():
    feed, calls = service()
    plain = FakeSocket(capable=False)
    asyncio.run(feed.handle_ws_request(plain, USER, {"cursor": "a|b"}))
    assert plain.sent == [{"type": "chat_sync_delta_error", "payload": {"code": "capability_required", "team_id": None, "context_epoch": None}}]
    assert calls == []

    class TeamPermissionError(Exception):
        pass

    feed, calls = service(team_error=TeamPermissionError("gone"))
    capable = FakeSocket()
    feed.register(capable, USER, TEAM)
    asyncio.run(feed.handle_ws_request(capable, USER, {"team_id": TEAM, "cursor": "a|b", "context_epoch": 4}))
    assert capable.sent[-1]["payload"]["code"] == "team_access_revoked"
    assert calls == [] and capable not in feed.contexts  # Team hints stop; personal scope untouched


# contract-test: supporting surface=rest_api assertions=sync.delta.cursor-gap-free,sync.delta.live-hint
def test_ws_page_registers_socket_and_echoes_context():
    chat = str(uuid.uuid4())
    raw = {"reset": False, "has_more": True, "next_cursor": "n", "wrappers": [], "drafts": [], "existing_chat_ids": [],
           "changes": [{"lane": "scope", "chat_id": chat, "hashed_chat_id": h(chat), "kinds": ["metadata"]}],
           "chats": [chat_row(chat)]}
    feed, calls = service([raw])
    sock = FakeSocket()
    asyncio.run(feed.handle_ws_request(sock, USER, {"cursor": "a|b", "limit": 10, "context_epoch": 2}))
    message = sock.sent[-1]
    assert message["type"] == "chat_sync_delta" and message["payload"]["context_epoch"] == 2
    assert message["payload"]["has_more"] is True and message["payload"]["next_cursor"] == "n"
    assert calls[0] == ("changes", {"scope": f"personal:{h(USER)}", "user_scope": f"user:{h(USER)}", "cursor": "a|b", "limit": 10})
    assert sock in feed.scope_sockets[f"personal:{h(USER)}"]


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_ws_rate_limit():
    feed, _ = service()
    sock = FakeSocket()
    assert all(feed.allow_request(sock) for _ in range(svc.WS_REQUEST_LIMIT))
    assert feed.allow_request(sock) is False


# contract-test: direct surface=rest_api assertions=sync.delta.live-hint
def test_hints_reach_only_capable_sockets_of_that_scope_and_coalesce():
    async def scenario():
        feed, _ = service()
        personal, team_sock, other, plain = FakeSocket(), FakeSocket(), FakeSocket(), FakeSocket(capable=False)
        feed.register(personal, USER, None)
        feed.register(team_sock, USER, TEAM)
        feed.register(other, OTHER, None)
        feed.register(plain, USER, None)
        feed.notify(f"personal:{h(USER)}", 5)
        feed.notify(f"personal:{h(USER)}", 6)
        feed.notify(f"user:{h(USER)}", 2)
        await asyncio.sleep(svc.HINT_DELAY_SECONDS * 3)
        return personal, team_sock, other, plain

    personal, team_sock, other, plain = asyncio.run(scenario())
    assert personal.sent == [{"type": "chat_sync_hint", "payload": {"team_id": None, "revision": 6}}]
    assert team_sock.sent == [{"type": "chat_sync_hint", "payload": {"team_id": TEAM, "revision": 2}}]
    assert other.sent == [] and plain.sent == []


# contract-test: direct surface=rest_api assertions=sync.startup.bounded-phases
def test_cold_start_is_inert_without_capability_and_reads_clock_first_with_it():
    async def scenario(capable):
        feed, calls = service()
        sock = FakeSocket(capable=capable)
        sock.app = SimpleNamespace(state=SimpleNamespace(chat_sync_feed=feed))
        manager = SimpleNamespace(send_personal_message=AsyncMock())
        cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"last_opened": "/chat/new"}))
        handle = await begin_cold_start(sock, manager, cache, SimpleNamespace(), USER, "dev", None, 3, "all")
        first_call = calls[0][0] if calls else None
        await handle.finish()
        return handle, calls, first_call, manager, feed, sock

    handle, calls, _, manager, feed, sock = asyncio.run(scenario(False))
    assert handle.completion_fields() == {} and calls == [] and manager.send_personal_message.await_count == 0
    handle, calls, first, manager, feed, sock = asyncio.run(scenario(True))
    assert first == "clock" and handle.completion_fields() == {"sync_cursor": "e1:7|e2:3"}
    sent = manager.send_personal_message.await_args.args[0]
    assert sent["type"] == "chat_overview_priority_ready" and sent["payload"]["context_epoch"] == 3
    assert sent["payload"]["due_soon"]["reminders"] == [] and sock in feed.contexts


# contract-test: supporting surface=rest_api assertions=sync.overview.cross-device
def test_last_opened_parsing():
    chat = str(uuid.uuid4())
    assert svc.parse_last_opened(f"/chat/{chat.upper()}") == chat
    for value in ("/chat/new", "/signup/one_time_codes", None, "demo-for-everyone"):
        assert svc.parse_last_opened(value) is None


def _client(feed):
    app = FastAPI()
    app.state.limiter = limiter
    app.state.chat_sync_feed = feed
    app.include_router(routes.router)
    app.include_router(routes.internal_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER)
    return TestClient(app)


# contract-test: direct surface=rest_api assertions=sync.access.first-party-authenticated
def test_rest_route_is_session_only_and_maps_team_revocation_to_403():
    paths = {route.path: route for route in routes.router.routes}
    assert get_current_user in [dep.call for dep in paths["/v1/chats/changes"].dependant.dependencies]

    class TeamPermissionError(Exception):
        pass

    feed, _ = service(team_error=TeamPermissionError("gone"))
    response = _client(feed).get("/v1/chats/changes", params={"team_id": TEAM, "cursor": "a|b"})
    assert response.status_code == 403 and response.json()["detail"] == "team_access_revoked"
    feed, _ = service()
    response = _client(feed).get("/v1/chats/changes")
    assert response.status_code == 200 and response.json()["reset"] is True
    assert _client(feed).get("/v1/chats/changes", params={"limit": 500}).status_code == 422


# contract-test: supporting surface=rest_api assertions=sync.delta.live-hint
def test_internal_hint_endpoint_requires_service_token(monkeypatch):
    from backend.core.api.app.utils import internal_auth
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "secret-token")
    feed, _ = service()
    feed.cache = SimpleNamespace(publish_event=AsyncMock(return_value=True))
    client = _client(feed)
    body = {"hints": [{"scope": f"team:{h(TEAM)}", "revision": "9"}]}
    assert client.post("/internal/chat-sync/changed", json=body).status_code in (401, 403)
    ok = client.post("/internal/chat-sync/changed", json=body, headers={"X-Internal-Service-Token": "secret-token"})
    assert ok.status_code == 200
    feed.cache.publish_event.assert_awaited_once_with(f"chat_sync:team:{h(TEAM)}", {"revision": 9})
    bad = client.post("/internal/chat-sync/changed", json={"hints": [{"scope": "team:nope", "revision": "1"}]},
                      headers={"X-Internal-Service-Token": "secret-token"})
    assert bad.status_code == 400
