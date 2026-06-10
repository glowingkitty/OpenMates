"""
Backend contract tests for durable share short links.

Shared chat and embed short links are user-facing public URLs, but the server
must never receive the fragment secret or decrypted long share URL. These tests
exercise the route functions directly with small fakes instead of a live CMS.
"""

import hashlib
import importlib
import sys
import types

import pytest


class _StubLimiter:
    def limit(self, _rule: str):
        def decorator(func):
            return func

        return decorator


directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
user_stub = types.ModuleType("backend.core.api.app.models.user")
user_stub.User = object

_STUB_MODULES = {
    "backend.core.api.app.services.directus": directus_stub,
    "backend.core.api.app.utils.encryption": encryption_stub,
    "backend.core.api.app.services.cache": cache_stub,
    "backend.core.api.app.services.limiter": limiter_stub,
    "backend.core.api.app.routes.auth_routes.auth_dependencies": auth_deps_stub,
    "backend.core.api.app.models.user": user_stub,
}
_previous_modules = {name: sys.modules.get(name) for name in _STUB_MODULES}
try:
    sys.modules.update(_STUB_MODULES)
    share_routes = importlib.import_module("backend.core.api.app.routes.share")
finally:
    sys.modules.pop("backend.core.api.app.routes.share", None)
    for name, previous_module in _previous_modules.items():
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module


create_short_url = getattr(
    share_routes.create_short_url,
    "__wrapped__",
    share_routes.create_short_url,
)
resolve_short_url = getattr(
    share_routes.resolve_short_url,
    "__wrapped__",
    share_routes.resolve_short_url,
)


class FakeUser:
    id = "user-1"


class FakeChatMethods:
    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        if chat_id == "missing-chat":
            return None
        return {
            "id": chat_id,
            "is_private": False,
            "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
            "shared_encrypted_title": "enc-title",
            "shared_encrypted_summary": "enc-summary",
            "shared_encrypted_category": "enc-category",
            "shared_encrypted_icon": "enc-icon",
        }


class FakeEmbedMethods:
    async def get_embed_by_id(self, embed_id: str):
        if embed_id == "missing-embed":
            return None
        return {
            "id": "embed-row-1",
            "embed_id": embed_id,
            "is_private": False,
            "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
        }


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.embed = FakeEmbedMethods()
        self.short_links: list[dict] = []

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        if collection != "share_short_links":
            return []

        token = (params or {}).get("filter[token][_eq]")
        rows = self.short_links
        if token:
            rows = [row for row in rows if row["token"] == token]
        return rows[:1]

    async def create_item(self, collection: str, payload: dict, **_kwargs):
        assert collection == "share_short_links"
        row = {"id": f"short-{len(self.short_links) + 1}", **payload}
        self.short_links.append(row)
        return True, row


class FailingCreateDirectusService(FakeDirectusService):
    async def create_item(self, collection: str, payload: dict, **_kwargs):
        assert collection == "share_short_links"
        return False, {"status_code": 403, "text": "permission denied"}


class FakeCacheService:
    def __init__(self) -> None:
        self.short_links: dict[str, dict] = {}

    async def store_short_url(self, token: str, encrypted_url: str, ttl_seconds: int) -> bool:
        self.short_links[token] = {
            "encrypted_url": encrypted_url,
            "ttl_seconds": ttl_seconds,
        }
        return True


class FakeEncryptionService:
    async def decrypt(self, value: str, key_name: str):
        assert key_name == "shared-content-metadata"
        return {
            "enc-title": "Paris travel plan",
            "enc-summary": "A concise itinerary for a weekend in Paris.",
            "enc-category": "general_knowledge",
            "enc-icon": "map",
        }[value]


@pytest.mark.asyncio
async def test_create_short_url_stores_no_expiration_as_null():
    directus = FakeDirectusService()
    payload = share_routes.CreateShortUrlRequest(
        token="Abc123XY",
        encrypted_url="opaque-ciphertext",
        content_type="chat",
        content_id="chat-1",
        password_protected=False,
        ttl_seconds=None,
    )

    response = await create_short_url(
        request=None,
        payload=payload,
        current_user=FakeUser(),
        directus_service=directus,
    )

    assert response == {"success": True, "expires_at": None}
    assert directus.short_links[0]["expires_at"] is None
    assert directus.short_links[0]["content_type"] == "chat"
    assert directus.short_links[0]["content_id"] == "chat-1"
    assert directus.short_links[0]["password_protected"] is False


@pytest.mark.asyncio
async def test_create_short_url_uses_cache_fallback_when_durable_storage_is_unavailable():
    directus = FailingCreateDirectusService()
    cache = FakeCacheService()
    payload = share_routes.CreateShortUrlRequest(
        token="Abc123XY",
        encrypted_url="opaque-ciphertext",
        content_type="chat",
        content_id="chat-1",
        password_protected=False,
        ttl_seconds=None,
    )

    response = await create_short_url(
        request=None,
        payload=payload,
        current_user=FakeUser(),
        directus_service=directus,
        cache_service=cache,
    )

    assert response["success"] is True
    assert isinstance(response["expires_at"], int)
    assert cache.short_links["Abc123XY"] == {
        "encrypted_url": "opaque-ciphertext",
        "ttl_seconds": share_routes.cache_config.SHORT_URL_MAX_TTL,
    }


@pytest.mark.asyncio
async def test_resolve_short_url_returns_only_encrypted_url():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "chat",
            "content_id": "chat-1",
            "password_protected": False,
            "expires_at": None,
            "revoked_at": None,
        }
    )

    response = await resolve_short_url(
        request=None,
        token="Abc123XY",
        directus_service=directus,
    )

    assert response == {"encrypted_url": "opaque-ciphertext"}


@pytest.mark.asyncio
async def test_short_url_metadata_uses_shared_chat_title_and_summary():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "chat",
            "content_id": "chat-1",
            "password_protected": False,
            "expires_at": None,
            "revoked_at": None,
        }
    )

    get_metadata = getattr(
        share_routes.get_short_url_metadata,
        "__wrapped__",
        share_routes.get_short_url_metadata,
    )
    response = await get_metadata(
        request=None,
        token="Abc123XY",
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response["title"] == "Paris travel plan"
    assert response["description"] == "A concise itinerary for a weekend in Paris."
    assert response["image"] == "/v1/share/short-url/Abc123XY/og-image.png"
    assert response["password_protected"] is False


@pytest.mark.asyncio
async def test_password_protected_short_url_metadata_hides_chat_metadata():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "chat",
            "content_id": "chat-1",
            "password_protected": True,
            "expires_at": None,
            "revoked_at": None,
        }
    )

    get_metadata = getattr(
        share_routes.get_short_url_metadata,
        "__wrapped__",
        share_routes.get_short_url_metadata,
    )
    response = await get_metadata(
        request=None,
        token="Abc123XY",
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response["title"] == "Password protected chat"
    assert "Paris" not in response["description"]
    assert response["image"] == "/v1/share/short-url/Abc123XY/og-image.png"
    assert response["password_protected"] is True
