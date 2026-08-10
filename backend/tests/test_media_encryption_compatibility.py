"""Backend media encryption reader compatibility contracts.

Frozen legacy fixtures must remain readable without metadata mutation. R1 also
adds read support for the explicit nonce-prefixed v2 marker while every writer
remains on the legacy format through the rollout manifest.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.shared.python_utils.media_encryption import (
    MEDIA_ENCRYPTION_V2,
    decrypt_media_payload,
    encrypt_media_variants,
)
from backend.shared.python_utils.generated_assets.service import index_generated_asset


FIXTURE_PATH = Path(__file__).parent / "fixtures/encryption_compatibility/legacy_layouts.json"


def test_frozen_legacy_media_uses_unchanged_top_level_nonce_fallback() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    legacy_media = fixtures["legacy_media"]
    original = deepcopy(legacy_media)

    for media in legacy_media:
        key = base64.b64decode(media["aes_key_b64"])
        for variant in media["variants"].values():
            plaintext = decrypt_media_payload(
                encrypted_data=base64.b64decode(variant["ciphertext_b64"]),
                aes_key=key,
                variant=variant,
                legacy_nonce_b64=media["aes_nonce"],
            )
            assert plaintext.decode("utf-8") == variant["plaintext"]

    assert legacy_media == original


def test_explicit_v2_marker_reads_nonce_prefixed_payload() -> None:
    key = bytes(range(32))
    nonce = bytes(range(12))
    plaintext = b"generated_image:v2-preview"
    encrypted_data = nonce + AESGCM(key).encrypt(nonce, plaintext, None)

    assert decrypt_media_payload(
        encrypted_data=encrypted_data,
        aes_key=key,
        variant={"encryption": MEDIA_ENCRYPTION_V2},
        legacy_nonce_b64=None,
    ) == plaintext


def test_unknown_media_encryption_marker_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported media encryption"):
        decrypt_media_payload(
            encrypted_data=b"not-decrypted",
            aes_key=bytes(range(32)),
            variant={"encryption": "unknown-version"},
            legacy_nonce_b64=None,
        )


@pytest.mark.parametrize("key", [b"short", b"long" * 9])
def test_invalid_media_key_size_fails_before_decryption(key: bytes) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        decrypt_media_payload(
            encrypted_data=b"not-decrypted",
            aes_key=key,
            variant={},
            legacy_nonce_b64=base64.b64encode(bytes(range(12))).decode("ascii"),
        )


def test_v2_writer_uses_distinct_prefixed_nonces_for_every_variant() -> None:
    random_values = iter(
        [
            bytes(range(32)),
            b"\x01" * 12,
            b"\x02" * 12,
            b"\x03" * 12,
        ]
    )

    encrypted = encrypt_media_variants(
        {"original": b"original", "full": b"full", "preview": b"preview"},
        write_version=2,
        random_bytes=lambda _length: next(random_values),
    )

    prefixes = {payload[:12] for payload in encrypted.payloads.values()}
    assert prefixes == {b"\x01" * 12, b"\x02" * 12, b"\x03" * 12}
    assert encrypted.legacy_nonce_b64 is None
    assert all(metadata == {"encryption": MEDIA_ENCRYPTION_V2} for metadata in encrypted.metadata.values())
    for variant, payload in encrypted.payloads.items():
        assert decrypt_media_payload(
            encrypted_data=payload,
            aes_key=encrypted.aes_key,
            variant=encrypted.metadata[variant],
            legacy_nonce_b64=None,
        ) == {"original": b"original", "full": b"full", "preview": b"preview"}[variant]


def test_v2_writer_rejects_duplicate_nonce_before_returning_payloads() -> None:
    random_values = iter([bytes(range(32)), b"\x01" * 12, b"\x01" * 12])

    with pytest.raises(RuntimeError, match="duplicate media nonce"):
        encrypt_media_variants(
            {"original": b"original", "preview": b"preview"},
            write_version=2,
            random_bytes=lambda _length: next(random_values),
        )


class _IndexDirectus:
    def __init__(self) -> None:
        self.record = None

    async def create_item(self, collection: str, record: dict) -> tuple[bool, None]:
        assert collection == "upload_files"
        self.record = record
        return True, None

    async def get_user_fields_direct(self, _user_id: str, _fields: list[str]) -> dict:
        return {"storage_used_bytes": 0}

    async def update_user(self, _user_id: str, _fields: dict) -> None:
        return None


class _IndexTask:
    def __init__(self) -> None:
        self._directus_service = _IndexDirectus()


@pytest.mark.asyncio
async def test_v2_generated_asset_index_omits_raw_key() -> None:
    task = _IndexTask()
    files_metadata = {
        "original": {
            "s3_key": "generated/original.bin",
            "size_bytes": 42,
            "encryption": MEDIA_ENCRYPTION_V2,
        }
    }

    assert await index_generated_asset(
        task,
        user_id="user-1",
        embed_id="embed-1",
        media_type="image",
        files_metadata=files_metadata,
        s3_base_url="https://s3.example.test",
        aes_key_b64=base64.b64encode(bytes(range(32))).decode("ascii"),
        nonce_b64="",
        vault_wrapped_aes_key="vault:v1:wrapped",
        created_at=1,
        content_hash_source=b"ciphertext",
        original_filename="image.png",
        content_type="image/png",
        log_prefix="[test]",
    )

    assert task._directus_service.record is not None
    assert "aes_key" not in task._directus_service.record
    assert task._directus_service.record["vault_wrapped_aes_key"] == "vault:v1:wrapped"
