# backend/tests/test_encrypted_embed_images.py
#
# Contract tests for worker-side image inputs. The resolver must recover a
# persisted encrypted embed after its cache entry expires without putting image
# bytes or keys into task payloads.

import base64
import io

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.shared.python_utils.encrypted_embed_images import EncryptedEmbedImageError, resolve_encrypted_image_embed
from backend.shared.python_utils.media_encryption import MEDIA_ENCRYPTION_V2


class _FakeCache:
    def __init__(self) -> None:
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value


class _FakeDirectus:
    class _EmbedMethods:
        async def get_embed_by_id(self, embed_id):
            assert embed_id == "embed-1"
            return {"embed_id": embed_id, "encrypted_content": "embed-ciphertext"}

    def __init__(self):
        self.embed = self._EmbedMethods()


class _BrokenCache(_FakeCache):
    async def get(self, _key):
        raise RuntimeError("cache unavailable")


class _MissingDirectus:
    class _EmbedMethods:
        async def get_embed_by_id(self, _embed_id):
            return None

    def __init__(self):
        self.embed = self._EmbedMethods()


class _UnexpectedDirectus:
    class _EmbedMethods:
        async def get_embed_by_id(self, _embed_id):
            raise AssertionError("valid upload-cache records must not fall back to Directus")

    def __init__(self):
        self.embed = self._EmbedMethods()


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_cache_read_error_falls_back_to_directus_embed_methods() -> None:
    nonce = b"\x22" * 12
    plaintext = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=_BrokenCache(),
        directus_service=_FakeDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        decode_toon=lambda _plaintext: {
            "vault_wrapped_aes_key": "wrapped-aes-key",
            "aes_nonce": base64.b64encode(nonce).decode(),
            "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
        },
    )

    assert resolved.content == plaintext


class _LegacyFakeDirectus:
    async def get_embed_by_id(self, embed_id):
        assert embed_id == "embed-1"
        return {"embed_id": embed_id, "encrypted_content": "embed-ciphertext"}


class _FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext, _vault_key_id):
        if ciphertext == "embed-ciphertext":
            return "decoded-toon"
        if ciphertext == "wrapped-aes-key":
            return base64.b64encode(b"\x11" * 32).decode()
        raise AssertionError(f"unexpected ciphertext: {ciphertext}")


