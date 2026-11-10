# backend/tests/test_design_embroidery_vector_source.py
#
# Contract tests for reading the SVG source of design.embroidery
# (feature.app-skill.design-embroidery). A generated SVG child is delivered
# client-encrypted only, so once the client persisted it the cache holds the
# client-encrypted durable record. The source must then come from the
# owner-scoped generated-asset index, and stay fail-closed when that index is
# foreign or past its processing window.

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.encrypted_embed_vectors import (
    ORIGIN_GENERATED,
    VectorSourceError,
    resolve_vector_source_embed,
)
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable
from backend.shared.python_utils.media_encryption import MEDIA_WRITE_VERSION_V2, encrypt_media_variants

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0H10V10Z"/></svg>'
EMBED_ID = "faa3617d-131c-5774-8146-cb7cb0000001"
USER_ID = "user-1"
OWNER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
S3_KEY = "user-1/1_ab_original.svg"


class RawRedis:
    """The raw async Redis client the media worker passes (get / set with ex)."""

    def __init__(self, records: dict[str, Any]) -> None:
        self.store = {key: json.dumps(value) for key, value in records.items()}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if not isinstance(value, str):
            raise TypeError("raw redis stores strings")
        self.store[key] = value
        return True


class Directus:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.get_items = AsyncMock(return_value=rows)


class S3:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.reads: list[str] = []

    async def get_file(self, *, bucket_name: str, object_key: str) -> bytes:
        self.reads.append(object_key)
        return self.payload


class Vault:
    def __init__(self, aes_key_b64: str) -> None:
        self.aes_key_b64 = aes_key_b64
        self.decrypted: list[str] = []

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        self.decrypted.append(ciphertext)
        if ciphertext != "vault:v1:wrapped-media-key":
            raise AssertionError("only the Vault-wrapped media key may be decrypted")
        return self.aes_key_b64


def _client_encrypted_record() -> dict[str, Any]:
    # Shape seen on dev after the CLI persisted the child: Directus fields, client ciphertext.
    return {
        "id": "row-1", "embed_id": EMBED_ID, "hashed_user_id": OWNER_HASH, "status": "finished",
        "encryption_mode": "client", "encrypted_content": "4EOoa72yclientciphertext",
        "parent_embed_id": "bfef9322-0000-0000-0000-000000000000",
    }


def _world(*, index_owner: str = USER_ID, created_at: int | None = None) -> dict[str, Any]:
    encrypted = encrypt_media_variants({"original": SVG.encode()}, write_version=MEDIA_WRITE_VERSION_V2)
    created = int(time.time()) - 60 if created_at is None else created_at
    content = {
        "embed_id": EMBED_ID, "user_id": index_owner, "type": "image", "status": "finished",
        "created_at": created, "expires_at": created + 86400, "filename": "fox-logo.svg",
        "content_type": "image/svg+xml", "s3_base_url": "https://chatfiles.example",
        "files": {"original": {"s3_key": S3_KEY, "format": "svg", "mime_type": "image/svg+xml",
                               **encrypted.metadata["original"]}},
        "aes_nonce": encrypted.legacy_nonce_b64, "vault_wrapped_aes_key": "vault:v1:wrapped-media-key",
    }
    return {
        "cache": RawRedis({f"embed:{EMBED_ID}": _client_encrypted_record()}),
        "directus": Directus([_client_encrypted_record()]),
        "internal": AsyncMock(return_value={"status": "success", "content": content}),
        "s3": S3(encrypted.payloads["original"]),
        "vault": Vault(encrypted.aes_key_b64),
    }


async def _resolve(world: dict[str, Any], **overrides: Any) -> Any:
    return await resolve_vector_source_embed(
        embed_id=EMBED_ID, user_id=overrides.get("user_id", USER_ID), user_vault_key_id="vault-key-1",
        cache_client=world["cache"], directus_service=world["directus"],
        encryption_service=world["vault"], s3_service=world["s3"],
        request_internal=world["internal"],
    )


# contract-test: supporting surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_persisted_generated_svg_resolves_through_owner_scoped_asset_index() -> None:
    world = _world()
    source = await _resolve(world)
    assert source.svg == SVG and source.origin == ORIGIN_GENERATED and source.label == "Fox logo"
    world["internal"].assert_awaited_once_with(
        "POST", "internal/uploads/resolve-image", payload={"embed_id": EMBED_ID, "user_id": USER_ID},
    )
    params = world["directus"].get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == OWNER_HASH
    # The client ciphertext is never sent to Vault; only the wrapped media key is.
    assert world["vault"].decrypted == ["vault:v1:wrapped-media-key"]
    # The cache now holds the recovered metadata only, so the next call skips Directus.
    cached = json.loads(world["cache"].store[f"embed:{EMBED_ID}"])
    assert "encrypted_content" not in cached and SVG not in json.dumps(cached)
    again = _world()
    again["cache"] = world["cache"]
    assert (await _resolve(again)).svg == SVG
    again["directus"].get_items.assert_not_called()


# contract-test: supporting surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_expired_processing_window_fails_closed_without_reading_storage() -> None:
    world = _world()
    world["internal"].side_effect = FreshUploadImageUnavailable("not in the current processing window")
    with pytest.raises(VectorSourceError):
        await _resolve(world)
    assert world["s3"].reads == [] and world["vault"].decrypted == []


# contract-test: supporting surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_foreign_owner_index_is_rejected_without_reading_storage() -> None:
    world = _world(index_owner="someone-else")
    with pytest.raises(VectorSourceError):
        await _resolve(world)
    assert world["s3"].reads == [] and world["vault"].decrypted == []


# contract-test: supporting surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_foreign_cached_record_is_rejected_before_any_lookup() -> None:
    world = _world()
    world["cache"] = RawRedis({f"embed:{EMBED_ID}": {**_client_encrypted_record(), "hashed_user_id": "f" * 64}})
    with pytest.raises(VectorSourceError):
        await _resolve(world)
    world["directus"].get_items.assert_not_called()
    world["internal"].assert_not_called()
