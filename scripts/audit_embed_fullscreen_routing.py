#!/usr/bin/env python3
"""Audit unified embed fullscreen routing ownership.

This guard prevents regressions to the pre-controller architecture where many
components independently dispatched `embedfullscreen` events, wrote active embed
hash state, or resolved child-parent fullscreen targets. The only allowed owner
for those operations is `embedFullscreenController.ts`, with the legacy resolver
method remaining in `embedStore.ts` as a delegated lookup implementation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

EVENT_PATTERN = re.compile(
    r"new\s+CustomEvent\(\s*[\"']embedfullscreen[\"']|dispatchEvent\(\s*new\s+CustomEvent\(\s*[\"']embedfullscreen[\"']"
)
ACTIVE_WRITE_PATTERN = re.compile(r"activeEmbedStore\.(?:setActiveEmbed|clearActiveEmbed)\(")
TARGET_RESOLVER_PATTERN = re.compile(r"\.resolveFullscreenTarget\(")

ALLOWED_EVENT_FILES = {
    "frontend/packages/ui/src/services/embedFullscreenController.ts",
}

ALLOWED_ACTIVE_WRITE_FILES = {
    "frontend/packages/ui/src/services/embedFullscreenController.ts",
    "frontend/packages/ui/src/stores/activeEmbedStore.ts",
}

ALLOWED_TARGET_RESOLVER_FILES = {
    "frontend/packages/ui/src/services/embedFullscreenController.ts",
    "frontend/packages/ui/src/services/embedStore.ts",
    "frontend/packages/ui/src/services/__tests__/embedFullscreenController.test.ts",
}

INCLUDE_SUFFIXES = {".svelte", ".ts"}
EXCLUDED_PARTS = {"node_modules", ".svelte-kit", "dist", "build"}


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in FRONTEND.rglob("*"):
        if path.suffix not in INCLUDE_SUFFIXES:
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def find_violations(pattern: re.Pattern[str], allowed_files: set[str]) -> list[str]:
    violations: list[str] = []
    for path in iter_source_files():
        relative = rel(path)
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            if relative in allowed_files:
                continue
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{relative}:{line}: {match.group(0)}")
    return violations


def main() -> int:
    failures = {
        "direct embedfullscreen event creation": find_violations(
            EVENT_PATTERN,
            ALLOWED_EVENT_FILES,
        ),
        "direct active embed route writes": find_violations(
            ACTIVE_WRITE_PATTERN,
            ALLOWED_ACTIVE_WRITE_FILES,
        ),
        "fullscreen target resolver bypasses": find_violations(
            TARGET_RESOLVER_PATTERN,
            ALLOWED_TARGET_RESOLVER_FILES,
        ),
    }

    has_failures = False
    for label, violations in failures.items():
        if not violations:
            continue
        has_failures = True
        print(f"FAIL: {label}", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)

    if has_failures:
        print(
            "\nRoute fullscreen opens through frontend/packages/ui/src/services/embedFullscreenController.ts.",
            file=sys.stderr,
        )
        return 1

    print("PASS: embed fullscreen routing ownership is centralized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
