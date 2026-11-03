"""
Backend contract tests for durable share short links.

Shared chat and embed short links are user-facing public URLs, but the server
must never receive the fragment secret or decrypted long share URL. These tests
exercise the route functions directly with small fakes instead of a live CMS.
"""

import hashlib
import importlib
import io
from pathlib import Path
import sys
import types

import pytest
from pydantic import ValidationError


class _StubLimiter:
    def limit(self, _rule: str):
        def decorator(func):
            return func

        return decorator


directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
# Real pure team identity helpers remain importable through the service stub.
directus_stub.__path__ = [str(Path(__file__).resolve().parents[1] / "core/api/app/services/directus")]
encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
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
revoke_short_url = getattr(
    share_routes.revoke_short_url,
    "__wrapped__",
    share_routes.revoke_short_url,
)
get_shared_embed = getattr(
    share_routes.get_shared_embed,
    "__wrapped__",
    share_routes.get_shared_embed,
)
get_embed_og_metadata = getattr(
    share_routes.get_embed_og_metadata,
    "__wrapped__",
    share_routes.get_embed_og_metadata,
)


class FakeUser:
    id = "user-1"


class FakeChatMethods:
    def __init__(self) -> None:
        self.seen_chat_ids: list[str] = []

    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        self.seen_chat_ids.append(chat_id)
        if chat_id == "missing-chat":
            return None
        return {
            "id": chat_id,
            "is_private": False,
            "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
            "shared_encrypted_title": "enc-title",
            "shared_encrypted_summary": "enc-summary",
            "shared_encrypted_share_cta_text": None if chat_id == "chat-no-cta" else "enc-share-cta",
            "shared_encrypted_category": "enc-category",
            "shared_encrypted_icon": "enc-icon",
            "shared_encrypted_image_bubbles": "enc-image-bubbles",
        }


class FakeEmbedMethods:
    async def get_embed_by_id(self, embed_id: str):
        if embed_id == "missing-embed":
            return None
        if embed_id == "legacy-no-privacy-flag":
            return {
                "id": "embed-row-legacy",
                "embed_id": embed_id,
                "encrypted_content": "legacy-ciphertext",
                "shared_encrypted_title": "enc-legacy-embed-title",
                "shared_encrypted_description": "enc-legacy-embed-description",
                "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
            }
        return {
            "id": "embed-row-1",
            "embed_id": embed_id,
            "is_private": False,
            "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
        }

    async def get_embed_keys_by_embed_id(self, _embed_id: str):
        return []


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.embed = FakeEmbedMethods()
        self.short_links: list[dict] = []
        self.template_projections: list[dict] = []
        self.workflows: list[dict] = []
        self.updated_items: list[tuple[str, str, dict]] = []

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        params = params or {}
        if collection == "workflow_template_projections":
            template_id = params.get("filter[template_id][_eq]")
            rows = self.template_projections
            return [row for row in rows if row["template_id"] == template_id][:1]
        if collection == "workflows":
            workflow_id = params.get("filter[id][_eq]")
            rows = self.workflows
            return [row for row in rows if row["id"] == workflow_id][:1]
        if collection != "share_short_links":
            return []

        token = params.get("filter[token][_eq]")
        rows = self.short_links
        if token:
            rows = [row for row in rows if row["token"] == token]
        content_type = params.get("filter[content_type][_eq]")
        if content_type:
            rows = [row for row in rows if row.get("content_type") == content_type]
        content_id = params.get("filter[content_id][_eq]")
        if content_id:
            rows = [row for row in rows if row.get("content_id") == content_id]
        if params.get("filter[revoked_at][_null]") is True:
            rows = [row for row in rows if row.get("revoked_at") is None]
        return rows if params.get("limit") == -1 else rows[:1]

    async def create_item(self, collection: str, payload: dict, **_kwargs):
        assert collection == "share_short_links"
        row = {"id": f"short-{len(self.short_links) + 1}", **payload}
        self.short_links.append(row)
        return True, row

    async def update_item(self, collection: str, item_id: str, payload: dict, **_kwargs):
        self.updated_items.append((collection, item_id, payload))
        if collection == "share_short_links":
            for row in self.short_links:
                if row.get("id") == item_id:
                    row.update(payload)
                    break
        return {"id": item_id, **payload}


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_shared_embed_without_privacy_flag_defaults_to_private():
    result = await get_shared_embed(
        request=object(),
        embed_id="legacy-no-privacy-flag",
        directus_service=FakeDirectusService(),
    )

    assert result["embed"]["embed_id"] == "legacy-no-privacy-flag"
    assert result["embed"].get("encrypted_content") != "legacy-ciphertext"
    assert result["child_embeds"] == []
    assert result["embed_keys"] == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_shared_embed_og_metadata_without_privacy_flag_uses_fallback():
    result = await get_embed_og_metadata(
        request=object(),
        embed_id="legacy-no-privacy-flag",
        directus_service=FakeDirectusService(),
        encryption_service=FakeEncryptionService(),
    )

    assert result["title"] == "Shared Embed - OpenMates"
    assert result["description"] == "View this shared content on OpenMates"


