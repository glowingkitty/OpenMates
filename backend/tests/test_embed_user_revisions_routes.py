"""Route tests for user-made embed versions and pending chat notices.

Specification: feature.embed-user-edits. The Directus extension is replaced by
a fake transport that records the forwarded transaction body and returns the
extension's result shapes; the extension itself is covered by
backend/core/directus/extensions/embed-version-transaction/test/user-revisions.test.js.
Route functions are called directly (rate limiting is skipped for non-HTTP
requests); auth and request validation run through a FastAPI test client.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.core.api.app.routes import embed_user_revisions as routes
from backend.core.api.app.services import pending_embed_notices
from backend.core.api.app.services.directus.team_methods import TeamPermissionError

USER_ID = "user-owner"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
EMBED_ID = "0b6f0f0e-7c1a-4d2b-9a3e-1f2e3d4c5b6a"
CHAT_ID = "chat-a"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeTeam:
    def __init__(self, allowed: bool):
        self.allowed = allowed

    async def require_team_role(self, team_id, user_id, roles):
        if not self.allowed:
            raise TeamPermissionError("not a member")
        return {"role": "member"}


class FakeChat:
    def __init__(self, metadata):
        self.metadata = metadata

    async def get_chat_metadata(self, chat_id, admin_required=False):
        return self.metadata if chat_id == CHAT_ID else None


class FakeDirectus:
    base_url = "http://directus"

    def __init__(self, *, status=200, payload=None, metadata=None, team_allowed=True, notices=None,
                 upload_rows=None):
        self.status, self.payload = status, payload
        self.sent: list[dict[str, Any]] = []
        self.updates: list[tuple] = []
        self.deleted: list[tuple] = []
        self.chat = FakeChat(metadata)
        self.team = FakeTeam(team_allowed)
        self.notices = notices or []
        self.upload_rows = upload_rows if upload_rows is not None else [{"id": "upload-row"}]

    async def _make_api_request(self, method, url, headers=None, json=None):
        assert url == "http://directus/embed-version-transaction/user-revision"
        assert headers == {"X-Internal-Service-Token": "internal-token"}
        self.sent.append(json)
        return FakeResponse(self.status, self.payload)

    async def get_items(self, collection, params=None, **kwargs):
        if collection == "pending_embed_notices":
            assert params["filter[hashed_chat_id][_eq]"] == hashlib.sha256(CHAT_ID.encode()).hexdigest()
            return self.notices
        assert collection == "upload_files" and params["filter[user_id][_eq]"] == USER_ID
        return self.upload_rows

    async def update_item(self, collection, item_id, data, admin_required=False):
        self.updates.append((collection, item_id, data))
        return {"id": item_id}

    async def delete_items(self, collection, filter_dict, admin_required=False):
        self.deleted.append((collection, filter_dict))
        return 1


class FakeRedis:
    def __init__(self):
        self.deleted = []

    async def delete(self, key):
        self.deleted.append(key)


class FakeCache:
    def __init__(self):
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis


def _request(cache: FakeCache):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=cache)))


def _body(**overrides) -> routes.UserRevisionRequest:
    data = {
        "operation_id": "user-edit-1",
        "scope": {"kind": "chat", "chat_id": CHAT_ID},
        "action": "edit",
        "expected_revision": 1,
        "expected_content_hash": "1" * 64,
        "head": {"encrypted_content": "cipher-v2", "status": "finished", "updated_at": 20},
        "history_rows": [{"version_number": 2, "encrypted_snapshot": "snapshot-v2", "created_at": 20}],
        **overrides,
    }
    return routes.UserRevisionRequest.model_validate(data)


def _committed(**extra):
    return {"data": {"status": "committed", "operation_id": "user-edit-1", "embed_id": EMBED_ID,
                     "current_revision": 2, "current_content_hash": "2" * 64, "revision_origin": "user",
                     "revision_action": "edit", "idempotent": False, "pending_notice": True, "image": None,
                     **extra}}


@pytest.fixture(autouse=True)
def _internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    broadcasts = []

    async def broadcast(user_id, result):
        broadcasts.append((user_id, result["current_revision"]))

    monkeypatch.setattr(routes, "_broadcast_committed", broadcast)
    return broadcasts


async def _commit(directus, body, cache=None):
    return await routes.commit_user_embed_revision(
        request=_request(cache or FakeCache()), body=body, embed_id=EMBED_ID,
        current_user=SimpleNamespace(id=USER_ID), directus_service=directus,
    )


# contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
def test_routes_require_a_session_and_validate_the_body():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    def unauthenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[routes.get_current_user] = unauthenticated
    assert client.post(f"/v1/embeds/{EMBED_ID}/user-revisions", json={}).status_code == 401
    assert client.get(f"/v1/chats/{CHAT_ID}/pending-embed-notices").status_code == 401
    app.dependency_overrides[routes.get_current_user] = lambda: SimpleNamespace(id=USER_ID)
    app.dependency_overrides[routes.get_directus_service] = lambda: FakeDirectus()
    valid = _body().model_dump(exclude_unset=True)
    for invalid in (
        {**valid, "unexpected": True},
        {**valid, "action": "paint"},
        {**valid, "expected_content_hash": "nothex"},
        {**valid, "scope": {"kind": "chat", "chat_id": CHAT_ID, "project_id": "p"}},
        {**valid, "head": {**valid["head"], "status": "processing"}},
    ):
        assert client.post(f"/v1/embeds/{EMBED_ID}/user-revisions", json=invalid).status_code == 422


# contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version,embed-user-edits.history.one-per-embed
@pytest.mark.asyncio
async def test_commit_forwards_the_exact_transaction_and_announces_the_new_head(_internal_token):
    directus, cache = FakeDirectus(payload=_committed()), FakeCache()
    result = await _commit(directus, _body(), cache)
    assert result["status"] == "committed" and result["current_revision"] == 2
    assert result["revision_origin"] == "user" and result["pending_notice"] is True
    assert result["media_index_repointed"] is False
    sent = directus.sent[0]
    assert sent["embed_id"] == EMBED_ID and sent["actor_user_hash"] == USER_HASH
    assert sent["scope"] == {"kind": "chat", "chat_id": CHAT_ID}
    assert "media_index" not in sent and "files" not in sent and "restored_from" not in sent
    assert cache.redis.deleted == [f"embed:{EMBED_ID}"]
    assert _internal_token == [(USER_ID, 2)]


# contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
@pytest.mark.asyncio
async def test_stale_version_and_refusals_map_to_stable_errors(_internal_token):
    conflict = FakeDirectus(payload={"data": {"status": "conflict", "operation_id": "user-edit-1",
                                              "embed_id": EMBED_ID, "current_revision": 3,
                                              "current_content_hash": "3" * 64}})
    with pytest.raises(HTTPException) as stale:
        await _commit(conflict, _body())
    assert stale.value.status_code == 409
    assert stale.value.detail == {"code": "embed_version_conflict", "current_revision": 3,
                                  "current_content_hash": "3" * 64}
    for status, code, expected in (
        (403, "chat_access_denied", 403), (403, "project_context_required", 403),
        (409, "operation_payload_mismatch", 409), (400, "unsupported_file_source", 400),
        (409, "enhance_scope_mismatch", 409),
        (403, "unlisted_code", 500), (500, "user_revision_failed", 500),
    ):
        with pytest.raises(HTTPException) as refused:
            await _commit(FakeDirectus(status=status, payload={"error": {"code": code}}), _body())
        assert refused.value.status_code == expected
        assert refused.value.detail == (code if expected < 500 else "user_revision_failed")
    assert _internal_token == []


MEDIA_INDEX = {"files": {"full": {"s3_key": "u/v1.webp", "format": "webp"}}, "aes_nonce": "bm9uY2U=",
               "vault_wrapped_aes_key": "vault:v1:wrapped", "content_type": "image/webp"}
RESTORE = {"action": "restore", "restored_from": 1, "expected_revision": 2,
           "history_rows": [{"version_number": 3, "encrypted_snapshot": "snapshot-v3", "created_at": 30}],
           "files": {"head_file_keys": [{"bucket": "chatfiles", "key": "u/v1.webp"}]}}


# contract-test: direct surface=rest_api assertions=embed-user-edits.restore.creates-version,embed-user-edits.files.client-made-version
@pytest.mark.asyncio
async def test_image_restore_repoints_the_owner_media_index():
    image = {"head_file_keys": [{"bucket": "chatfiles", "key": "u/v1.webp"}], "owner_is_actor": True}
    directus = FakeDirectus(payload=_committed(current_revision=3, revision_action="restore", image=image))
    result = await _commit(directus, _body(**RESTORE, media_index=MEDIA_INDEX))
    assert result["media_index_repointed"] is True
    collection, row_id, update = directus.updates[0]
    assert (collection, row_id) == ("upload_files", "upload-row")
    assert update["files_metadata"] == MEDIA_INDEX["files"] and update["aes_key"] is None
    assert isinstance(update["created_at"], int)
    assert "media_index" not in directus.sent[0]


# contract-test: direct surface=rest_api assertions=embed-user-edits.restore.creates-version,embed-user-edits.files.client-made-version
@pytest.mark.asyncio
async def test_image_restore_accepts_the_empty_index_nonce_of_current_media():
    image = {"head_file_keys": [{"bucket": "chatfiles", "key": "u/v1.webp"}], "owner_is_actor": True}
    directus = FakeDirectus(payload=_committed(current_revision=3, revision_action="restore", image=image))
    result = await _commit(directus, _body(**RESTORE, media_index={**MEDIA_INDEX, "aes_nonce": ""}))
    assert result["media_index_repointed"] is True
    assert directus.updates[0][2]["aes_nonce"] == ""

    not_owner = FakeDirectus(payload=_committed(image={**image, "owner_is_actor": False}))
    result = await _commit(not_owner, _body(**RESTORE, media_index=MEDIA_INDEX))
    assert (result["media_index_repointed"], result["media_index_reason"]) == (False, "not_owner")
    assert not_owner.updates == []

    # The committed head names the same key in another bucket: the index row is not repointed.
    other_bucket = FakeDirectus(payload=_committed(image={**image, "head_file_keys": [
        {"bucket": "otherfiles", "key": "u/v1.webp"}]}))
    result = await _commit(other_bucket, _body(**RESTORE, media_index=MEDIA_INDEX))
    assert (result["media_index_repointed"], result["media_index_reason"]) == (False, "media_index_mismatch")
    assert other_bucket.updates == []


# contract-test: direct surface=rest_api assertions=embed-user-edits.files.client-made-version
@pytest.mark.asyncio
async def test_file_commits_need_a_matching_media_index_before_any_write():
    for overrides, code in (
        ({**RESTORE}, "media_index_required"),
        ({**RESTORE, "media_index": {**MEDIA_INDEX, "files": {"full": {"s3_key": "other.webp"}}}}, "media_index_mismatch"),
        ({"media_index": MEDIA_INDEX}, "invalid_media_index"),
        # Same key in another bucket is a different object.
        ({**RESTORE, "files": {"head_file_keys": [{"bucket": "otherfiles", "key": "u/v1.webp"}]},
          "media_index": MEDIA_INDEX}, "media_index_mismatch"),
        ({**RESTORE, "media_index": {**MEDIA_INDEX, "files": {"full": {"s3_key": "u/v1.webp", "bucket": "otherfiles"}}}},
         "media_index_mismatch"),
    ):
        directus = FakeDirectus(payload=_committed())
        with pytest.raises(HTTPException) as refused:
            await _commit(directus, _body(**overrides))
        assert (refused.value.status_code, refused.value.detail) == (400, code)
        assert directus.sent == []


NOTICE_ROW = {"embed_id": EMBED_ID, "version": 2, "action": "edit", "surface": "chat", "restored_from": None, "created_at": 20}
RESTORE_ROW = {"embed_id": EMBED_ID, "version": 3, "action": "restore", "surface": "project", "restored_from": 1, "created_at": 30}


# contract-test: direct surface=rest_api assertions=embed-user-edits.event.project-edit-reaches-chat
@pytest.mark.asyncio
async def test_pending_notices_are_listed_for_the_chat_owner_or_team_writers_only():
    owner_chat = {"hashed_user_id": USER_HASH, "hashed_team_id": None}
    directus = FakeDirectus(metadata=owner_chat, notices=[NOTICE_ROW])
    page = await routes.get_pending_embed_notices(
        request=SimpleNamespace(), chat_id=CHAT_ID, team_id=None,
        current_user=SimpleNamespace(id=USER_ID), directus_service=directus,
    )
    expected = {k: v for k, v in NOTICE_ROW.items() if k != "restored_from"}
    assert page["notices"] == [{**expected, "message_id": f"embed-updated-{EMBED_ID}-v2"}]
    with pytest.raises(HTTPException) as foreign:
        await routes.get_pending_embed_notices(
            request=SimpleNamespace(), chat_id=CHAT_ID, team_id=None,
            current_user=SimpleNamespace(id="someone-else"), directus_service=directus,
        )
    assert foreign.value.status_code == 404
    team_chat = {"hashed_user_id": None, "hashed_team_id": hashlib.sha256(b"team-a").hexdigest()}
    with pytest.raises(HTTPException) as non_member:
        await routes.get_pending_embed_notices(
            request=SimpleNamespace(), chat_id=CHAT_ID, team_id="team-a",
            current_user=SimpleNamespace(id="outsider"),
            directus_service=FakeDirectus(metadata=team_chat, team_allowed=False),
        )
    assert (non_member.value.status_code, non_member.value.detail) == (403, "forbidden")
    member_page = await routes.get_pending_embed_notices(
        request=SimpleNamespace(), chat_id=CHAT_ID, team_id="team-a",
        current_user=SimpleNamespace(id="member"),
        directus_service=FakeDirectus(metadata=team_chat, notices=[NOTICE_ROW]),
    )
    assert len(member_page["notices"]) == 1


# contract-test: direct surface=rest_api assertions=embed-user-edits.event.project-edit-reaches-chat
@pytest.mark.asyncio
async def test_pending_notices_carry_surface_and_restored_from_for_restores_only():
    directus = FakeDirectus(metadata={"hashed_user_id": USER_HASH, "hashed_team_id": None},
                            notices=[NOTICE_ROW, RESTORE_ROW])
    page = await routes.get_pending_embed_notices(
        request=SimpleNamespace(), chat_id=CHAT_ID, team_id=None,
        current_user=SimpleNamespace(id=USER_ID), directus_service=directus,
    )
    edit, restore = page["notices"]
    assert edit["surface"] == "chat" and "restored_from" not in edit
    assert (restore["surface"], restore["restored_from"]) == ("project", 1)
    broken = {**RESTORE_ROW, "restored_from": None}
    with pytest.raises(RuntimeError):
        await pending_embed_notices.list_pending_embed_notices(
            FakeDirectus(notices=[broken]), chat_id=CHAT_ID)


# contract-test: direct surface=rest_api assertions=embed-user-edits.event.project-edit-reaches-chat
@pytest.mark.asyncio
async def test_storing_the_event_message_clears_exactly_its_notice():
    directus = FakeDirectus()
    assert pending_embed_notices.parse_embed_updated_message_id(f"embed-updated-{EMBED_ID}-v12") == (EMBED_ID, 12)
    assert pending_embed_notices.parse_embed_updated_message_id("embed-updated-x-v0") is None
    assert await pending_embed_notices.clear_pending_embed_notice(
        directus, chat_id=CHAT_ID, message_id="ffffffff-voice-call-ended") == 0
    assert directus.deleted == []
    assert await pending_embed_notices.clear_pending_embed_notice(
        directus, chat_id=CHAT_ID, message_id=f"embed-updated-{EMBED_ID}-v2") == 1
    assert directus.deleted == [("pending_embed_notices", {
        "hashed_chat_id": {"_eq": hashlib.sha256(CHAT_ID.encode()).hexdigest()},
        "embed_id": {"_eq": EMBED_ID}, "version": {"_eq": 2},
    })]
