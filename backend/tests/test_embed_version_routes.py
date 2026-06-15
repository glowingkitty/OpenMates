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
auth_deps_stub.get_current_user_or_api_key = lambda: None
sys.modules.setdefault("backend.core.api.app.routes.auth_routes.auth_dependencies", auth_deps_stub)

directus_module_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module_stub)

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
            }
        )
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


list_embed_versions = getattr(embeds_api.list_embed_versions, "__wrapped__", embeds_api.list_embed_versions)
get_embed_version = getattr(embeds_api.get_embed_version, "__wrapped__", embeds_api.get_embed_version)
restore_embed_version = getattr(embeds_api.restore_embed_version, "__wrapped__", embeds_api.restore_embed_version)


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