class FailingCreateDirectusService(FakeDirectusService):
    async def create_item(self, collection: str, payload: dict, **_kwargs):
        assert collection == "share_short_links"
        return False, {"status_code": 403, "text": "permission denied"}


class FailingUpdateDirectusService(FakeDirectusService):
    async def update_item(self, collection: str, item_id: str, payload: dict, **_kwargs):
        self.updated_items.append((collection, item_id, payload))
        return None


class FakeCacheService:
    def __init__(self) -> None:
        self.short_links: dict[str, dict] = {}

    async def store_short_url(self, token: str, encrypted_url: str, ttl_seconds: int) -> bool:
        self.short_links[token] = {
            "encrypted_url": encrypted_url,
            "ttl_seconds": ttl_seconds,
        }
        return True

    async def resolve_short_url(self, token: str):
        record = self.short_links.get(token)
        if not record:
            return None
        return record["encrypted_url"]

    async def get_resolve_count(self, _token: str) -> int:
        return 0

    async def increment_resolve_count(self, _token: str) -> None:
        return None


class FakeEncryptionService:
    async def encrypt(self, value: str, key_name: str):
        assert key_name == "shared-content-metadata"
        return f"enc:{value}", "key-version"

    async def decrypt(self, value: str, key_name: str):
        assert key_name == "shared-content-metadata"
        return {
            "enc-title": "Paris travel plan",
            "enc-summary": "A concise itinerary for a weekend in Paris.",
            "enc-share-cta": "Plan a better weekend in Paris",
            "enc-category": "general_knowledge",
            "enc-icon": "map",
            "enc-image-bubbles": '[{"imageUrl":"https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg","title":"One"}]',
            "enc-legacy-embed-title": "Legacy private embed title",
            "enc-legacy-embed-description": "Legacy private embed description",
        }[value]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
