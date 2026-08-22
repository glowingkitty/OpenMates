#!/usr/bin/env python3
# scripts/import_live_mock_cache.py
# Import recorded live-mock API cache files from an external export directory.
# The Playwright recording flow writes cache JSON inside the running dev API
# container, while agent work usually happens in an isolated worktree. This
# script validates the exported JSON and copies only explicitly named groups into
# backend/apps/ai/testing/api_cache so the generated fixtures are reviewable and
# can be committed through the normal workflow.

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "backend" / "apps" / "ai" / "testing" / "api_cache"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import recorded live-mock cache groups")
    parser.add_argument("source_root", type=Path, help="Directory containing exported cache group folders")
    parser.add_argument("--group", action="append", required=True, help="Cache group folder to import")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without copying")
    return parser.parse_args()


def _validate_cache_file(path: Path, expected_group: str) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc

    actual_group = str(data.get("group_id") or "")
    if actual_group != expected_group:
        raise SystemExit(f"Unexpected group_id in {path}: {actual_group!r} != {expected_group!r}")
    for key in ("fingerprint", "category", "request", "response"):
        if key not in data:
            raise SystemExit(f"Missing {key!r} in {path}")


def main() -> int:
    args = _parse_args()
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise SystemExit(f"Source root does not exist: {source_root}")

    imported_files = 0
    for group in args.group:
        source_group = source_root / group
        if not source_group.is_dir():
            raise SystemExit(f"Missing source group: {source_group}")

        files = sorted(source_group.glob("*/*.json"))
        if not files:
            raise SystemExit(f"No cache JSON files found for group: {group}")
        for path in files:
            _validate_cache_file(path, group)

        destination_group = CACHE_ROOT / group
        print(f"{group}: {len(files)} file(s) -> {destination_group}")
        if not args.dry_run:
            if destination_group.exists():
                shutil.rmtree(destination_group)
            shutil.copytree(source_group, destination_group)
        imported_files += len(files)

    action = "Validated" if args.dry_run else "Imported"
    print(f"{action} {imported_files} live-mock cache file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
