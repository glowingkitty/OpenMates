"""Route-level tests for embed version history endpoints.

These tests keep the REST contract deterministic without a live Directus or
Vault dependency. The fake services model append-only client-encrypted
`embed_diffs` rows and owner-gated parent embed access used by clients.
They intentionally exercise route functions directly so auth/rate-limit
middleware does not obscure the version-history behavior under test.
"""

import difflib
import hashlib
import json
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_exceptions_stub = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = redis_exceptions_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
auth_deps_stub.get_current_user_optional = lambda: None
sys.modules.setdefault("backend.core.api.app.routes.auth_routes.auth_dependencies", auth_deps_stub)

directus_module_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module_stub)

team_methods_stub = types.ModuleType("backend.core.api.app.services.directus.team_methods")
team_methods_stub.TeamPermissionError = type("TeamPermissionError", (PermissionError,), {})
sys.modules.setdefault("backend.core.api.app.services.directus.team_methods", team_methods_stub)

s3_service_stub = types.ModuleType("backend.core.api.app.services.s3.service")
s3_service_stub.S3UploadService = object
sys.modules.setdefault("backend.core.api.app.services.s3.service", s3_service_stub)

s3_config_stub = types.ModuleType("backend.core.api.app.services.s3.config")
s3_config_stub.get_bucket_name = lambda *args: "test-bucket"
sys.modules.setdefault("backend.core.api.app.services.s3.config", s3_config_stub)


class _FakeLimiter:
    def limit(self, rate: str):
        def decorator(func):
            return func

        return decorator


limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _FakeLimiter()
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)

from backend.core.api.app.routes import embeds_api  # noqa: E402  # Import after route dependency stubs.


OWNER_ID = "owner-user"
RECIPIENT_ID = "recipient-user"
OWNER_HASH = hashlib.sha256(OWNER_ID.encode()).hexdigest()


def _patch(before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="v1",
            tofile="v2",
            lineterm="",
        )
    )


class FakeEmbedMethods:
    def __init__(self, embed: dict):
        self.embed = embed
        self.updates = []

    async def get_embed_by_id(self, embed_id: str):
        if embed_id != self.embed["embed_id"]:
            return None
        return self.embed

    async def update_embed(self, embed_id: str, payload: dict):
        self.updates.append((embed_id, payload))
        self.embed.update(payload)
        return {"embed_id": embed_id, **payload}