@pytest.mark.parametrize("is_shared", [True, False])
async def test_embed_share_metadata_persists_to_distinct_directus_row_id(is_shared):
    row = {
        "id": "directus-primary-id",
        "embed_id": "public-embed-id",
        "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
        "is_private": is_shared,
        "is_shared": not is_shared,
        "encrypted_content": "unchanged-client-ciphertext",
        "asset_ref": "unchanged-durable-asset",
    }
    directus = FakeDirectusService()

    async def get_embed_by_id(embed_id):
        assert embed_id == row["embed_id"]
        return dict(row)

    async def update_item(collection, item_id, updates):
        directus.updated_items.append((collection, item_id, updates))
        if collection != "embeds" or item_id != row["id"]:
            return None
        row.update(updates)
        return dict(row)

    directus.embed.get_embed_by_id = get_embed_by_id
    directus.update_item = update_item
    result = await share_routes.update_embed_share_metadata(
        request=object(),
        payload=share_routes.ShareEmbedMetadataUpdate(
            embed_id=row["embed_id"], title="Shared title",
            description="Shared description", is_shared=is_shared,
        ),
        current_user=FakeUser(), directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert result["success"] is True
    assert result["embed_id"] == "public-embed-id"
    assert directus.updated_items == [("embeds", "directus-primary-id", {
        "shared_encrypted_title": "enc:Shared title",
        "shared_encrypted_description": "enc:Shared description",
        "is_private": not is_shared,
        "is_shared": is_shared,
    })]
    assert row["is_private"] is not is_shared
    assert row["is_shared"] is is_shared
    assert row["encrypted_content"] == "unchanged-client-ciphertext"
    assert row["asset_ref"] == "unchanged-durable-asset"


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_embed_share_metadata_failed_write_returns_error():
    directus = FailingUpdateDirectusService()
    with pytest.raises(share_routes.HTTPException) as error:
        await share_routes.update_embed_share_metadata(
            request=object(),
            payload=share_routes.ShareEmbedMetadataUpdate(embed_id="public-embed-id", is_shared=True),
            current_user=FakeUser(), directus_service=directus,
            encryption_service=FakeEncryptionService(),
        )
    assert error.value.status_code == 500
    assert directus.updated_items == [("embeds", "embed-row-1", {"is_private": False, "is_shared": True})]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
@pytest.mark.parametrize("row, status_code", [
    (None, 404),
    ({"id": "foreign-row", "hashed_user_id": "different-owner"}, 403),
    ({"hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest()}, 500),
])
async def test_embed_share_metadata_invalid_target_does_not_write(row, status_code):
    directus = FakeDirectusService()

    async def get_embed_by_id(_embed_id):
        return row

    directus.embed.get_embed_by_id = get_embed_by_id
    with pytest.raises(share_routes.HTTPException) as error:
        await share_routes.update_embed_share_metadata(
            request=object(),
            payload=share_routes.ShareEmbedMetadataUpdate(embed_id="public-embed-id", is_shared=True),
            current_user=FakeUser(), directus_service=directus,
            encryption_service=FakeEncryptionService(),
        )
    assert error.value.status_code == status_code
    assert directus.updated_items == []


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
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


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_create_chat_short_url_marks_chat_shared():
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
    assert ("chats", "chat-1", {"is_shared": True, "is_private": False}) in directus.updated_items


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
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


# contract-test: supporting surface=rest_api assertions=workflows.portability.private-content-boundary,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_workflow_template_short_link_never_accepts_fragment_key_and_is_revocable():
    directus = FakeDirectusService()
    workflow_owner_hash = "user_sha256:" + hashlib.sha256(FakeUser.id.encode()).hexdigest()
    directus.template_projections.append(
        {
            "template_id": "template-rain-v1",
            "workflow_id": "workflow-rain-v1",
            "hashed_user_id": workflow_owner_hash,
            "source_version": 3,
            "revoked_at": None,
        }
    )
    directus.workflows.append(
        {
            "id": "workflow-rain-v1",
            "hashed_user_id": workflow_owner_hash,
            "version": 3,
            "status": "active",
        }
    )

    with pytest.raises(ValidationError, match="fragment_key"):
        share_routes.CreateShortUrlRequest(
            token="Abc123XY",
            encrypted_url="opaque-ciphertext",
            content_type="workflow_template",
            content_id="template-rain-v1",
            fragment_key="never-send-this",
        )

    payload = share_routes.CreateShortUrlRequest(
        token="Abc123XY",
        encrypted_url="opaque-ciphertext",
        content_type="workflow_template",
        content_id="template-rain-v1",
    )
    response = await create_short_url(
        request=None,
        payload=payload,
        current_user=FakeUser(),
        directus_service=directus,
    )
    revoked = await revoke_short_url(token="Abc123XY", current_user=FakeUser(), directus_service=directus)

    assert response["success"] is True
    assert revoked["success"] is True
    with pytest.raises(share_routes.HTTPException, match="expired or not found"):
        await resolve_short_url(request=None, token="Abc123XY", directus_service=directus)


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_short_link_revocation_fails_closed_when_update_fails():
    directus = FailingUpdateDirectusService()
    directus.short_links.append(
        {
            "id": "row-1",
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "workflow_template",
            "content_id": "template-rain-v1",
            "hashed_user_id": hashlib.sha256(FakeUser.id.encode()).hexdigest(),
            "password_protected": False,
            "expires_at": None,
            "revoked_at": None,
        }
    )

    with pytest.raises(share_routes.HTTPException, match="Failed to revoke short link"):
        await revoke_short_url(token="Abc123XY", current_user=FakeUser(), directus_service=directus)

    assert directus.short_links[0]["revoked_at"] is None


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_workflow_template_short_link_fails_closed_without_durable_revocation_storage():
    directus = FailingCreateDirectusService()
    workflow_owner_hash = "user_sha256:" + hashlib.sha256(FakeUser.id.encode()).hexdigest()
    directus.template_projections.append(
        {
            "template_id": "template-rain-v1",
            "workflow_id": "workflow-rain-v1",
            "hashed_user_id": workflow_owner_hash,
            "source_version": 3,
            "revoked_at": None,
        }
    )
    directus.workflows.append(
        {
            "id": "workflow-rain-v1",
            "hashed_user_id": workflow_owner_hash,
            "version": 3,
            "status": "active",
        }
    )
    payload = share_routes.CreateShortUrlRequest(
        token="Abc123XY",
        encrypted_url="opaque-ciphertext",
        content_type="workflow_template",
        content_id="template-rain-v1",
    )

    with pytest.raises(share_routes.HTTPException, match="temporarily unavailable"):
        await create_short_url(
            request=None,
            payload=payload,
            current_user=FakeUser(),
            directus_service=directus,
            cache_service=FakeCacheService(),
        )


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
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
    assert ("chats", "chat-1", {"is_shared": True, "is_private": False}) in directus.updated_items


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_revoked_durable_short_url_does_not_fall_back_to_cache():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "revoked-durable-ciphertext",
            "content_type": "workflow_template",
            "content_id": "template-rain-v1",
            "password_protected": False,
            "expires_at": None,
            "revoked_at": 123,
        }
    )
    cache = FakeCacheService()
    await cache.store_short_url("Abc123XY", "legacy-cache-ciphertext", 3600)

    with pytest.raises(share_routes.HTTPException, match="expired or not found"):
        await resolve_short_url(
            request=None,
            token="Abc123XY",
            directus_service=directus,
            cache_service=cache,
        )


# contract-test: supporting surface=rest_api assertions=workflows.portability.private-content-boundary
@pytest.mark.asyncio
async def test_workflow_template_short_url_metadata_uses_generic_preview_without_chat_lookup():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "workflow_template",
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
        request=object(),
        token="Abc123XY",
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response["title"] == "Shared Workflow Template - OpenMates"
    assert response["content_type"] == "workflow_template"
    assert directus.chat.seen_chat_ids == []


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
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
    assert response["image_text"] == "Plan a better weekend in Paris"
    assert response["image"] == "/v1/share/short-url/Abc123XY/og-image.png"
    assert response["password_protected"] is False
    assert response["image_bubbles"] == [
        {
            "imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg",
            "title": "One",
        }
    ]


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_short_url_metadata_falls_back_to_summary_for_image_text_without_cta():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "token": "Abc123XY",
            "encrypted_url": "opaque-ciphertext",
            "content_type": "chat",
            "content_id": "chat-no-cta",
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

    assert response["description"] == "A concise itinerary for a weekend in Paris."
    assert response["image_text"] == "A concise itinerary for a weekend in Paris."


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_short_url_og_image_generates_png_for_shared_chat_metadata(monkeypatch):
    directus = FakeDirectusService()
    monkeypatch.setattr(share_routes, "_load_safe_og_bubble_image", lambda _url: None)
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

    get_og_image = getattr(
        share_routes.get_short_url_og_image,
        "__wrapped__",
        share_routes.get_short_url_og_image,
    )
    response = await get_og_image(
        request=None,
        token="Abc123XY",
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response.media_type == "image/png"
    assert response.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(response.body) > 1000
    from PIL import Image

    image = Image.open(io.BytesIO(response.body))
    assert image.size == (share_routes.OG_IMAGE_WIDTH, share_routes.OG_IMAGE_HEIGHT)


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
def test_short_url_og_image_draws_header_style_side_images(monkeypatch):
    from PIL import Image

    loaded_urls = []

    def fake_load_safe_bubble(url: str):
        loaded_urls.append(url)
        color = (220, 40, 40, 255) if "one.jpg" in url else (40, 80, 220, 255)
        return Image.new("RGBA", (320, 320), color)

    monkeypatch.setattr(share_routes, "_load_safe_og_bubble_image", fake_load_safe_bubble)

    png = share_routes._render_short_url_og_png(
        {
            "title": "Midi-chlorians and the Force in Star Wars",
            "description": "User asked about midi-chlorians in Star Wars; assistant explained their role in the Force and compared them to mitochondria.",
            "category": "movies_tv",
            "icon": "film",
            "image_bubbles": [
                {"imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg"},
                {"imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Ftwo.jpg"},
            ],
        }
    )

    image = Image.open(io.BytesIO(png)).convert("RGBA")
    assert loaded_urls == [
        "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg",
        "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Ftwo.jpg",
    ]
    left_bubble_pixel = image.getpixel((180, 460))
    right_bubble_pixel = image.getpixel((1020, 460))
    assert left_bubble_pixel[0] > left_bubble_pixel[2]
    assert right_bubble_pixel[2] > right_bubble_pixel[0]


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_chat_og_metadata_includes_header_image_bubbles():
    get_metadata = getattr(
        share_routes.get_og_metadata,
        "__wrapped__",
        share_routes.get_og_metadata,
    )

    response = await get_metadata(
        request=None,
        chat_id="chat-1",
        directus_service=FakeDirectusService(),
        encryption_service=FakeEncryptionService(),
    )

    assert response["category"] == "general_knowledge"
    assert response["icon"] == "map"
    assert response["image"] == "/v1/share/chat/chat-1/og-image.png"
    assert response["image_bubbles"] == [
        {
            "imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg",
            "title": "One",
        }
    ]


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_direct_chat_og_image_generates_png_for_shared_chat_metadata(monkeypatch):
    monkeypatch.setattr(share_routes, "_load_safe_og_bubble_image", lambda _url: None)
    get_og_image = getattr(
        share_routes.get_chat_og_image,
        "__wrapped__",
        share_routes.get_chat_og_image,
    )

    response = await get_og_image(
        request=None,
        chat_id="chat-1",
        directus_service=FakeDirectusService(),
        encryption_service=FakeEncryptionService(),
    )

    assert response.media_type == "image/png"
    assert response.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(response.body) > 1000


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
def test_og_icon_uses_stored_lucide_icon_before_fallback(monkeypatch):
    from PIL import Image, ImageDraw

    used_icons = []

    def fake_draw_lucide_icon(_draw, _center_x, _center_y, _size, icon, _color):
        used_icons.append(icon)
        return True

    monkeypatch.setattr(share_routes, "_draw_lucide_icon", fake_draw_lucide_icon)
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    share_routes._draw_og_icon(draw, 100, 100, 90, {"icon": "map"}, (255, 255, 255, 255))

    assert used_icons == ["map"]


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
def test_short_url_og_image_uses_packaged_lexend_deca_font():
    from PIL import Image, ImageDraw, ImageFont

    font = share_routes._load_og_font(44, bold=True)
    assert isinstance(font, ImageFont.FreeTypeFont)

    image = Image.new("RGB", (500, 120), "white")
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), "OpenMates", font=font)
    assert bbox[2] - bbox[0] > 180
    assert bbox[3] - bbox[1] > 25


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
def test_chat_metadata_field_list_includes_shared_preview_fields_and_stored_url():
    repo_root = Path(__file__).resolve().parents[2]
    chat_methods_source = (repo_root / "backend/core/api/app/services/directus/chat_methods.py").read_text()

    assert "shared_encrypted_category" in chat_methods_source
    assert "shared_encrypted_icon" in chat_methods_source
    assert "shared_encrypted_share_cta_text" in chat_methods_source
    assert "shared_encrypted_image_bubbles" in chat_methods_source
    assert "encrypted_share_cta_text" in chat_methods_source
    assert "encrypted_shared_short_url" in chat_methods_source


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_share_metadata_update_can_clear_encrypted_shared_short_url():
    directus = FakeDirectusService()
    update_metadata = getattr(
        share_routes.update_share_metadata,
        "__wrapped__",
        share_routes.update_share_metadata,
    )
    payload = share_routes.ShareChatMetadataUpdate(
        chat_id="chat-1",
        title="Paris travel plan",
        encrypted_shared_short_url=None,
    )

    response = await update_metadata(
        request=None,
        payload=payload,
        current_user=FakeUser(),
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response == {"success": True, "chat_id": "chat-1"}
    assert directus.updated_items[0][0:2] == ("chats", "chat-1")
    assert directus.updated_items[0][2]["encrypted_shared_short_url"] is None


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_share_metadata_update_encrypts_image_bubbles_for_og_header():
    directus = FakeDirectusService()
    update_metadata = getattr(
        share_routes.update_share_metadata,
        "__wrapped__",
        share_routes.update_share_metadata,
    )
    payload = share_routes.ShareChatMetadataUpdate(
        chat_id="chat-1",
        image_bubbles=[
            {
                "imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg",
                "title": "One",
                "ignored": "not stored",
            },
            {"imageUrl": "", "title": "Ignored"},
        ],
    )

    response = await update_metadata(
        request=None,
        payload=payload,
        current_user=FakeUser(),
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
    )

    assert response == {"success": True, "chat_id": "chat-1"}
    encrypted_payload = directus.updated_items[0][2]["shared_encrypted_image_bubbles"]
    assert encrypted_payload.startswith("enc:")
    assert "ignored" not in encrypted_payload
    assert "https://preview.openmates.org/api/v1/image" in encrypted_payload


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
@pytest.mark.asyncio
async def test_unshare_chat_clears_metadata_and_revokes_short_links():
    directus = FakeDirectusService()
    directus.short_links.append(
        {
            "id": "short-1",
            "token": "Abc123XY",
            "content_type": "chat",
            "content_id": "chat-1",
            "revoked_at": None,
        }
    )
    unshare = getattr(
        share_routes.unshare_chat,
        "__wrapped__",
        share_routes.unshare_chat,
    )

    response = await unshare(
        payload=share_routes.UnshareChatRequest(chat_id="chat-1"),
        request=None,
        current_user=FakeUser(),
        directus_service=directus,
    )

    assert response == {"success": True, "chat_id": "chat-1"}
    chat_update = directus.updated_items[0][2]
    assert chat_update["is_private"] is True
    assert chat_update["is_shared"] is False
    assert chat_update["shared_encrypted_title"] is None
    assert chat_update["shared_encrypted_summary"] is None
    assert chat_update["shared_encrypted_share_cta_text"] is None
    assert chat_update["shared_encrypted_category"] is None
    assert chat_update["shared_encrypted_icon"] is None
    assert chat_update["shared_encrypted_image_bubbles"] is None
    assert chat_update["encrypted_shared_short_url"] is None
    short_link_update = directus.updated_items[1]
    assert short_link_update[0:2] == (share_routes.SHORT_URL_COLLECTION, "short-1")
    assert isinstance(short_link_update[2]["revoked_at"], int)
    assert short_link_update[2]["updated_at"] == short_link_update[2]["revoked_at"]


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
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
    assert response["image"] == "/images/password-protected-chat-og.png"
    assert response["password_protected"] is True


# contract-test: supporting surface=rest_api assertions=chat-share-settings.shared-link-open
def test_password_protected_og_image_asset_exists_with_social_preview_size():
    from PIL import Image

    repo_root = Path(__file__).resolve().parents[2]
    image_path = repo_root / "frontend/apps/web_app/static/images/password-protected-chat-og.png"
    assert image_path.exists()

    image = Image.open(image_path)
    assert image.size == (share_routes.OG_IMAGE_WIDTH, share_routes.OG_IMAGE_HEIGHT)


class AuthoredShareGraphMethods:
    def __init__(self, records, keys=None):
        self.records = records
        self.keys = keys or {}
        self.read_ids = []
        self.key_ids = []

    async def get_embed_by_id(self, embed_id):
        self.read_ids.append(embed_id)
        return self.records.get(embed_id)

    async def get_embed_keys_by_embed_id(self, embed_id):
        self.key_ids.append(embed_id)
        return self.keys.get(embed_id, [])


class AuthoredShareGraphDirectus:
    def __init__(self, records, keys=None):
        self.embed = AuthoredShareGraphMethods(records, keys)

    async def get_items(self, *_args, **_kwargs):
        return []


def shared_graph_row(embed_id, **fields):
    return {"embed_id": embed_id, "hashed_user_id": "owner", "hashed_chat_id": "chat",
            "encrypted_content": "ciphertext-" + embed_id, "is_private": False,
            "status": "finished", **fields}


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse
@pytest.mark.asyncio
async def test_authored_share_expands_only_ordered_scoped_children_and_recipient_wrappers():
    parent = shared_graph_row("carrier", app_id="ai", skill_id="authored_results", is_shared=True,
                              embed_ids=["second", "first", "second", "foreign-owner", "foreign-chat", "wrong-parent", "legacy-no-backlink", "pending", "carrier"])
    records = {"carrier": parent, "first": shared_graph_row("first", parent_embed_id="carrier"),
               "second": shared_graph_row("second", parent_embed_id="carrier", source_embed_id="private-upload",
                                           authoring={"sources": [{"embed_ref": "private-notes"}]}),
               "foreign-owner": shared_graph_row("foreign-owner", parent_embed_id="carrier", hashed_user_id="foreign"),
               "foreign-chat": shared_graph_row("foreign-chat", parent_embed_id="carrier", hashed_chat_id="foreign"),
               "wrong-parent": shared_graph_row("wrong-parent", parent_embed_id="other"),
               "legacy-no-backlink": shared_graph_row("legacy-no-backlink"),
               "pending": shared_graph_row("pending", parent_embed_id="carrier", status="processing"),
               "private-upload": shared_graph_row("private-upload")}
    root_hash = hashlib.sha256(b"carrier").hexdigest()
    child_hash = hashlib.sha256(b"first").hexdigest()
    valid_key = {"id": "selected-wrapper", "key_type": "embed", "parent_embed_id": root_hash,
                 "hashed_embed_id": child_hash, "encrypted_embed_key": "wrapped-child-key"}
    keys = {"first": [valid_key, {**valid_key, "id": "owner-master", "key_type": "master"},
                      {**valid_key, "id": "owner-chat", "key_type": "chat"},
                      {**valid_key, "id": "other-parent", "parent_embed_id": "unrelated"},
                      {**valid_key, "id": "other-child", "hashed_embed_id": "unrelated"}]}
    directus = AuthoredShareGraphDirectus(records, keys)
    result = await get_shared_embed(request=object(), embed_id="carrier", directus_service=directus)
    assert [row["embed_id"] for row in result["child_embeds"]] == ["second", "first"]
    assert result["embed_keys"] == [valid_key]
    assert directus.embed.key_ids == ["second", "first"]
    assert "private-upload" not in directus.embed.read_ids
    assert "private-notes" not in directus.embed.read_ids


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.media.safe-and-attributed
@pytest.mark.asyncio
async def test_individual_authored_share_cannot_open_unshared_carrier_or_sibling_with_inherited_key():
    records = {"carrier": shared_graph_row("carrier", app_id="ai", skill_id="authored_results",
                                           is_shared=False, embed_ids=["selected", "sibling"]),
               "selected": shared_graph_row("selected", parent_embed_id="carrier", is_shared=True),
               "sibling": shared_graph_row("sibling", parent_embed_id="carrier", is_shared=False)}
    directus = AuthoredShareGraphDirectus(records)
    selected = await get_shared_embed(request=object(), embed_id="selected", directus_service=directus)
    assert selected["embed"]["encrypted_content"] == "ciphertext-selected"
    assert selected["child_embeds"] == [] and selected["embed_keys"] == []
    for target in ("carrier", "sibling"):
        denied = await get_shared_embed(request=object(), embed_id=target, directus_service=directus)
        assert denied["embed"]["encrypted_content"] != "ciphertext-" + target
        assert denied["child_embeds"] == [] and denied["embed_keys"] == []
    records["carrier"]["is_shared"] = True
    group_member = await get_shared_embed(request=object(), embed_id="sibling", directus_service=directus)
    assert group_member["embed"]["encrypted_content"] == "ciphertext-sibling"


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_legacy_shared_children_without_backlinks_keep_valid_owner_chat_membership():
    records = {"legacy": shared_graph_row("legacy", embed_ids=["old-child", "foreign", "wrong-parent"]),
               "old-child": shared_graph_row("old-child"),
               "foreign": shared_graph_row("foreign", hashed_chat_id="different"),
               "wrong-parent": shared_graph_row("wrong-parent", parent_embed_id="unrelated")}
    result = await get_shared_embed(request=object(), embed_id="legacy", directus_service=AuthoredShareGraphDirectus(records))
    assert result["embed"]["encrypted_content"] == "ciphertext-legacy"
    assert [row["embed_id"] for row in result["child_embeds"]] == ["old-child"]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_authored_shared_individual_still_requires_legitimate_carrier_scope_membership():
    for patch in ({"hashed_user_id": "foreign"}, {"hashed_chat_id": "foreign"}, {"hashed_team_id": "foreign"}):
        records = {"carrier": shared_graph_row("carrier", app_id="ai", skill_id="authored_results", is_shared=True, embed_ids=["child"]),
                   "child": shared_graph_row("child", parent_embed_id="carrier", is_shared=True, **patch)}
        result = await get_shared_embed(request=object(), embed_id="child", directus_service=AuthoredShareGraphDirectus(records))
        assert result["embed"].get("encrypted_content") != "ciphertext-child"
    records = {"carrier": shared_graph_row("carrier", app_id="ai", skill_id="authored_results", is_shared=True, embed_ids=[]),
               "unselected": shared_graph_row("unselected", parent_embed_id="carrier", is_shared=True)}
    result = await get_shared_embed(request=object(), embed_id="unselected", directus_service=AuthoredShareGraphDirectus(records))
    assert result["embed"].get("encrypted_content") != "ciphertext-unselected"


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_unshared_authored_carrier_does_not_expose_og_metadata():
    records = {"carrier": shared_graph_row("carrier", app_id="ai", skill_id="authored_results", is_shared=False,
                                           shared_encrypted_title="private-group-title")}
    result = await get_embed_og_metadata(request=object(), embed_id="carrier",
                                         directus_service=AuthoredShareGraphDirectus(records), encryption_service=object())
    assert result["title"] == "Shared Embed - OpenMates"


# contract-test: supporting surface=rest_api assertions=authored-results.groups.same-response-and-reuse
@pytest.mark.asyncio
async def test_authored_shared_graph_is_bounded_before_fetching_child_records_or_wrappers():
    ids = [f"child-{index}" for index in range(60)]
    records = {"carrier": shared_graph_row("carrier", app_id="ai", skill_id="authored_results", is_shared=True, embed_ids=ids)}
    records.update({child_id: shared_graph_row(child_id, parent_embed_id="carrier") for child_id in ids})
    directus = AuthoredShareGraphDirectus(records)
    result = await get_shared_embed(request=object(), embed_id="carrier", directus_service=directus)
    assert [row["embed_id"] for row in result["child_embeds"]] == ids[:50]
    assert directus.embed.read_ids == ["carrier", *ids[:50]]
    assert directus.embed.key_ids == ids[:50]


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_explicit_false_share_flag_fails_closed_before_catalog_sidecars_exist():
    records = {"carrier": shared_graph_row("carrier", is_shared=False, embed_ids=["selected", "sibling"]),
               "selected": shared_graph_row("selected", parent_embed_id="carrier", is_shared=True),
               "sibling": shared_graph_row("sibling", parent_embed_id="carrier", is_shared=False)}
    directus = AuthoredShareGraphDirectus(records)
    selected = await get_shared_embed(request=object(), embed_id="selected", directus_service=directus)
    assert selected["embed"]["encrypted_content"] == "ciphertext-selected"
    for target in ("carrier", "sibling"):
        result = await get_shared_embed(request=object(), embed_id=target, directus_service=directus)
        assert result["embed"].get("encrypted_content") != "ciphertext-" + target
    records["carrier"]["is_shared"] = True
    group = await get_shared_embed(request=object(), embed_id="carrier", directus_service=directus)
    assert [row["embed_id"] for row in group["child_embeds"]] == ["selected", "sibling"]
    sibling = await get_shared_embed(request=object(), embed_id="sibling", directus_service=directus)
    assert sibling["embed"]["encrypted_content"] == "ciphertext-sibling"


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_missing_legacy_share_flag_preserves_declared_same_scope_child_access():
    records = {"old-parent": shared_graph_row("old-parent", embed_ids=["old-child"]),
               "old-child": shared_graph_row("old-child", parent_embed_id="old-parent", is_shared=False)}
    result = await get_shared_embed(request=object(), embed_id="old-child", directus_service=AuthoredShareGraphDirectus(records))
    assert result["embed"].get("encrypted_content") == "ciphertext-old-child"
