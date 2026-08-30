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
import re
import shutil
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "backend" / "apps" / "ai" / "testing" / "api_cache"
GROUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import recorded live-mock cache groups")
    parser.add_argument("source_root", type=Path, help="Directory containing exported cache group folders")
    parser.add_argument("--group", action="append", required=True, help="Cache group folder to import")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without copying")
    parser.add_argument(
        "--passed-real-run",
        action="store_true",
        help="Confirm the candidate came from a passing real scenario",
    )
    parser.add_argument(
        "--passed-zero-call-replay",
        action="store_true",
        help="Confirm the same candidate passed replay with zero provider calls",
    )
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


def _validate_groups(source_root: Path, groups: list[str]) -> dict[str, tuple[Path, list[Path]]]:
    """Validate every requested group before filesystem promotion begins."""
    validated: dict[str, tuple[Path, list[Path]]] = {}
    for group in groups:
        if not GROUP_NAME_PATTERN.fullmatch(group):
            raise SystemExit(f"Invalid cache group name: {group!r}")
        source_group = source_root / group
        if not source_group.is_dir():
            raise SystemExit(f"Missing source group: {source_group}")
        files = sorted(source_group.rglob("*.json"))
        if not files:
            raise SystemExit(f"No cache JSON files found for group: {group}")
        for path in files:
            _validate_cache_file(path, group)
        validated[group] = (source_group, files)
    return validated


def _promote_groups(validated: dict[str, tuple[Path, list[Path]]]) -> None:
    """Stage candidate groups and replace canonical groups with rollback backups."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    promoted: list[str] = []
    try:
        for group, (source_group, _) in validated.items():
            stage = CACHE_ROOT / f".{group}.staging-{transaction_id}"
            shutil.copytree(source_group, stage)
            staged[group] = stage

        for group, stage in staged.items():
            destination = CACHE_ROOT / group
            backup = CACHE_ROOT / f".{group}.backup-{transaction_id}"
            if destination.exists():
                destination.rename(backup)
                backups[group] = backup
            stage.rename(destination)
            promoted.append(group)
    except OSError as exc:
        for group in reversed(promoted):
            destination = CACHE_ROOT / group
            stage = staged[group]
            if destination.exists():
                destination.rename(stage)
            if group in backups:
                backups[group].rename(destination)
        for group, backup in backups.items():
            destination = CACHE_ROOT / group
            if not destination.exists() and backup.exists():
                backup.rename(destination)
        raise SystemExit(f"Could not promote live-mock cache groups: {exc}") from exc
    finally:
        for stage in staged.values():
            if stage.exists():
                shutil.rmtree(stage)

    for backup in backups.values():
        shutil.rmtree(backup)


def main() -> int:
    args = _parse_args()
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise SystemExit(f"Source root does not exist: {source_root}")

    validated = _validate_groups(source_root, args.group)
    imported_files = 0
    for group, (_, files) in validated.items():
        destination_group = CACHE_ROOT / group
        print(f"{group}: {len(files)} file(s) -> {destination_group}")
        imported_files += len(files)

    if not args.dry_run:
        if not args.passed_real_run or not args.passed_zero_call_replay:
            raise SystemExit(
                "Promotion requires --passed-real-run and --passed-zero-call-replay"
            )
        _promote_groups(validated)

    action = "Validated" if args.dry_run else "Imported"
    print(f"{action} {imported_files} live-mock cache file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