class FakeDirectusService:
    def __init__(self):
        self.embed = FakeEmbedMethods(
            {
                "embed_id": "embed-1",
                "hashed_user_id": OWNER_HASH,
                "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(),
                "version_number": 2,
                "encrypted_type": "cipher-type",
                "encrypted_content": "cipher-head-v2",
                "encrypted_text_preview": "cipher-preview",
                "encrypted_diff": "cipher-diff-v2",
                "status": "finished",
                "encryption_mode": "client",
                "created_at": 1760000000,
                "updated_at": 1760000100,
                "file_path": "must-not-leak.md",
                "content_hash": "must-not-leak",
            }
        )
        self.project = SimpleNamespace(get_project=self._get_project)
        self.team = SimpleNamespace(require_team_role=self._require_team_role)
        self.chat = SimpleNamespace(
            get_chat_metadata=self._get_chat_metadata,
            check_chat_ownership=self._check_chat_ownership,
        )
        self.project_item_exists = True
        self.rows = [
            {
                "embed_id": "embed-1",
                "version_number": 1,
                "encrypted_snapshot": "first line\nsecond line",
                "encrypted_patch": None,
                "hashed_user_id": OWNER_HASH,
                "created_at": 1760000000,
            },
            {
                "embed_id": "embed-1",
                "version_number": 2,
                "encrypted_snapshot": None,
                "encrypted_patch": _patch("first line\nsecond line", "first line\nupdated line"),
                "hashed_user_id": OWNER_HASH,
                "created_at": 1760000100,
            },
        ]

    async def get_user_profile(self, user_id: str):
        return True, {"vault_key_id": f"vault-{user_id}"}, ""

    async def _get_project(self, project_id: str, user_id: str, team_id=None):
        if project_id == "project-1" and user_id in {OWNER_ID, RECIPIENT_ID}:
            return {"project_id": project_id}
        return None

    async def _require_team_role(self, team_id: str, user_id: str, roles: set[str]):
        if team_id == "team-1" and user_id in {OWNER_ID, RECIPIENT_ID}:
            return {"role": "member"}
        raise RuntimeError("denied")

    async def _get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        return {"hashed_team_id": hashlib.sha256(b"team-1").hexdigest()} if chat_id == "chat-1" else None

    async def _check_chat_ownership(self, chat_id: str, user_id: str):
        return chat_id == "chat-1" and user_id == OWNER_ID

    async def read_items(self, collection: str, params: dict):
        assert collection == "embed_diffs"
        filters = params.get("filter", {})
        embed_filter = filters.get("embed_id", {}).get("_eq")
        owner_filter = filters.get("hashed_user_id", {}).get("_eq")
        max_version = filters.get("version_number", {}).get("_lte")
        min_version = filters.get("version_number", {}).get("_gte")
        rows = [
            row
            for row in self.rows
            if row["embed_id"] == embed_filter and row["hashed_user_id"] == owner_filter
        ]
        if max_version is not None:
            rows = [row for row in rows if row["version_number"] <= max_version]
        if min_version is not None:
            rows = [row for row in rows if row["version_number"] >= min_version]
        fields = params.get("fields")
        if isinstance(fields, str):
            fields = fields.split(",")
        if fields:
            rows = [{key: row.get(key) for key in fields} for row in rows]
        descending = params.get("sort") == ["-version_number"]
        return sorted(rows, key=lambda row: row["version_number"], reverse=descending)[:params.get("limit", 100)]

    async def create_item(self, collection: str, payload: dict):
        assert collection == "embed_diffs"
        self.rows.append(payload)
        return payload

    async def get_items(self, collection: str, params: dict, **kwargs):
        if collection == "project_items":
            return [{"id": "item-1"}] if self.project_item_exists else []
        if collection == "embed_keys":
            return [{
                "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(),
                "key_type": "project",
                "hashed_project_id": hashlib.sha256(b"project-1").hexdigest(),
                "encrypted_embed_key": "project-wrapped-key",
                "created_at": 1760000000,
            }]
        if collection == "embed_diffs":
            return [{"id": "history-v1"}]
        if collection == "embed_version_commits":
            expected = {
                "filter[embed_id][_eq]": "embed-1",
                "filter[operation_id][_eq]": "operation-1",
                "filter[proposal_digest][_eq]": "b" * 64,
            }
            if all(params.get(key) == value for key, value in expected.items()):
                return [{"committed_revision": 2}]
            return []
        raise AssertionError(collection)


