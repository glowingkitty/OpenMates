#!/usr/bin/env python3
"""Audit CSS text-color token usage in frontend files.

The primary token is a gradient and is valid for backgrounds, but it is invalid
for the CSS `color` property. Browsers then fall back to inherited text color,
which caused low-contrast share URLs in light mode.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


INVALID_TEXT_PRIMARY_RE = re.compile(r"(?<![-\w])color\s*:\s*var\(--color-primary\)")


@dataclass(frozen=True)
class CssColorIssue:
    path: Path
    line_number: int
    line: str


def audit_text_color_tokens(paths: list[Path]) -> list[CssColorIssue]:
    issues: list[CssColorIssue] = []
    for path in paths:
        if not path.is_file():
            issues.append(CssColorIssue(path, 0, "file not found"))
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if INVALID_TEXT_PRIMARY_RE.search(line):
                issues.append(CssColorIssue(path, line_number, line.strip()))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit CSS text colors that incorrectly use gradient-only tokens."
    )
    parser.add_argument("paths", nargs="+", help="Svelte/CSS files to audit.")
    args = parser.parse_args(argv)

    issues = audit_text_color_tokens([Path(path) for path in args.paths])
    if not issues:
        return 0

    print("[css-color-tokens] Invalid text color token usage:", file=sys.stderr)
    for issue in issues:
        location = str(issue.path) if issue.line_number == 0 else f"{issue.path}:{issue.line_number}"
        print(f"  - {location}: {issue.line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
