# backend/tests/test_images_generate_reference_images.py
#
# Contract tests for the references of images.generate (feature.app-skill.images-generate).
# A generated graphic is client-encrypted once the chat stored it, so a later
# change must read it through the owner-scoped media index, and a reference
# that cannot be loaded must fail the request instead of being skipped.

from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.apps.images.tasks import reference_images
from backend.apps.images.tasks.reference_images import (
    ReferenceImageUnavailable,
    load_reference_images,
    remember_vector_script,
)
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable
from backend.shared.python_utils.media_encryption import MEDIA_WRITE_VERSION_V2, encrypt_media_variants

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0H10V10Z"/></svg>'
PREVIEW = b"RIFF\x00\x00\x00\x00WEBPpreview"
SCRIPT = "def build_svg():\n    return '<svg/>'\n"
EMBED_ID = "3e1733df-1aea-5245-a3d0-b9a7179d9b48"
USER_ID = "user-1"
WRAPPED = "vault:v1:wrapped-media-key"


class Redis:
    def __init__(self, records: dict[str, Any]) -> None:
        self.store = {key: json.dumps(value) for key, value in records.items()}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if not isinstance(value, str):
            raise TypeError("raw redis stores strings")
        self.store[key] = value
        return True


class S3:
    environment = "development"

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.reads: list[str] = []

    async def get_file(self, *, bucket_name: str, object_key: str) -> bytes:
        self.reads.append(object_key)
        return self.payloads[object_key]


class Vault:
    def __init__(self, aes_key_b64: str) -> None:
        self.aes_key_b64 = aes_key_b64

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str | None:
        if ciphertext == WRAPPED:
            return self.aes_key_b64
        if ciphertext.startswith("vault:script:"):
            return ciphertext.removeprefix("vault:script:")
        raise AssertionError("client ciphertext must never be sent to Vault")

    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]:
        return f"vault:script:{plaintext}", "v1"


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    encrypted = encrypt_media_variants(
        {"original": SVG.encode(), "preview": PREVIEW}, write_version=MEDIA_WRITE_VERSION_V2,
    )
    created = int(time.time()) - 60
    index = {
        "embed_id": EMBED_ID, "user_id": USER_ID, "type": "image", "status": "finished",
        "created_at": created, "expires_at": created + 86400, "filename": "tail.svg",
        "content_type": "image/svg+xml", "s3_base_url": "https://chatfiles.example",
        "files": {
            "original": {"s3_key": "u/original.svg", "format": "svg", **encrypted.metadata["original"]},
            "preview": {"s3_key": "u/preview.webp", "format": "webp", **encrypted.metadata["preview"]},
        },
        "aes_nonce": encrypted.legacy_nonce_b64, "vault_wrapped_aes_key": WRAPPED,
    }
    # What the chat stored: the client-encrypted durable record only.
    stored = {
        "embed_id": EMBED_ID, "hashed_user_id": hashlib.sha256(USER_ID.encode()).hexdigest(),
        "status": "finished", "encryption_mode": "client", "encrypted_content": "clientciphertext",
    }
    cache = Redis({})
    internal = AsyncMock(return_value={"status": "success", "content": index})
    monkeypatch.setattr(reference_images, "_request_internal", internal)
    task = SimpleNamespace(
        _cache_service=SimpleNamespace(client=_resolved(cache)),
        _directus_service=SimpleNamespace(get_items=AsyncMock(return_value=[stored])),
        _encryption_service=Vault(encrypted.aes_key_b64),
    )
    s3 = S3({"u/original.svg": encrypted.payloads["original"], "u/preview.webp": encrypted.payloads["preview"]})
    return {"task": task, "s3": s3, "cache": cache, "internal": internal}


class _resolved:
    """Awaitable attribute like CacheService.client, usable more than once."""

    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):
        async def _get() -> Any:
            return self.value
        return _get().__await__()


async def _load(world: dict[str, Any], *, vector: bool = True) -> Any:
    return await load_reference_images(
        world["task"], embed_ids=[EMBED_ID], user_id=USER_ID, user_vault_key_id="vault-key-1",
        s3_service=world["s3"], want_vector_sources=vector, log_prefix="[test]",
    )


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
@pytest.mark.asyncio
async def test_stored_generated_graphic_is_read_as_source_through_the_media_index(monkeypatch) -> None:
    world = _world(monkeypatch)
    loaded = await _load(world)
    assert loaded.svg_sources == [SVG]
    assert loaded.images == [(PREVIEW, "image/webp")]
    assert loaded.script_sources == []
    world["internal"].assert_awaited_once_with(
        "POST", "internal/uploads/resolve-image", payload={"embed_id": EMBED_ID, "user_id": USER_ID},
    )


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
@pytest.mark.asyncio
async def test_pixel_output_uses_only_the_raster_preview_of_a_vector_reference(monkeypatch) -> None:
    world = _world(monkeypatch)
    loaded = await _load(world, vector=False)
    assert loaded.images == [(PREVIEW, "image/webp")] and loaded.svg_sources == []
    assert world["s3"].reads == ["u/preview.webp"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel,images-generate.vector.script-engine
@pytest.mark.asyncio
async def test_script_made_graphic_returns_its_stored_generator(monkeypatch) -> None:
    world = _world(monkeypatch)
    await remember_vector_script(world["task"], embed_id=EMBED_ID, script=SCRIPT, vault_key_id="vault-key-1")
    loaded = await _load(world)
    assert loaded.script_sources == [SCRIPT] and loaded.svg_sources == [SVG]


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
@pytest.mark.asyncio
async def test_unavailable_reference_fails_the_request_instead_of_being_skipped(monkeypatch) -> None:
    world = _world(monkeypatch)
    world["internal"].side_effect = FreshUploadImageUnavailable("not in the current processing window")
    with pytest.raises(ReferenceImageUnavailable):
        await _load(world)
    assert world["s3"].reads == []


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
@pytest.mark.asyncio
async def test_missing_file_fails_the_request(monkeypatch) -> None:
    world = _world(monkeypatch)
    world["s3"].payloads["u/original.svg"] = b""
    with pytest.raises(ReferenceImageUnavailable):
        await _load(world)
