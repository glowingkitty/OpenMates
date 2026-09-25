"""Route-level tests for embed version history endpoints.

These tests keep the REST contract deterministic without a live Directus or
Vault dependency. The fake services model append-only client-encrypted
`embed_diffs` rows and owner-gated parent embed access used by clients.
They intentionally exercise route functions directly so auth/rate-limit
middleware does not obscure the version-history behavior under test.
"""

import difflib
import hashlib
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
s3_config_stub.get_bucket_name = lambda: "test-bucket"
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
        if project_id == "project-1" and user_id == OWNER_ID:
            return {"project_id": project_id}
        return None

    async def _require_team_role(self, team_id: str, user_id: str, roles: set[str]):
        if team_id == "team-1" and user_id == OWNER_ID:
            return {"role": "member"}
        raise RuntimeError("denied")

    async def read_items(self, collection: str, params: dict):
        assert collection == "embed_diffs"
        filters = params.get("filter", {})
        embed_filter = filters.get("embed_id", {}).get("_eq")
        owner_filter = filters.get("hashed_user_id", {}).get("_eq")
        max_version = filters.get("version_number", {}).get("_lte")
        rows = [
            row
            for row in self.rows
            if row["embed_id"] == embed_filter and row["hashed_user_id"] == owner_filter
        ]
        if max_version is not None:
            rows = [row for row in rows if row["version_number"] <= max_version]
        return sorted(rows, key=lambda row: row["version_number"])

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
    assert history["versions"][0]["encrypted_snapshot"] == "first line\nsecond line"
    assert history["versions"][1]["encrypted_patch"] is not None

    version = await get_embed_version(
        embed_id="embed-1",
        version_number=1,
        request=SimpleNamespace(),
        current_user=user,
        directus_service=directus,
    )
    assert version["rows"][0]["encrypted_snapshot"] == "first line\nsecond line"
    assert "content" not in version


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
