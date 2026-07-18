#!/usr/bin/env python3
"""Verify Account Export V1 archive safety and layout.

Purpose: provide a deterministic local gate for CLI/web account export archives.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: fails if text files contain reusable credential/key field names or
secret-like values that must never be exported.
Privacy: validates personal export layout only; team export is separate.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import zipfile


FORBIDDEN_FIELD_NAMES = {
    "access_token",
    "api_key",
    "anonymous_encrypted_chat_key",
    "backup_code_hash",
    "chat_key",
    "chat_key_wrappers",
    "credential_secret",
    "device_key",
    "embed_key",
    "embed_key_wrappers",
    "encrypted_chat_key",
    "encrypted_embed_key",
    "encrypted_master_key",
    "encrypted_plan_key",
    "encrypted_project_key",
    "encrypted_task_key",
    "encrypted_workflow_secret_key",
    "key_wrappers",
    "lookup_hash",
    "master_key",
    "plan_key",
    "password_hash",
    "private_key",
    "project_key",
    "raw_key",
    "refresh_token",
    "share_key",
    "shared_encrypted_chat_key",
    "signing_secret",
    "task_key",
    "token_hash",
    "totp_seed",
    "webhook_secret",
    "workflow_secret_key",
}

FORBIDDEN_FIELD_PATTERN = re.compile(
    rf"(^|[^A-Za-z0-9_])['\"]?({'|'.join(re.escape(field) for field in sorted(FORBIDDEN_FIELD_NAMES))})['\"]?\s*:",
    re.IGNORECASE,
)

FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}", re.IGNORECASE),
    re.compile(r"#key=[A-Za-z0-9_-]{8,}"),
]

TEXT_SUFFIXES = {".json", ".md", ".txt", ".yml", ".yaml"}


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    content: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an OpenMates Account Export V1 archive.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", dest="zip_path", help="Path to an export ZIP file.")
    source.add_argument("--dir", dest="dir_path", help="Path to an unpacked export directory.")
    parser.add_argument("--layout-v1", action="store_true", help="Validate required V1 files and chat pairs.")
    parser.add_argument("--forbid-secrets", action="store_true", help="Scan text files for forbidden secret fields and values.")
    args = parser.parse_args()

    entries = read_zip(Path(args.zip_path)) if args.zip_path else read_directory(Path(args.dir_path))
    failures: list[str] = []
    if args.layout_v1:
        failures.extend(validate_layout(entries))
    if args.forbid_secrets:
        failures.extend(validate_secret_scan(entries))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS account export archive")
    return 0


def read_zip(path: Path) -> list[ArchiveEntry]:
    if not path.is_file():
        raise SystemExit(f"ZIP not found: {path}")
    with zipfile.ZipFile(path) as archive:
        entries: list[ArchiveEntry] = []
        for name in archive.namelist():
            if name.endswith("/"):
                entries.append(ArchiveEntry(name=name.rstrip("/"), content=None))
                continue
            suffix = Path(name).suffix.lower()
            content = archive.read(name).decode("utf-8") if suffix in TEXT_SUFFIXES else None
            entries.append(ArchiveEntry(name=name, content=content))
        return entries


def read_directory(path: Path) -> list[ArchiveEntry]:
    if not path.is_dir():
        raise SystemExit(f"Directory not found: {path}")
    entries: list[ArchiveEntry] = []
    for item in path.rglob("*"):
        if item.is_dir():
            continue
        relative = item.relative_to(path).as_posix()
        content = item.read_text(encoding="utf-8") if item.suffix.lower() in TEXT_SUFFIXES else None
        entries.append(ArchiveEntry(name=relative, content=content))
    return entries


def validate_layout(entries: list[ArchiveEntry]) -> list[str]:
    names = {entry.name for entry in entries}
    failures = [f"missing required file {name}" for name in ["README.md", "manifest.yml", "export-report.yml"] if name not in names]
    if "checksums.sha256" in names:
        failures.append("checksums.sha256 must not exist in Account Export V1")
    if not any(name.startswith("domains/") and name.endswith(".json") for name in names):
        failures.append("missing domains/*.json export data")

    chat_markdown = {Path(name).stem for name in names if name.startswith("chats/") and name.endswith(".md")}
    chat_yaml = {Path(name).stem for name in names if name.startswith("chats/") and (name.endswith(".yml") or name.endswith(".yaml"))}
    missing_markdown = sorted(chat_yaml - chat_markdown)
    missing_yaml = sorted(chat_markdown - chat_yaml)
    failures.extend(f"chat {chat_id} has YAML but no Markdown" for chat_id in missing_markdown)
    failures.extend(f"chat {chat_id} has Markdown but no YAML" for chat_id in missing_yaml)
    return failures


def validate_secret_scan(entries: list[ArchiveEntry]) -> list[str]:
    failures: list[str] = []
    for entry in entries:
        if entry.content is None:
            continue
        for field in sorted({match.group(2).lower() for match in FORBIDDEN_FIELD_PATTERN.finditer(entry.content)}):
            failures.append(f"{entry.name} contains forbidden secret field {field}")
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(entry.content):
                failures.append(f"{entry.name} contains forbidden secret-like value")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
