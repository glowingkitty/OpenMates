"""Reverse search consumes owned image refs directly, using real media decryption."""

# contract-test-file: infrastructure
import hashlib
import io
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image
from toon_format import encode

from backend.apps.images.skills import search_skill
from backend.shared.python_utils.media_encryption import encrypt_media_variants


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "source",
    ["upload-cache", "generated-cache", "fresh-upload", "generated-cache-loss"],
)
async def test_reverse_search_resolves_media_without_view_and_cleans_temp(
    monkeypatch, version, source
):
    embed_id = str(uuid4())
    image = io.BytesIO()
    Image.new("RGB", (16, 12), "green").save(image, "PNG")
    plaintext = image.getvalue()
    media = encrypt_media_variants({"original": plaintext}, write_version=version)
    content = {
        "files": {
            "original": {
                "s3_key": "private/object",
                "format": "png",
                **media.metadata["original"],
            }
        },
        "vault_wrapped_aes_key": "vault:v1:wrapped",
        "aes_nonce": media.legacy_nonce_b64,
    }
    now = int(time.time())
    fresh = {
        **content,
        "embed_id": embed_id,
        "user_id": "alice",
        "created_at": now - 5,
        "expires_at": now - 5 + 86400,
        "content_type": "image/png",
    }
    owner = {
        "embed_id": embed_id,
        "hashed_user_id": hashlib.sha256(b"alice").hexdigest(),
    }
    cached = (
        fresh
        if source == "upload-cache"
        else {**owner, "encrypted_content": "vault:v1:generated"}
        if source == "generated-cache"
        else None
    )
    rows = (
        [{**owner, "encrypted_content": "client-ciphertext"}]
        if source == "generated-cache-loss"
        else []
    )
    cache = SimpleNamespace(
        get_embed_from_cache=AsyncMock(return_value=cached), set=AsyncMock()
    )
    cms = SimpleNamespace(get_items=AsyncMock(return_value=rows))
    encryption = SimpleNamespace(
        decrypt_with_user_key=AsyncMock(
            side_effect=lambda value, key: encode(content)
            if value == "vault:v1:generated"
            else media.aes_key_b64
        )
    )
    storage = SimpleNamespace(
        environment="development",
        get_file=AsyncMock(return_value=media.payloads["original"]),
    )
    internal = AsyncMock(return_value={"status": "success", "content": fresh})
    skill = object.__new__(search_skill.SearchSkill)
    upload = AsyncMock(
        return_value=("https://temporary.example/image", "temporary/key")
    )
    cleanup = AsyncMock()
    lens = AsyncMock(return_value=([], "Google Lens"))
    monkeypatch.setattr(skill, "_upload_temp_image", upload)
    monkeypatch.setattr(skill, "_delete_temp_image", cleanup)
    monkeypatch.setattr(skill, "_reverse_image_search", lens)

    async def sanitize(*, payload, **kwargs):
        return payload

    monkeypatch.setattr(search_skill, "sanitize_long_text_fields_in_payload", sanitize)
    result = await skill._process_single_request(
        req={"file_path": "photo.png", "count": 3},
        request_id=1,
        secrets_manager=object(),
        file_path_index={"photo.png": embed_id},
        user_vault_key_id="vault-key",
        cache_service=cache,
        reference_context={
            "user_id": "alice",
            "directus_service": cms,
            "encryption_service": encryption,
            "s3_service": storage,
            "internal_api_request": internal,
        },
    )
    assert result == (1, [], "Google Lens", None)
    upload.assert_awaited_once_with(plaintext, "image/png")
    cleanup.assert_awaited_once_with("temporary/key")
    assert (
        storage.get_file.await_args.kwargs["max_bytes"]
        == search_skill.MAX_IMAGE_INPUT_BYTES + 32
    )
    assert lens.await_args.kwargs["count"] == 3
    if source in {"fresh-upload", "generated-cache-loss"}:
        internal.assert_awaited_once()
        assert cache.set.await_args.kwargs["ttl"] <= 86395
    else:
        internal.assert_not_called()
        cms.get_items.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record", [{"user_id": "bob"}, {"user_id": "alice", "expires_at": 1}]
)
async def test_reverse_search_foreign_reference_never_reaches_storage_or_provider(
    record,
):
    embed_id = str(uuid4())
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=record))
    cms = SimpleNamespace(get_items=AsyncMock())
    skill = object.__new__(search_skill.SearchSkill)
    skill._reverse_image_search = AsyncMock()
    skill._upload_temp_image = AsyncMock()
    result = await skill._process_single_request(
        req={"file_path": embed_id},
        request_id=1,
        secrets_manager=object(),
        file_path_index={},
        user_vault_key_id="key",
        cache_service=cache,
        reference_context={
            "user_id": "alice",
            "directus_service": cms,
            "encryption_service": object(),
        },
    )
    assert result[1] == [] and (
        "unavailable" in result[3] or "no longer available" in result[3]
    )
    cms.get_items.assert_not_called()
    skill._upload_temp_image.assert_not_called()
    skill._reverse_image_search.assert_not_called()


@pytest.mark.asyncio
async def test_reverse_provider_failure_still_deletes_private_temp_upload(monkeypatch):
    skill = object.__new__(search_skill.SearchSkill)
    monkeypatch.setattr(
        skill,
        "_resolve_image_input",
        AsyncMock(
            return_value=(
                None,
                SimpleNamespace(content=b"image", mime_type="image/webp"),
            )
        ),
    )
    monkeypatch.setattr(
        skill,
        "_upload_temp_image",
        AsyncMock(return_value=("https://temporary.example/image", "temporary/key")),
    )
    monkeypatch.setattr(
        skill,
        "_reverse_image_search",
        AsyncMock(side_effect=RuntimeError("provider unavailable")),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(skill, "_delete_temp_image", cleanup)
    result = await skill._process_single_request(
        req={"file_path": "photo.png"},
        request_id=1,
        secrets_manager=object(),
        file_path_index={},
        user_vault_key_id="key",
    )
    assert result[1] == [] and result[3] == "provider unavailable"
    cleanup.assert_awaited_once_with("temporary/key")


@pytest.mark.asyncio
async def test_owned_public_search_child_is_reused_without_private_upload():
    embed_id = str(uuid4())
    public_url = "https://images.example/public.jpg"
    record = {
        "embed_id": embed_id,
        "user_id": "alice",
        "encrypted_content": "vault:v1:search-child",
    }
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=record))
    cms = SimpleNamespace(get_items=AsyncMock())
    encryption = SimpleNamespace(
        decrypt_with_user_key=AsyncMock(return_value=encode({"image_url": public_url}))
    )
    skill = object.__new__(search_skill.SearchSkill)
    public, image = await skill._resolve_image_input(
        embed_id,
        {
            "user_id": "alice",
            "user_vault_key_id": "key",
            "cache_service": cache,
            "directus_service": cms,
            "encryption_service": encryption,
        },
    )
    assert public == public_url and image is None
    cms.get_items.assert_not_called()