class _FakeS3:
    def __init__(self, encrypted):
        self.encrypted = encrypted

    async def get_file(self, *, bucket_name, object_key):
        assert bucket_name == "chatfiles"
        assert object_key == "inputs/chair.png"
        return self.encrypted


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_cache_miss_falls_back_to_directus_and_recaches_encrypted_embed() -> None:
    nonce = b"\x22" * 12
    plaintext = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)
    cache = _FakeCache()

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=cache,
        directus_service=_FakeDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        decode_toon=lambda _plaintext: {
            "vault_wrapped_aes_key": "wrapped-aes-key",
            "aes_nonce": base64.b64encode(nonce).decode(),
            "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
        },
    )

    assert resolved.content == plaintext
    assert resolved.mime_type == "image/png"
    assert "embed:embed-1" in cache.values


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_upload_cache_image_decrypts_without_chat_embed_persistence() -> None:
    nonce = b"\x22" * 12
    plaintext = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)
    cache = _FakeCache()
    cache.values["embed:embed-1"] = __import__("json").dumps(
        {
            "embed_id": "embed-1",
            "user_id": "user-1",
            "content_type": "image/png",
            "vault_wrapped_aes_key": "wrapped-aes-key",
            "aes_nonce": base64.b64encode(nonce).decode(),
            "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
        }
    )

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=cache,
        directus_service=_FakeDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        decode_toon=lambda _plaintext: pytest.fail("upload-cache records must not decode chat TOON"),
    )

    assert resolved.content == plaintext
    assert resolved.mime_type == "image/png"


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_decoded_cache_record_decrypts_without_directus_fallback() -> None:
    nonce = b"\x22" * 12
    plaintext = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)
    cache = _FakeCache()
    cache.values["embed:embed-1"] = {
        "embed_id": "embed-1",
        "user_id": "user-1",
        "content_type": "image/png",
        "vault_wrapped_aes_key": "wrapped-aes-key",
        "aes_nonce": base64.b64encode(nonce).decode(),
        "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
    }

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=cache,
        directus_service=_UnexpectedDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        decode_toon=lambda _plaintext: pytest.fail("upload-cache records must not decode chat TOON"),
    )

    assert resolved.content == plaintext
    assert resolved.mime_type == "image/png"


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_preloaded_upload_record_decrypts_when_worker_cache_misses() -> None:
    nonce = b"\x22" * 12
    plaintext = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=_BrokenCache(),
        directus_service=_MissingDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        preloaded_records={
            "embed-1": {
                "embed_id": "embed-1",
                "vault_wrapped_aes_key": "wrapped-aes-key",
                "aes_nonce": base64.b64encode(nonce).decode(),
                "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
            }
        },
        decode_toon=lambda _plaintext: pytest.fail("preloaded upload records must not decode chat TOON"),
    )

    assert resolved.content == plaintext
    assert resolved.mime_type == "image/png"


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_preloaded_v2_image_decrypts_without_top_level_nonce() -> None:
    nonce = b"\x23" * 12
    plaintext = b"\x89PNG\r\n\x1a\nv2-chair-image"
    encrypted = nonce + AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1",
        user_vault_key_id="vault-key-1",
        cache_client=_BrokenCache(),
        directus_service=_MissingDirectus(),
        encryption_service=_FakeEncryption(),
        s3_service=_FakeS3(encrypted),
        preloaded_records={
            "embed-1": {
                "embed_id": "embed-1",
                "vault_wrapped_aes_key": "wrapped-aes-key",
                "files": {
                    "original": {
                        "s3_key": "inputs/chair.png",
                        "format": "png",
                        "encryption": MEDIA_ENCRYPTION_V2,
                    }
                },
            }
        },
        decode_toon=lambda _plaintext: pytest.fail("preloaded upload records must not decode chat TOON"),
    )

    assert resolved.content == plaintext
    assert resolved.mime_type == "image/png"


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
@pytest.mark.parametrize("actual_format,expected_mime", [
    ("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp"),
])
@pytest.mark.parametrize("nonce_prefixed", [False, True])
async def test_provider_image_mime_matches_decrypted_container_despite_legacy_label(
    actual_format, expected_mime, nonce_prefixed,
) -> None:
    from PIL import Image

    source = io.BytesIO()
    Image.new("RGB", (16, 12), "green").save(source, actual_format)
    plaintext = source.getvalue()
    nonce = b"\x23" * 12
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, plaintext, None)
    variant = {"s3_key": "inputs/chair.png", "format": "webp"}
    if nonce_prefixed:
        encrypted = nonce + encrypted
        variant["encryption"] = MEDIA_ENCRYPTION_V2

    resolved = await resolve_encrypted_image_embed(
        embed_id="embed-1", user_vault_key_id="vault-key-1",
        cache_client=_FakeCache(), directus_service=_UnexpectedDirectus(),
        encryption_service=_FakeEncryption(), s3_service=_FakeS3(encrypted),
        preloaded_records={"embed-1": {
            "vault_wrapped_aes_key": "wrapped-aes-key",
            "aes_nonce": base64.b64encode(nonce).decode(),
            "files": {"original": variant},
        }},
    )
    assert resolved.content == plaintext
    assert resolved.mime_type == expected_mime


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_declared_image_format_cannot_turn_unknown_plaintext_into_provider_input() -> None:
    nonce = b"\x23" * 12
    encrypted = AESGCM(b"\x11" * 32).encrypt(nonce, b"not an image container", None)
    with pytest.raises(EncryptedEmbedImageError, match="format is not supported"):
        await resolve_encrypted_image_embed(
            embed_id="embed-1", user_vault_key_id="vault-key-1",
            cache_client=_FakeCache(), directus_service=_UnexpectedDirectus(),
            encryption_service=_FakeEncryption(), s3_service=_FakeS3(encrypted),
            preloaded_records={"embed-1": {
                "vault_wrapped_aes_key": "wrapped-aes-key",
                "aes_nonce": base64.b64encode(nonce).decode(),
                "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
            }},
        )
