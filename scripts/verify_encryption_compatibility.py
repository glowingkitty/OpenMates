#!/usr/bin/env python3
"""Verify frozen encryption compatibility fixtures without external effects.

Hashes immutable synthetic/existing fixtures, decrypts their authenticated
legacy ciphertext, and confirms protected reader branches remain present.
This local-only gate performs no network calls or durable writes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "backend/tests/fixtures/encryption_compatibility"
MEDIA_KINDS = {"upload_image", "generated_image", "vectorized_image", "remotion_output"}
INVOICE_FIELDS = {"encrypted_amount", "encrypted_s3_object_key", "encrypted_aes_key", "encrypted_filename", "aes_nonce"}
IMMUTABLE_PATHS = {
    "backend/tests/fixtures/encryption_compatibility/legacy_layouts.json",
    "backend/tests/fixtures/chat_completion_recovery_vectors.json",
    "backend/core/api/app/services/domain_security_allowed.encrypted",
    "backend/core/api/app/services/domain_security_patterns.encrypted",
    "backend/core/api/app/services/domain_security_restricted.encrypted",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def repo_path(raw: str) -> Path:
    path = (ROOT / raw).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {raw}")
    return path


def nonce(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(decode_b64(value, label)) != 12:
        raise ValueError(f"{label} must be a 12-byte base64 nonce")


def decode_b64(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{label} must be valid base64") from exc


def decrypt_prefixed(blob_b64: Any, key: bytes, label: str) -> bytes:
    blob = decode_b64(blob_b64, label)
    if len(blob) < 28:
        raise ValueError(f"{label} must contain nonce[12] || ciphertext || tag[16]")
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def fnv1a_fingerprint(key: bytes) -> bytes:
    value = 0x811C9DC5
    for byte in key:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value.to_bytes(4, "big")


def fixture_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    keys = data.get("keys", {})
    content_key = decode_b64(keys.get("content_key_b64"), "keys.content_key_b64")
    wrapping_key = decode_b64(keys.get("wrapping_key_b64"), "keys.wrapping_key_b64")
    if len(content_key) != 32 or len(wrapping_key) != 32:
        return ["fixture keys must each contain exactly 32 bytes"]

    chat = data.get("chat", {})
    if set(chat) != {"format_a", "format_b", "format_c", "format_d"}:
        return ["chat fixtures must contain exactly formats A-D"]
    decoded = {name: decode_b64(value.get("blob_b64"), f"chat.{name}.blob_b64") for name, value in chat.items()}
    if decoded["format_a"][:2] != b"OM" or len(decoded["format_a"]) < 34:
        errors.append("Format A layout changed")
    elif decoded["format_a"][2:6] != fnv1a_fingerprint(content_key):
        errors.append("Format A key fingerprint changed")
    elif AESGCM(content_key).decrypt(decoded["format_a"][6:18], decoded["format_a"][18:], None).decode() != chat["format_a"].get("plaintext"):
        errors.append("Format A no longer decrypts to its frozen plaintext")
    if decoded["format_b"][:2] == b"OM" or len(decoded["format_b"]) < 28:
        errors.append("Format B legacy layout changed")
    elif decrypt_prefixed(chat["format_b"]["blob_b64"], content_key, "chat.format_b").decode() != chat["format_b"].get("plaintext"):
        errors.append("Format B no longer decrypts to its frozen plaintext")
    if len(decoded["format_c"]) != 60:
        errors.append("Format C must remain nonce[12] || key[32] || tag[16]")
    elif decrypt_prefixed(chat["format_c"]["blob_b64"], wrapping_key, "chat.format_c") != decode_b64(chat["format_c"].get("plaintext_key_b64"), "chat.format_c.plaintext_key_b64"):
        errors.append("Format C no longer unwraps its frozen chat key")
    if decoded["format_d"][:2] == b"OM" or len(decoded["format_d"]) < 28:
        errors.append("Format D layout changed")
    elif decrypt_prefixed(chat["format_d"]["blob_b64"], wrapping_key, "chat.format_d").decode() != chat["format_d"].get("plaintext"):
        errors.append("Format D no longer decrypts to its frozen plaintext")

    media = data.get("legacy_media", [])
    if {item.get("kind") for item in media} != MEDIA_KINDS:
        errors.append("legacy media corpus is incomplete")
    for item in media:
        nonce(item.get("aes_nonce"), f"{item.get('kind')}.aes_nonce")
        item_key = decode_b64(item.get("aes_key_b64"), f"{item.get('kind')}.aes_key_b64")
        item_nonce = decode_b64(item.get("aes_nonce"), f"{item.get('kind')}.aes_nonce")
        if len(item.get("variants", {})) < 2:
            errors.append(f"{item.get('kind')} needs representative variants")
        for name, variant in item.get("variants", {}).items():
            if "aes_nonce" in variant or "encryption" in variant:
                errors.append(f"{item.get('kind')}.{name} no longer represents global-nonce media")
            ciphertext = decode_b64(variant.get("ciphertext_b64"), f"{item.get('kind')}.{name}.ciphertext_b64")
            if not variant.get("s3_key") or len(ciphertext) < 16:
                errors.append(f"{item.get('kind')}.{name} layout is incomplete")
            elif AESGCM(item_key).decrypt(item_nonce, ciphertext, None).decode() != variant.get("plaintext"):
                errors.append(f"{item.get('kind')}.{name} no longer decrypts to its frozen plaintext")

    invoice = data.get("legacy_invoice", {})
    if not INVOICE_FIELDS.issubset(invoice):
        errors.append("legacy invoice fields changed")
    else:
        nonce(invoice["aes_nonce"], "legacy_invoice.aes_nonce")
        ciphertext = decode_b64(invoice.get("object_ciphertext_b64"), "legacy_invoice.object_ciphertext_b64")
        if len(ciphertext) < 16:
            errors.append("legacy invoice object ciphertext layout changed")
        else:
            plaintext = AESGCM(decode_b64(invoice.get("aes_key_b64"), "legacy_invoice.aes_key_b64")).decrypt(
                decode_b64(invoice["aes_nonce"], "legacy_invoice.aes_nonce"), ciphertext, None
            )
            if plaintext.decode() != invoice.get("plaintext"):
                errors.append("legacy invoice object no longer decrypts to its frozen plaintext")
    link = data.get("legacy_short_link", {})
    expected_kdf = {"name": "PBKDF2", "iterations": 200000, "hash": "SHA-256", "salt_prefix": "omts-v1-"}
    if len(link.get("token", "")) != 8 or len(link.get("short_key", "")) != 6 or link.get("kdf") != expected_kdf:
        errors.append("legacy six-character short-link contract changed")
    encrypted_url = decode_b64(link.get("encrypted_url_b64"), "legacy_short_link.encrypted_url_b64")
    if len(encrypted_url) < 28:
        errors.append("legacy short-link ciphertext layout changed")
    else:
        derived_key = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=(expected_kdf["salt_prefix"] + link["token"]).encode(),
            iterations=expected_kdf["iterations"],
        ).derive(link["short_key"].encode())
        if decrypt_prefixed(link["encrypted_url_b64"], derived_key, "legacy_short_link.encrypted_url_b64").decode() != link.get("plaintext"):
            errors.append("legacy short link no longer decrypts to its frozen URL")
    sessions = data.get("legacy_cli_sessions", [])
    if {item.get("tier") for item in sessions} != {"plaintext", "keychain", "encrypted"}:
        errors.append("legacy CLI session tiers changed")
    for item in sessions:
        session = item.get("session", {})
        if not {"sessionId", "hashedEmail"}.issubset(session):
            errors.append(f"legacy CLI {item.get('tier')} identity fields changed")
        if item.get("tier") == "plaintext" and "masterKeyStorage" in session:
            errors.append("legacy plaintext CLI fixture must omit masterKeyStorage")
        if item.get("tier") == "plaintext" and not session.get("masterKeyExportedB64"):
            errors.append("legacy plaintext CLI fixture lost its inline key field")
        if item.get("tier") == "keychain" and session.get("masterKeyStorage") != "keychain":
            errors.append("legacy keychain CLI fixture changed")
        if item.get("tier") == "encrypted" and not session.get("masterKeyEncrypted"):
            errors.append("legacy encrypted CLI fixture changed")
        if item.get("tier") == "encrypted" and session.get("masterKeyEncrypted"):
            decrypted_key = decrypt_prefixed(
                session["masterKeyEncrypted"],
                decode_b64(keys.get("cli_fixture_machine_key_b64"), "keys.cli_fixture_machine_key_b64"),
                "legacy_cli_sessions.encrypted.masterKeyEncrypted",
            )
            if decrypted_key.decode() != session.get("plaintextMasterKeyB64"):
                errors.append("legacy encrypted CLI fixture no longer authenticates")
    return errors


def recovery_errors() -> list[str]:
    from backend.shared.python_utils.chat_completion_recovery import open_recovery_envelope

    data = load_json(ROOT / "backend/tests/fixtures/chat_completion_recovery_vectors.json")
    vectors = data.get("vectors", [])
    if data.get("version") != 1 or not vectors:
        return ["recovery v1 fixture missing"]
    vector = vectors[0]
    envelope = vector.get("envelope", {})
    if set(envelope) != {"v", "epk", "nonce", "ciphertext"} or envelope.get("v") != 1:
        return ["recovery envelope v1 fields changed"]
    nonce(envelope["nonce"] + "==", "recovery.envelope.nonce")
    plaintext = open_recovery_envelope(
        envelope,
        recovery_private_key=vector["recovery_private_key"],
        owner_id=vector["owner_id"],
        chat_id=vector["chat_id"],
        turn_id=vector["turn_id"],
        job_id=vector["job_id"],
        assistant_message_id=vector["assistant_message_id"],
        key_version=vector["key_version"],
    )
    if plaintext.decode() != vector.get("plaintext"):
        return ["recovery envelope no longer decrypts to its frozen plaintext"]
    return []


def domain_policy_errors() -> list[str]:
    from backend.core.api.app.services.domain_security import DomainSecurityService

    service = DomainSecurityService()
    errors: list[str] = []
    for name in ("allowed", "patterns", "restricted"):
        path = ROOT / f"backend/core/api/app/services/domain_security_{name}.encrypted"
        plaintext, _ = service._load_encrypted_file(path, f"legacy {name} policy")
        if not plaintext.strip():
            errors.append(f"legacy {name} domain policy decrypts to empty content")
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        manifest = load_json(FIXTURES / "manifest.json")
        data = load_json(FIXTURES / "legacy_layouts.json")
        if manifest.get("schema_version") != 1 or data.get("schema_version") != 1:
            errors.append("fixture schemas must remain version 1")
        immutable_files = manifest.get("immutable_files", [])
        if {entry.get("path") for entry in immutable_files if isinstance(entry, dict)} != IMMUTABLE_PATHS:
            errors.append("immutable fixture manifest coverage changed")
        for entry in immutable_files:
            path = repo_path(entry["path"])
            contents = path.read_bytes()
            actual = hashlib.sha256(contents).hexdigest()
            if actual != entry.get("sha256"):
                errors.append(f"immutable hash mismatch: {entry['path']} expected={entry.get('sha256')} actual={actual}")
            if "domain_security_" in entry["path"] and not contents.startswith(b"gAAAA"):
                errors.append(f"legacy domain-policy Fernet layout changed: {entry['path']}")
        errors.extend(fixture_errors(data))
        errors.extend(recovery_errors())
        errors.extend(domain_policy_errors())
        for guard in manifest.get("reader_guards", []):
            source = repo_path(guard["path"]).read_text(encoding="utf-8")
            for fragment in guard["required"]:
                if fragment not in source:
                    errors.append(f"legacy reader missing from {guard['path']}: {fragment!r}")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    if errors:
        print("Encryption compatibility verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Encryption compatibility verification passed (5 immutable files, 10 reader guards).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
