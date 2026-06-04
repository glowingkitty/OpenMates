#!/usr/bin/env python3
"""
Validate user-guide to Playwright spec links.

This is the first layer of test-backed user-guide freshness: guides declare
their canonical E2E specs in frontmatter, specs expose docCheckpoint IDs, and
this script verifies that those references remain valid as either side changes.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_GUIDE_ROOT = REPO_ROOT / "docs" / "user-guide"


@dataclass(frozen=True)
class TestedByEntry:
    spec: str
    test: str
    checkpoints: tuple[str, ...]


@dataclass(frozen=True)
class GuideMetadata:
    path: Path
    status: str | None
    tested_by: tuple[TestedByEntry, ...]


def _extract_frontmatter(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return []


def _parse_scalar(line: str, key: str) -> str | None:
    prefix = f"{key}:"
    if line.startswith(prefix):
        return line[len(prefix):].strip() or None
    return None


def _parse_tested_by(frontmatter: list[str]) -> tuple[TestedByEntry, ...]:
    entries: list[TestedByEntry] = []
    in_tested_by = False
    current: dict[str, object] | None = None
    in_checkpoints = False

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        spec = str(current.get("spec") or "")
        test = str(current.get("test") or "")
        checkpoints = tuple(current.get("checkpoints") or ())
        entries.append(TestedByEntry(spec=spec, test=test, checkpoints=checkpoints))
        current = None

    for raw_line in frontmatter:
        if raw_line.startswith("tested_by:"):
            in_tested_by = True
            in_checkpoints = False
            continue

        if not in_tested_by:
            continue

        if raw_line and not raw_line.startswith(" "):
            flush_current()
            in_tested_by = False
            in_checkpoints = False
            continue

        line = raw_line.strip()
        if line.startswith("- spec:"):
            flush_current()
            current = {"spec": line.removeprefix("- spec:").strip(), "checkpoints": []}
            in_checkpoints = False
        elif current is not None and line.startswith("test:"):
            current["test"] = line.removeprefix("test:").strip()
            in_checkpoints = False
        elif current is not None and line.startswith("checkpoints:"):
            in_checkpoints = True
        elif current is not None and in_checkpoints and line.startswith("- "):
            checkpoints = current.setdefault("checkpoints", [])
            assert isinstance(checkpoints, list)
            checkpoints.append(line.removeprefix("- ").strip())

    flush_current()
    return tuple(entries)


def parse_guide(path: Path) -> GuideMetadata:
    frontmatter = _extract_frontmatter(path.read_text(encoding="utf-8"))
    status = None
    for line in frontmatter:
        parsed = _parse_scalar(line, "status")
        if parsed is not None:
            status = parsed
            break
    return GuideMetadata(path=path, status=status, tested_by=_parse_tested_by(frontmatter))


def _spec_contains_test(spec_text: str, test_name: str) -> bool:
    escaped = re.escape(test_name)
    return re.search(rf"\btest\(\s*['\"]{escaped}['\"]", spec_text) is not None


def _spec_contains_checkpoint(spec_text: str, checkpoint_id: str) -> bool:
    escaped = re.escape(checkpoint_id)
    return re.search(rf"\bid\s*:\s*['\"]{escaped}['\"]", spec_text) is not None


def validate_guide(guide: GuideMetadata, require_all: bool) -> list[str]:
    errors: list[str] = []
    rel_guide = guide.path.relative_to(REPO_ROOT)

    if guide.status == "active" and require_all and not guide.tested_by:
        errors.append(f"{rel_guide}: active guide is missing tested_by metadata")
        return errors

    for entry in guide.tested_by:
        if not entry.spec:
            errors.append(f"{rel_guide}: tested_by entry is missing spec")
            continue
        if not entry.test:
            errors.append(f"{rel_guide}: tested_by entry for {entry.spec} is missing test")
        if not entry.checkpoints:
            errors.append(f"{rel_guide}: tested_by entry for {entry.spec} has no checkpoints")

        spec_path = REPO_ROOT / entry.spec
        if not spec_path.exists():
            errors.append(f"{rel_guide}: referenced spec does not exist: {entry.spec}")
            continue

        spec_text = spec_path.read_text(encoding="utf-8")
        if entry.test and not _spec_contains_test(spec_text, entry.test):
            errors.append(f"{rel_guide}: test title not found in {entry.spec}: {entry.test}")
        for checkpoint_id in entry.checkpoints:
            if not _spec_contains_checkpoint(spec_text, checkpoint_id):
                errors.append(
                    f"{rel_guide}: checkpoint not found in {entry.spec}: {checkpoint_id}"
                )

    return errors


def _collect_guides(paths: list[str]) -> list[Path]:
    if paths:
        return [(REPO_ROOT / path).resolve() for path in paths]
    return sorted(USER_GUIDE_ROOT.rglob("*.md"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--guide",
        action="append",
        default=[],
        help="Guide path to validate. May be repeated. Defaults to all linked guides.",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail active guides that do not yet have tested_by metadata.",
    )
    args = parser.parse_args()

    all_errors: list[str] = []
    checked_count = 0
    skipped_count = 0
    for guide_path in _collect_guides(args.guide):
        guide = parse_guide(guide_path)
        if not guide.tested_by and not args.require_all:
            skipped_count += 1
            continue
        checked_count += 1
        all_errors.extend(validate_guide(guide, args.require_all))

    if all_errors:
        print("User-guide spec linkage validation failed:", file=sys.stderr)
        for error in all_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Validated {checked_count} guide(s); skipped {skipped_count} unlinked guide(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
