"""Shared media ciphertext reader compatibility.

Legacy media stores one external AES-GCM nonce at the record level. Media v2
uses an explicit marker and prefixes each ciphertext with its own 12-byte nonce.
Readers support both formats while unknown markers fail closed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import yaml

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


AES_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
AES_GCM_TAG_BYTES = 16
MEDIA_ENCRYPTION_V2 = "aes-gcm-nonce-prefixed-v1"
MEDIA_WRITE_VERSION_LEGACY = 1
MEDIA_WRITE_VERSION_V2 = 2
ROLLOUT_CONFIG_PATH = Path(
    os.getenv(
        "MEDIA_ENCRYPTION_ROLLOUT_PATH",
        str(Path(__file__).resolve().parents[3] / "config/media_encryption_rollout.yml"),
    )
)


@dataclass(frozen=True)
class EncryptedMediaVariants:
    """One key and the encrypted payload/metadata for a media variant set."""

    aes_key: bytes
    aes_key_b64: str
    payloads: dict[str, bytes]
    metadata: dict[str, dict[str, str]]
    legacy_nonce_b64: str | None


def _random_exact(random_bytes: Callable[[int], bytes], length: int, label: str) -> bytes:
    value = random_bytes(length)
    if not isinstance(value, bytes) or len(value) != length:
        raise RuntimeError(f"media {label} randomness failed")
    return value


def encrypt_media_variants(
    plaintext_by_variant: Mapping[str, bytes],
    *,
    write_version: int,
    random_bytes: Callable[[int], bytes] = os.urandom,
) -> EncryptedMediaVariants:
    """Encrypt all variants before any caller publishes objects or metadata."""
    if not plaintext_by_variant:
        raise ValueError("media variants are required")
    if write_version not in {MEDIA_WRITE_VERSION_LEGACY, MEDIA_WRITE_VERSION_V2}:
        raise ValueError(f"unsupported media write version: {write_version}")

    aes_key = _random_exact(random_bytes, AES_KEY_BYTES, "key")
    aesgcm = AESGCM(aes_key)
    payloads: dict[str, bytes] = {}
    metadata: dict[str, dict[str, str]] = {}

    if write_version == MEDIA_WRITE_VERSION_LEGACY:
        nonce = _random_exact(random_bytes, AES_GCM_NONCE_BYTES, "nonce")
        for variant, plaintext in plaintext_by_variant.items():
            payloads[variant] = aesgcm.encrypt(nonce, plaintext, None)
            metadata[variant] = {}
        legacy_nonce_b64 = base64.b64encode(nonce).decode("ascii")
    else:
        seen_nonces: set[bytes] = set()
        for variant, plaintext in plaintext_by_variant.items():
            nonce = _random_exact(random_bytes, AES_GCM_NONCE_BYTES, "nonce")
            if nonce in seen_nonces:
                raise RuntimeError("duplicate media nonce")
            seen_nonces.add(nonce)
            payloads[variant] = nonce + aesgcm.encrypt(nonce, plaintext, None)
            metadata[variant] = {"encryption": MEDIA_ENCRYPTION_V2}
        legacy_nonce_b64 = None

    return EncryptedMediaVariants(
        aes_key=aes_key,
        aes_key_b64=base64.b64encode(aes_key).decode("ascii"),
        payloads=payloads,
        metadata=metadata,
        legacy_nonce_b64=legacy_nonce_b64,
    )


def validate_rollout_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail closed when a checked-in media writer rollout is incomplete."""
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported media rollout schema_version")
    if manifest.get("v2_format") != MEDIA_ENCRYPTION_V2:
        raise ValueError("media rollout v2_format is invalid")

    write_version = manifest.get("write_version")
    if write_version == MEDIA_WRITE_VERSION_LEGACY:
        return
    if write_version != MEDIA_WRITE_VERSION_V2:
        raise ValueError("media rollout write_version is invalid")

    minimum_commit = manifest.get("minimum_r1_commit")
    if not isinstance(minimum_commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", minimum_commit):
        raise ValueError("media rollout minimum_r1_commit is invalid")
    if not manifest.get("activated_at"):
        raise ValueError("media rollout activated_at is missing")

    evidence = manifest.get("r1_evidence")
    required = evidence.get("required") if isinstance(evidence, Mapping) else None
    passed = evidence.get("passed") if isinstance(evidence, Mapping) else None
    if not isinstance(required, list) or not required or not isinstance(passed, list):
        raise ValueError("media rollout R1 evidence is invalid")
    if set(passed) != set(required):
        raise ValueError("media rollout R1 evidence is incomplete")


def load_media_write_version(path: Path = ROLLOUT_CONFIG_PATH) -> int:
    """Load and validate the atomic checked-in media writer version."""
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("media rollout manifest is invalid")
    validate_rollout_manifest(manifest)
    return int(manifest["write_version"])


def decrypt_media_payload(
    *,
    encrypted_data: bytes,
    aes_key: bytes,
    variant: Mapping[str, Any],
    legacy_nonce_b64: str | None,
) -> bytes:
    """Decrypt one legacy or explicitly marked v2 media payload."""
    if len(aes_key) != AES_KEY_BYTES:
        raise ValueError("media AES key must be 32 bytes")

    marker = variant.get("encryption")
    if marker == MEDIA_ENCRYPTION_V2:
        if len(encrypted_data) < AES_GCM_NONCE_BYTES + AES_GCM_TAG_BYTES:
            raise ValueError("nonce-prefixed media ciphertext is too short")
        nonce = encrypted_data[:AES_GCM_NONCE_BYTES]
        ciphertext = encrypted_data[AES_GCM_NONCE_BYTES:]
    elif marker in (None, ""):
        nonce_b64 = variant.get("aes_nonce") or legacy_nonce_b64
        if not isinstance(nonce_b64, str) or not nonce_b64:
            raise ValueError("legacy media nonce is missing")
        try:
            nonce = base64.b64decode(nonce_b64, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("legacy media nonce is invalid") from exc
        if len(nonce) != AES_GCM_NONCE_BYTES:
            raise ValueError("legacy media nonce must be 12 bytes")
        ciphertext = encrypted_data
    else:
        raise ValueError(f"unsupported media encryption marker: {marker}")

    return AESGCM(aes_key).decrypt(nonce, ciphertext, None)