list_embed_versions = getattr(embeds_api.list_embed_versions, "__wrapped__", embeds_api.list_embed_versions)
get_embed_version = getattr(embeds_api.get_embed_version, "__wrapped__", embeds_api.get_embed_version)
get_chat_embed_window = getattr(embeds_api.get_chat_embed_window, "__wrapped__", embeds_api.get_chat_embed_window)
get_chat_embed_key_window = getattr(embeds_api.get_chat_embed_key_window, "__wrapped__", embeds_api.get_chat_embed_key_window)
get_chat_embed_by_id = getattr(embeds_api.get_chat_embed_by_id, "__wrapped__", embeds_api.get_chat_embed_by_id)
publish_embed_version_snapshot = getattr(
    embeds_api.publish_embed_version_snapshot,
    "__wrapped__",
    embeds_api.publish_embed_version_snapshot,
)
restore_embed_version = getattr(embeds_api.restore_embed_version, "__wrapped__", embeds_api.restore_embed_version)
get_encrypted_project_embed = getattr(
    embeds_api.get_encrypted_project_embed,
    "__wrapped__",
    embeds_api.get_encrypted_project_embed,
)
get_project_embed_revision_receipt = getattr(
    embeds_api.get_project_embed_revision_receipt,
    "__wrapped__",
    embeds_api.get_project_embed_revision_receipt,
)


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_team_member_reads_versions_only_with_live_project_item_context():
    directus = FakeDirectusService()
    user = SimpleNamespace(id=RECIPIENT_ID)
    with pytest.raises(HTTPException) as missing_context:
        await list_embed_versions(
            embed_id="embed-1", request=SimpleNamespace(),
            current_user=user, directus_service=directus,
        )
    assert missing_context.value.status_code == 404

    context = {"project_id": "project-1", "team_id": "team-1"}
    history = await list_embed_versions(
        embed_id="embed-1", request=SimpleNamespace(),
        current_user=user, directus_service=directus, **context,
    )
    assert [row["version_number"] for row in history["versions"]] == [1, 2]
    version = await get_embed_version(
        embed_id="embed-1", version_number=2, request=SimpleNamespace(),
        current_user=user, directus_service=directus, **context,
    )
    assert len(version["rows"]) == 2

    chat_history = await list_embed_versions(
        embed_id="embed-1", request=SimpleNamespace(),
        current_user=user, directus_service=directus,
        chat_id="chat-1", team_id="team-1",
    )
    assert [row["version_number"] for row in chat_history["versions"]] == [1, 2]
    with pytest.raises(HTTPException) as wrong_chat:
        await list_embed_versions(
            embed_id="embed-1", request=SimpleNamespace(),
            current_user=user, directus_service=directus,
            chat_id="chat-other", team_id="team-1",
        )
    assert wrong_chat.value.status_code == 404

    directus.project_item_exists = False
    with pytest.raises(HTTPException) as revoked:
        await list_embed_versions(
            embed_id="embed-1", request=SimpleNamespace(),
            current_user=user, directus_service=directus, **context,
        )
    assert revoked.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_owner_can_list_and_fetch_encrypted_embed_version_rows_without_decryption():
    directus = FakeDirectusService()
    user = SimpleNamespace(id=OWNER_ID)

    history = await list_embed_versions(
        embed_id="embed-1",
        request=SimpleNamespace(),
        current_user=user,
        directus_service=directus,
    )
    assert history["current_version"] == 2
    assert [row["version_number"] for row in history["versions"]] == [1, 2]
    assert history["versions"][0]["has_snapshot"] is True
    assert history["versions"][1]["has_patch"] is True
    assert all("encrypted_snapshot" not in row and "encrypted_patch" not in row for row in history["versions"])

    version = await get_embed_version(
        embed_id="embed-1",
        version_number=1,
        request=SimpleNamespace(),
        current_user=user,
        directus_service=directus,
    )
    assert version["rows"][0]["encrypted_snapshot"] == "first line\nsecond line"
    assert "content" not in version


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload,storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_thousand_version_index_pages_and_reads_from_nearest_snapshot():
    directus = FakeDirectusService()
    directus.rows = [
        {
            "embed_id": "embed-1", "hashed_user_id": OWNER_HASH,
            "version_number": number, "created_at": 1760000000 + number,
            "encrypted_snapshot": f"cipher-snapshot-{number}" if number == 1 or number % 32 == 0 else None,
            "encrypted_patch": f"cipher-patch-{number}" if number > 1 else None,
            "has_snapshot": number == 1 or number % 32 == 0,
            "has_patch": number > 1,
        }
        for number in range(1, 1001)
    ]
    directus.embed.embed["version_number"] = 1000
    user = SimpleNamespace(id=OWNER_ID)
    numbers = []
    cursor = 0
    while True:
        page = await list_embed_versions(
            embed_id="embed-1", request=SimpleNamespace(), current_user=user,
            directus_service=directus, cursor=cursor, limit=100,
        )
        numbers.extend(row["version_number"] for row in page["versions"])
        assert all("encrypted_patch" not in row for row in page["versions"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert numbers == list(range(1, 1001))

    newest = await list_embed_versions(
        embed_id="embed-1", request=SimpleNamespace(), current_user=user,
        directus_service=directus, cursor=0, limit=32, order="desc",
    )
    assert [row["version_number"] for row in newest["versions"]] == list(range(1000, 968, -1))
    assert newest["next_cursor"] == 969
    older = await list_embed_versions(
        embed_id="embed-1", request=SimpleNamespace(), current_user=user,
        directus_service=directus, cursor=969, limit=32, order="desc",
    )
    assert older["versions"][0]["version_number"] == 968

    selected = await get_embed_version(
        embed_id="embed-1", version_number=287, request=SimpleNamespace(),
        current_user=user, directus_service=directus, capability="bounded-v1",
    )
    assert [row["version_number"] for row in selected["rows"]] == list(range(256, 288))
    assert selected["rows"][0]["encrypted_snapshot"] == "cipher-snapshot-256"
    assert all("archive_object_key" not in row for row in selected["rows"])


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_legacy_long_chain_remains_pending_without_client_snapshot():
    directus = FakeDirectusService()
    directus.rows = [
        {
            "embed_id": "embed-1", "hashed_user_id": OWNER_HASH,
            "version_number": number, "created_at": 1760000000 + number,
            "encrypted_snapshot": "cipher-start" if number == 1 else None,
            "encrypted_patch": f"cipher-patch-{number}" if number > 1 else None,
        }
        for number in range(1, 102)
    ]
    directus.embed.embed["version_number"] = 101
    with pytest.raises(HTTPException) as exc_info:
        await get_embed_version(
            embed_id="embed-1", version_number=101, request=SimpleNamespace(),
            current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
            capability="bounded-v1",
        )
    assert exc_info.value.status_code == 409
    # A sealed output can exist before its canonical version row. Absence is
    # retryable by persisting that output; it must not demand a new snapshot.
    for target, rows in ((102, directus.rows), (1, []), (2, directus.rows[:1])):
        original_rows = directus.rows
        directus.rows = rows
        with pytest.raises(HTTPException) as missing:
            await get_embed_version(
                embed_id="embed-1", version_number=target, request=SimpleNamespace(),
                current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
                capability="bounded-v1",
            )
        assert missing.value.status_code == 404
        directus.rows = original_rows
    legacy = await get_embed_version(
        embed_id="embed-1", version_number=101, request=SimpleNamespace(),
        current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
    )
    assert len(legacy["rows"]) == 101


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload,storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_selected_copied_version_reads_verified_archive_payload(monkeypatch):
    directus = FakeDirectusService()
    directus.rows[0]["archive_state"] = "reader_active"
    directus.rows[0]["archive_object_key"] = "archive-key"
    payload = json.dumps({
        "version_number": 1, "encrypted_snapshot": "first line\nsecond line",
        "encrypted_patch": None,
    }).encode()
    directus.rows[0]["archive_checksum"] = hashlib.sha256(payload).hexdigest()
    calls = []

    class S3:
        environment = "development"

        async def get_file(self, bucket, key):
            calls.append((bucket, key))
            return payload

    monkeypatch.setattr(embeds_api, "get_s3_service", lambda request: S3())
    monkeypatch.setattr(
        "backend.core.api.app.services.embed_version_archive_service.get_bucket_name",
        lambda *args: "test-bucket",
    )
    response = await get_embed_version(
        embed_id="embed-1", version_number=1, request=SimpleNamespace(),
        current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
        capability="bounded-v1",
    )
    assert calls == [("test-bucket", "archive-key")]
    assert response["rows"][0]["encrypted_snapshot"] == "first line\nsecond line"
    assert "archive_object_key" not in response["rows"][0]


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_pruned_version_reconstructs_from_checksum_verified_s3_ciphertext(monkeypatch):
    directus = FakeDirectusService()
    archived = json.dumps({
        "version_number": 1, "encrypted_snapshot": "first line\nsecond line",
        "encrypted_patch": None,
    }).encode()
    directus.rows[0].update({
        "encrypted_snapshot": None, "encrypted_patch": None, "has_snapshot": True,
        "archive_state": "pruned", "archive_object_key": "archive-v1",
        "archive_checksum": hashlib.sha256(archived).hexdigest(),
    })

    class S3:
        environment = "development"

        async def get_file(self, bucket, key):
            assert key == "archive-v1"
            return archived

    monkeypatch.setattr(embeds_api, "get_s3_service", lambda request: S3())
    response = await get_embed_version(
        embed_id="embed-1", version_number=2, request=SimpleNamespace(),
        current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
        capability="bounded-v1",
    )
    assert response["rows"][0]["encrypted_snapshot"] == "first line\nsecond line"
    assert response["rows"][1]["encrypted_patch"]
    assert len(response["rows"]) == 2

    directus.rows[0]["archive_checksum"] = "0" * 64
    with pytest.raises(HTTPException) as corrupted:
        await get_embed_version(
            embed_id="embed-1", version_number=2, request=SimpleNamespace(),
            current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
            capability="bounded-v1",
        )
    assert corrupted.value.status_code == 503


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_snapshot_route_forwards_only_ciphertext_and_actor_identity_to_fenced_extension(monkeypatch):
    directus = FakeDirectusService()
    directus.base_url = "http://directus.test"
    sent = []

    async def request(method, url, **kwargs):
        sent.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"data": {
            "status": "committed", "version_number": 2,
        }})

    directus._make_api_request = request
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    result = await publish_embed_version_snapshot(
        embed_id="embed-1", version_number=2, request=SimpleNamespace(),
        payload={"encrypted_snapshot": "opaque-ciphertext", "expected_revision": 2,
                 "operation_id": "snapshot.v2", "project_id": "project-1"},
        current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
    )
    assert result["status"] == "committed"
    assert sent[0][2]["json"]["actor_user_hash"] == OWNER_HASH
    assert sent[0][2]["json"]["encrypted_snapshot"] == "opaque-ciphertext"
    assert "content" not in sent[0][2]["json"]


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_chat_embed_window_returns_only_one_authorized_ciphertext_page_and_scoped_keys():
    calls = []

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return chat_id == "chat-1" and user_id == OWNER_ID

    class Embed:
        async def get_embed_window_by_hashed_chat_id(self, chat_hash, **cursor):
            calls.append((chat_hash, cursor))
            return {"embeds": [{"embed_id": "embed-1", "hashed_embed_id": "hash-embed", "encrypted_content": "cipher"}],
                    "has_more_before": True, "start_cursor": {"created_at": 10, "id": "row-1"},
                    "oversized_embed_id": None}

        async def get_sync_embed_key_window_for_page(self, chat_hash, owner_hash, embed_hashes, **kwargs):
            assert embed_hashes == ["hash-embed"]
            assert owner_hash == OWNER_HASH
            return {"embed_keys": [{"hashed_embed_id": "hash-embed", "encrypted_embed_key": "wrapped"}],
                    "has_more_after": True, "end_cursor": "key-1", "oversized_key_id": None}

    directus = SimpleNamespace(chat=Chat(), embed=Embed())
    result = await get_chat_embed_window(
        chat_id="chat-1", request=SimpleNamespace(), before_created_at=10, before_id="row-1",
        team_id=None, current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
    )
    assert result["embeds"][0]["encrypted_content"] == "cipher"
    assert result["embed_keys"][0]["encrypted_embed_key"] == "wrapped"
    assert result["has_more_before"] is True
    assert result["embed_keys_has_more_after"] is True
    assert result["embed_keys_end_cursor"] == "key-1"
    assert calls == [(hashlib.sha256(b"chat-1").hexdigest(), {"before_created_at": 10, "before_id": "row-1"})]
    with pytest.raises(HTTPException) as exc_info:
        await get_chat_embed_window(
            chat_id="other-chat", request=SimpleNamespace(), before_created_at=None, before_id=None,
            team_id=None, current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
        )
    assert exc_info.value.status_code == 404
    assert len(calls) == 1


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_team_embed_window_rechecks_membership_and_exact_chat_scope():
    visited = []

    class Team:
        async def require_team_role(self, team_id, user_id, roles):
            visited.append((team_id, user_id))
            if team_id != "team-1":
                raise team_methods_stub.TeamPermissionError("denied")

    class Chat:
        async def get_chat_metadata(self, chat_id, admin_required=False):
            return {"hashed_team_id": hashlib.sha256(b"other-team").hexdigest()}

    directus = SimpleNamespace(team=Team(), chat=Chat(), embed=SimpleNamespace())
    for team_id in ("team-1", "revoked-team"):
        with pytest.raises(HTTPException) as exc_info:
            await get_chat_embed_window(
                chat_id="chat-1", request=SimpleNamespace(), before_created_at=None, before_id=None,
                team_id=team_id, current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
            )
        assert exc_info.value.status_code == 404
    assert len(visited) == 2


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_embed_key_continuation_rechecks_chat_membership_and_exact_embed_scope():
    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return chat_id == "chat-1" and user_id == OWNER_ID

    class Embed:
        async def validate_embed_ids_in_chat(self, chat_hash, embed_ids):
            assert chat_hash == hashlib.sha256(b"chat-1").hexdigest()
            if embed_ids != ["embed-1"]:
                raise ValueError("not in chat")
            return [hashlib.sha256(b"embed-1").hexdigest()]

        async def get_sync_embed_key_window_for_page(self, chat_hash, owner_hash, hashes, after_key_id=None):
            assert after_key_id == "key-1"
            return {"embed_keys": [{"id": "key-2", "encrypted_embed_key": "wrapped"}],
                    "has_more_after": False, "end_cursor": "key-2", "oversized_key_id": None}

        async def get_sync_embed_key_by_id(self, chat_hash, owner_hash, hashes, key_id):
            return {"id": key_id, "encrypted_embed_key": "oversized"} if key_id == "key-big" else None

    directus = SimpleNamespace(chat=Chat(), embed=Embed())
    user = SimpleNamespace(id=OWNER_ID)
    page = await get_chat_embed_key_window(
        chat_id="chat-1", request=SimpleNamespace(), embed_ids="embed-1", after_key_id="key-1",
        current_user=user, directus_service=directus,
    )
    assert page["embed_keys"][0]["id"] == "key-2"
    exact = await get_chat_embed_key_window(
        chat_id="chat-1", request=SimpleNamespace(), embed_ids="embed-1", key_id="key-big",
        current_user=user, directus_service=directus,
    )
    assert exact["embed_keys"][0]["encrypted_embed_key"] == "oversized"
    with pytest.raises(HTTPException) as foreign:
        await get_chat_embed_key_window(
            chat_id="chat-1", request=SimpleNamespace(), embed_ids="foreign-embed", key_id="key-big",
            current_user=user, directus_service=directus,
        )
    assert foreign.value.status_code == 404


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_oversized_embed_exact_read_requires_checked_chat_and_returns_scoped_key_page():
    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return chat_id == "chat-1" and user_id == OWNER_ID

    class Embed:
        async def get_sync_embed_by_id(self, embed_id):
            return {"embed_id": embed_id, "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(),
                    "encrypted_content": "opaque-large-ciphertext"} if embed_id == "embed-1" else None

        async def get_sync_embed_key_window_for_page(self, chat_hash, owner_hash, hashes):
            assert hashes == [hashlib.sha256(b"embed-1").hexdigest()]
            return {"embed_keys": [{"encrypted_embed_key": "wrapped"}],
                    "has_more_after": False, "end_cursor": "key-1", "oversized_key_id": None}

    directus = SimpleNamespace(chat=Chat(), embed=Embed())
    response = await get_chat_embed_by_id(
        chat_id="chat-1", embed_id="embed-1", request=SimpleNamespace(),
        current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
    )
    assert response["embed"]["encrypted_content"] == "opaque-large-ciphertext"
    assert response["embed_keys"][0]["encrypted_embed_key"] == "wrapped"
    with pytest.raises(HTTPException) as denied:
        await get_chat_embed_by_id(
            chat_id="chat-other", embed_id="embed-1", request=SimpleNamespace(),
            current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
        )
    assert denied.value.status_code == 404

    async def unavailable(_embed_id):
        raise RuntimeError("Directus unavailable")

    directus.embed.get_sync_embed_by_id = unavailable
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await get_chat_embed_by_id(
            chat_id="chat-1", embed_id="embed-1", request=SimpleNamespace(),
            current_user=SimpleNamespace(id=OWNER_ID), directus_service=directus,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_server_side_restore_is_rejected_without_appending_version_row():
    directus = FakeDirectusService()

    with pytest.raises(HTTPException) as exc_info:
        await restore_embed_version(
            embed_id="embed-1",
            version_number=1,
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id=RECIPIENT_ID),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 400
    assert len(directus.rows) == 2
    assert directus.embed.updates == []


# contract-test: direct surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_project_ciphertext_read_returns_fresh_head_project_wrapper_and_history_presence_only():
    directus = FakeDirectusService()

    result = await get_encrypted_project_embed(
        embed_id="embed-1",
        request=SimpleNamespace(),
        project_id="project-1",
        team_id=None,
        current_user=SimpleNamespace(id=OWNER_ID),
        directus_service=directus,
    )

    assert result["embed"]["encrypted_content"] == "cipher-head-v2"
    assert result["embed"]["version_number"] == 2
    assert result["embed_keys"] == [{
        "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(),
        "key_type": "project",
        "hashed_project_id": hashlib.sha256(b"project-1").hexdigest(),
        "encrypted_embed_key": "project-wrapped-key",
        "created_at": 1760000000,
    }]
    assert result["has_initial_history"] is True
    assert "file_path" not in result["embed"]
    assert "content_hash" not in result["embed"]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.access.explicit-context
@pytest.mark.asyncio
async def test_project_ciphertext_read_requires_current_item_membership():
    directus = FakeDirectusService()
    directus.project_item_exists = False

    with pytest.raises(HTTPException) as exc_info:
        await get_encrypted_project_embed(
            embed_id="embed-1",
            request=SimpleNamespace(),
            project_id="project-1",
            team_id=None,
            current_user=SimpleNamespace(id=OWNER_ID),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 404


# contract-test: direct surface=rest_api assertions=projects.files.commit-replay,projects.files.recovery-authorization
@pytest.mark.asyncio
async def test_revision_receipt_reconciles_exact_scope_without_returning_payload(monkeypatch):
    directus = FakeDirectusService()
    authorization_calls = []

    class FakeAuthorization:
        def __init__(self, directus_service, cache_service):
            assert directus_service is directus
            assert cache_service == "cache"

        async def require_write_authorization(self, **kwargs):
            authorization_calls.append(kwargs)
            return {"authorized": True}

    monkeypatch.setattr(embeds_api, "ProjectWriteAuthorizationService", FakeAuthorization)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service="cache")))

    result = await get_project_embed_revision_receipt(
        embed_id="embed-1",
        operation_id="operation-1",
        request=request,
        project_id="project-1",
        chat_id="chat-a",
        proposal_digest="b" * 64,
        team_id=None,
        current_user=SimpleNamespace(id=OWNER_ID),
        directus_service=directus,
    )

    assert result == {"status": "committed", "current_revision": 2}
    assert authorization_calls[0]["consume_approval"] is False
    assert "payload_digest" not in result
    assert "proposal_digest" not in result
