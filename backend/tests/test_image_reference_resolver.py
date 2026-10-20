"""Direct app-skill references preserve ownership, media versions and expiry."""

# contract-test-file: infrastructure
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.shared.python_utils.image_reference_resolver import (
    ImageReferenceUnavailable,
    image_reference_id,
    load_owned_image_record,
)
from backend.shared.python_utils.encrypted_embed_images import (
    decode_image_record_content,
    EncryptedEmbedImageError,
)
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable


def context(record=None, rows=None):
    return (
        SimpleNamespace(
            get_embed_from_cache=AsyncMock(return_value=record), set=AsyncMock()
        ),
        SimpleNamespace(get_items=AsyncMock(return_value=rows or [])),
    )


def owned(**extra):
    return {"hashed_user_id": hashlib.sha256(b"alice").hexdigest(), **extra}


@pytest.mark.asyncio
async def test_owner_filtered_authoritative_lookup_recovers_and_warms_only_metadata():
    embed_id = str(uuid4())
    record = owned(embed_id=embed_id, encrypted_content="vault:v1:fixture")
    cache, cms = context(rows=[record])
    assert (
        await load_owned_image_record(
            embed_id=embed_id, user_id="alice", cache_client=cache, directus_service=cms
        )
        == record
    )
    kwargs = cms.get_items.await_args.kwargs
    assert kwargs["params"]["filter[embed_id][_eq]"] == embed_id
    assert kwargs["params"]["filter[hashed_user_id][_eq]"] == owned()["hashed_user_id"]
    assert kwargs["no_cache"] is True
    assert cache.set.await_args.args == (f"embed:{embed_id}", record)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record", [owned(user_id="bob"), owned(expires_at=1), {"user_id": "bob"}]
)
async def test_foreign_or_expired_cache_is_denied_before_authoritative_lookup(record):
    cache, cms = context(record=record)
    with pytest.raises(ImageReferenceUnavailable):
        await load_owned_image_record(
            embed_id=str(uuid4()),
            user_id="alice",
            cache_client=cache,
            directus_service=cms,
        )
    cms.get_items.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["upload", "generated"])
async def test_client_ciphertext_or_missing_embed_recovers_only_original_fresh_window(
    origin,
):
    embed_id = str(uuid4())
    now = int(time.time())
    cache, cms = context(
        rows=[owned(embed_id=embed_id, encrypted_content="client-only-ciphertext")]
        if origin == "generated"
        else []
    )
    fresh = {
        "embed_id": embed_id,
        "user_id": "alice",
        "created_at": now - 10,
        "expires_at": now - 10 + 86400,
        "content_type": "image/png",
        "files": {"original": {"s3_key": "private"}},
        "vault_wrapped_aes_key": "vault:v1:key",
    }
    internal = AsyncMock(return_value={"status": "success", "content": fresh})
    result = await load_owned_image_record(
        embed_id=embed_id,
        user_id="alice",
        cache_client=cache,
        directus_service=cms,
        request_internal=internal,
    )
    assert result == fresh and result["expires_at"] == now - 10 + 86400
    assert cache.set.await_args.kwargs["ttl"] <= 86390
    internal.assert_awaited_once_with(
        "POST",
        "internal/uploads/resolve-image",
        payload={"embed_id": embed_id, "user_id": "alice"},
    )


@pytest.mark.asyncio
async def test_old_generated_client_ciphertext_stays_unavailable_without_key_recovery():
    cache, cms = context(rows=[owned(encrypted_content="client-only-ciphertext")])
    with pytest.raises(FreshUploadImageUnavailable):
        await load_owned_image_record(
            embed_id=str(uuid4()),
            user_id="alice",
            cache_client=cache,
            directus_service=cms,
        )
    cache.set.assert_not_called()
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock())
    with pytest.raises(EncryptedEmbedImageError, match="processing window"):
        await decode_image_record_content(
            record={"encrypted_content": "client-only-ciphertext"},
            user_vault_key_id="key",
            encryption_service=encryption,
        )
    encryption.decrypt_with_user_key.assert_not_called()


def test_reference_mapping_does_not_guess_filenames():
    embed_id = str(uuid4())
    assert image_reference_id("photo.png", {"photo.png": embed_id}) == embed_id
    assert image_reference_id(embed_id, {}) == embed_id
    with pytest.raises(ImageReferenceUnavailable):
        image_reference_id("photo.png", {})


@pytest.mark.asyncio
async def test_raw_cache_json_and_cache_outage_both_preserve_fallback_contract():
    embed_id = str(uuid4())
    record = owned(embed_id=embed_id, encrypted_content="vault:v1:fixture")
    raw_cache = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps(record)), set=AsyncMock()
    )
    cms = SimpleNamespace(get_items=AsyncMock(return_value=[record]))
    assert (
        await load_owned_image_record(
            embed_id=embed_id,
            user_id="alice",
            cache_client=raw_cache,
            directus_service=cms,
        )
        == record
    )
    cms.get_items.assert_not_called()
    raw_cache.get.side_effect = RuntimeError("PRIVATE CACHE ERROR")
    assert (
        await load_owned_image_record(
            embed_id=embed_id,
            user_id="alice",
            cache_client=raw_cache,
            directus_service=cms,
        )
        == record
    )
    cms.get_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_authoritative_foreign_row_fails_closed_even_if_backend_ignores_filter():
    cache, cms = context(
        rows=[{"user_id": "bob", "encrypted_content": "vault:v1:foreign"}]
    )
    internal = AsyncMock()
    with pytest.raises(ImageReferenceUnavailable):
        await load_owned_image_record(
            embed_id=str(uuid4()),
            user_id="alice",
            cache_client=cache,
            directus_service=cms,
            request_internal=internal,
        )
    internal.assert_not_called()
    cache.set.assert_not_called()
