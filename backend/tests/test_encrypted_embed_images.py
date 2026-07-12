# backend/tests/test_encrypted_embed_images.py
#
# Contract tests for worker-side image inputs. The resolver must recover a
# persisted encrypted embed after its cache entry expires without putting image
# bytes or keys into task payloads.

import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.shared.python_utils.encrypted_embed_images import resolve_encrypted_image_embed


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
