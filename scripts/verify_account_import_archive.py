#!/usr/bin/env python3
"""Verify Account Import evidence and encrypted persistence boundaries.

Purpose: provide a deterministic guard for Account Import V1 evidence files and
backend persistence code.
Architecture: docs/specs/account-import-v1/spec.yml.
Security: blocks raw import message markers in captured artifacts and direct
plaintext-shaped Directus writes to private chat/message collections.
Privacy: intended for synthetic/redacted evidence only; never requires real
provider exports or user content.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DIRECTUS_WRITE_RE = re.compile(
    r"\b(?:create_item|update_item|update_item_if_version)\s*\(\s*['\"](?:chats|messages)['\"]"
)
PLAINTEXT_PRIVATE_FIELD_RE = re.compile(
    r"['\"](?:assistant_category|category|content|draft|model_name|pii_mappings|sender_name|summary|thinking|thinking_content|thinking_signature|thinking_tokens|title|user_id)['\"]\s*:"
)
DEFAULT_FORBIDDEN_MARKERS = [
    "Synthetic CLI import user message.",
    "Synthetic CLI import assistant message.",
    "Synthetic limits message.",
]
ACCOUNT_IMPORT_SOURCE_FILES = [
    ROOT / "backend/core/api/app/services/account_import_service.py",
    ROOT / "backend/core/api/app/routes/account_imports.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Account Import V1 artifacts do not leak plaintext import content.")
    parser.add_argument("--import-log", action="append", default=[], help="Captured CLI/import evidence file to scan.")
    parser.add_argument("--web-artifacts", action="append", default=[], help="Directory or file of web import artifacts to scan.")
    parser.add_argument("--forbid-marker", action="append", default=[], help="Additional exact marker that must not appear in artifacts.")
    parser.add_argument("--forbid-plaintext-directus-fields", action="store_true", help="Scan backend source for direct plaintext-shaped chat/message writes.")
    args = parser.parse_args()

    failures: list[str] = []
    artifact_paths = collect_artifacts(args.import_log, args.web_artifacts)
    markers = [*DEFAULT_FORBIDDEN_MARKERS, *args.forbid_marker]
    for artifact_path in artifact_paths:
      failures.extend(scan_artifact(artifact_path, markers))

    if args.forbid_plaintext_directus_fields:
      failures.extend(scan_backend_plaintext_writes())

    if failures:
      for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
      return 1

    print("PASS: Account Import artifacts and persistence boundaries are clean.")
    return 0


def collect_artifacts(import_logs: list[str], web_artifacts: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw_path in [*import_logs, *web_artifacts]:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_dir():
            paths.extend(child for child in path.rglob("*") if child.is_file())
        else:
            paths.append(path)
    return paths


def scan_artifact(path: Path, markers: list[str]) -> list[str]:
    if not path.exists():
        return [f"artifact not found: {path}"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"could not read artifact {path}: {error}"]
    return [f"{path} contains forbidden raw import marker: {marker}" for marker in markers if marker and marker in text]


def scan_backend_plaintext_writes() -> list[str]:
    failures: list[str] = []
    for path in ACCOUNT_IMPORT_SOURCE_FILES:
        if not path.exists():
            failures.append(f"expected account import source file is missing: {path.relative_to(ROOT)}")
            continue
        relative = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8", errors="replace")
        if not DIRECTUS_WRITE_RE.search(source):
            continue
        if PLAINTEXT_PRIVATE_FIELD_RE.search(source):
            failures.append(f"{relative} directly writes plaintext-shaped fields to Directus chats/messages")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
