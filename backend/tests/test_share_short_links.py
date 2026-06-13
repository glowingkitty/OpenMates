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
    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
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
        self.updated_items: list[tuple[str, str, dict]] = []

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        if collection != "share_short_links":
            return []

        params = params or {}
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
        return {"id": item_id, **payload}


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
    assert response["image_text"] == "Plan a better weekend in Paris"
    assert response["image"] == "/v1/share/short-url/Abc123XY/og-image.png"
    assert response["password_protected"] is False
    assert response["image_bubbles"] == [
        {
            "imageUrl": "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.com%2Fone.jpg",
            "title": "One",
        }
    ]


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


def test_short_url_og_image_uses_packaged_lexend_deca_font():
    from PIL import Image, ImageDraw, ImageFont

    font = share_routes._load_og_font(44, bold=True)
    assert isinstance(font, ImageFont.FreeTypeFont)

    image = Image.new("RGB", (500, 120), "white")
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), "OpenMates", font=font)
    assert bbox[2] - bbox[0] > 180
    assert bbox[3] - bbox[1] > 25


def test_chat_metadata_field_list_includes_shared_preview_fields_and_stored_url():
    repo_root = Path(__file__).resolve().parents[2]
    chat_methods_source = (repo_root / "backend/core/api/app/services/directus/chat_methods.py").read_text()

    assert "shared_encrypted_category" in chat_methods_source
    assert "shared_encrypted_icon" in chat_methods_source
    assert "shared_encrypted_share_cta_text" in chat_methods_source
    assert "shared_encrypted_image_bubbles" in chat_methods_source
    assert "encrypted_share_cta_text" in chat_methods_source
    assert "encrypted_shared_short_url" in chat_methods_source


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


def test_password_protected_og_image_asset_exists_with_social_preview_size():
    from PIL import Image

    repo_root = Path(__file__).resolve().parents[2]
    image_path = repo_root / "frontend/apps/web_app/static/images/password-protected-chat-og.png"
    assert image_path.exists()

    image = Image.open(image_path)
    assert image.size == (share_routes.OG_IMAGE_WIDTH, share_routes.OG_IMAGE_HEIGHT)
