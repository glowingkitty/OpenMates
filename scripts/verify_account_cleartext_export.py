#!/usr/bin/env python3
"""Verify cleartext Account Export fixtures.

Purpose: guard the user-facing account export contract: readable files, no raw
encrypted storage rows, and no exported key material.
Architecture: deterministic synthetic fixture verifier for the SDK cleartext
boundary spec; real CLI exports use the same forbidden-field policy.
Security: fails on encrypted_* fields, key wrappers, account/object keys, API key
material, and secret-like values.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "chat_key",
    "chat_key_wrappers",
    "embed_key",
    "embed_key_wrappers",
    "encrypted_chat_key",
    "encrypted_master_key",
    "encrypted_plan_key",
    "encrypted_project_key",
    "encrypted_task_key",
    "key_wrappers",
    "master_key",
    "plan_key",
    "private_key",
    "project_key",
    "raw_key",
    "refresh_token",
    "task_key",
    "token_hash",
}

FORBIDDEN_VALUES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}", re.IGNORECASE),
    re.compile(r"#key=[A-Za-z0-9_-]{8,}"),
]

TEXT_SUFFIXES = {".json", ".md", ".txt", ".yml", ".yaml"}
ENCRYPTED_ZIP_MAGIC = b"OMZIP1\n"
SYNTHETIC_EXPORT_PASSWORD = "correct horse battery staple"


def synthetic_files() -> dict[str, str]:
    return {
        "README.md": "# OpenMates Account Export\n\nCleartext user-readable export.\n",
        "manifest.yml": "format: openmates-account-export\nversion: 1\ndomains:\n  chats: included\n  tasks: included\n  plans: included\n  projects: included\n",
        "chats/chat-1.md": "# Launch Chat\n\n### user\nPrepare launch copy.\n",
        "domains/tasks.json": json.dumps({"items": [{"task_id": "task-1", "title": "Prepare launch copy", "description": "Draft email"}]}, indent=2),
        "domains/plans.json": json.dumps({"items": [{"plan_id": "plan-1", "title": "Launch plan", "goal": "Ship safely"}]}, indent=2),
        "domains/projects.json": json.dumps({"items": [{"project_id": "project-1", "name": "Launch", "description": "Marketing launch"}]}, indent=2),
    }


def scan_text(path: str, content: str) -> list[str]:
    failures: list[str] = []
    for field in FORBIDDEN_FIELD_NAMES:
        if re.search(rf"(^|[^A-Za-z0-9_])['\"]?{re.escape(field)}['\"]?\s*:", content, re.IGNORECASE):
            failures.append(f"{path} contains forbidden field {field}")
    if re.search(r"(^|[^A-Za-z0-9_])['\"]?encrypted_[A-Za-z0-9_]*['\"]?\s*:", content, re.IGNORECASE):
        failures.append(f"{path} contains encrypted storage field")
    for pattern in FORBIDDEN_VALUES:
        if pattern.search(content):
            failures.append(f"{path} contains forbidden secret-like value")
    return failures


def validate_entries(entries: dict[str, str]) -> list[str]:
    failures = [f"missing required file {name}" for name in ("README.md", "manifest.yml") if name not in entries]
    if not any(name.startswith("domains/") for name in entries):
        failures.append("missing domains cleartext files")
    for path, content in entries.items():
        if Path(path).suffix.lower() in TEXT_SUFFIXES:
            failures.extend(scan_text(path, content))
    return failures


def encrypt_synthetic_zip(zip_payload: bytes, password: str) -> bytes:
    salt = b"\x05" * 16
    iv = b"\x06" * 12
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    ciphertext_with_tag = AESGCM(key).encrypt(iv, zip_payload, None)
    header = json.dumps({
        "magic": "OMZIP1",
        "version": 1,
        "kdf": "scrypt",
        "cipher": "aes-256-gcm",
        "salt": base64.b64encode(salt).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "tag": base64.b64encode(ciphertext_with_tag[-16:]).decode("utf-8"),
    }).encode("utf-8")
    return ENCRYPTED_ZIP_MAGIC + str(len(header)).encode("utf-8") + b"\n" + header + ciphertext_with_tag[:-16]


def decrypt_synthetic_zip(payload: bytes, password: str) -> bytes:
    if not payload.startswith(ENCRYPTED_ZIP_MAGIC):
        raise ValueError("missing encrypted zip magic")
    header_length_end = payload.find(b"\n", len(ENCRYPTED_ZIP_MAGIC))
    header_length = int(payload[len(ENCRYPTED_ZIP_MAGIC):header_length_end].decode("utf-8"))
    header_start = header_length_end + 1
    header_end = header_start + header_length
    header = json.loads(payload[header_start:header_end].decode("utf-8"))
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.b64decode(header["salt"]),
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return AESGCM(key).decrypt(base64.b64decode(header["iv"]), payload[header_end:] + base64.b64decode(header["tag"]), None)


def verify_synthetic() -> list[str]:
    files = synthetic_files()
    failures = validate_entries(files)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative, content in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        directory_entries = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()}
        failures.extend(validate_entries(directory_entries))
        zip_path = root / "openmates-export.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, content in files.items():
                archive.writestr(relative, content)
        with zipfile.ZipFile(zip_path) as archive:
            zip_entries = {name: archive.read(name).decode("utf-8") for name in archive.namelist() if Path(name).suffix.lower() in TEXT_SUFFIXES}
        failures.extend(validate_entries(zip_entries))
        encrypted_zip = encrypt_synthetic_zip(zip_path.read_bytes(), SYNTHETIC_EXPORT_PASSWORD)
        if b"Launch Chat" in encrypted_zip or b"Prepare launch copy" in encrypted_zip:
            failures.append("password-protected zip container exposes cleartext markers")
        try:
            with zipfile.ZipFile(io.BytesIO(encrypted_zip)):
                failures.append("password-protected zip container can be read as plaintext zip")
        except zipfile.BadZipFile:
            pass
        decrypted_zip = decrypt_synthetic_zip(encrypted_zip, SYNTHETIC_EXPORT_PASSWORD)
        with zipfile.ZipFile(io.BytesIO(decrypted_zip)) as archive:
            encrypted_entries = {name: archive.read(name).decode("utf-8") for name in archive.namelist() if Path(name).suffix.lower() in TEXT_SUFFIXES}
        failures.extend(validate_entries(encrypted_entries))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify cleartext Account Export fixtures.")
    parser.add_argument("--fixture", choices=["synthetic"], required=True)
    args = parser.parse_args()
    failures = verify_synthetic() if args.fixture == "synthetic" else []
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS account cleartext export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
