#!/usr/bin/env python3
"""Generate a static Apple/web parity inventory.

This script is intentionally Linux-safe: it does not call Xcode, compile Swift,
or require frontend dependencies. It extracts stable web test IDs, Apple
accessibility identifiers, and counterpart paths so parity work can start before
Mac simulator verification is available. The output is factual inventory only;
product priority stays in docs/architecture/apple/*.md.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "test-results" / "apple-parity-inventory.json"

WEB_SPEC_ROOT = REPO_ROOT / "frontend" / "apps" / "web_app" / "tests"
APPLE_SOURCE_ROOT = REPO_ROOT / "apple" / "OpenMates" / "Sources"
COUNTERPARTS_PATH = REPO_ROOT / "apple" / "SVELTE_SWIFT_COUNTERPARTS.md"

GET_BY_TEST_ID_RE = re.compile(r"getByTestId\(\s*['\"]([^'\"]+)['\"]\s*\)")
DATA_TEST_ID_RE = re.compile(r"data-testid\s*=\s*['\"]([^'\"]+)['\"]")
LOCATOR_DATA_TEST_ID_RE = re.compile(r"\[data-testid=['\"]([^'\"]+)['\"]\]")
ACCESSIBILITY_ID_RE = re.compile(r"accessibilityIdentifier\(\s*\"([^\"]+)\"\s*\)")
MARKDOWN_PATH_RE = re.compile(r"`([^`]+\.(?:svelte|css|ts|swift))`")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


def extract_web_test_ids() -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for path in sorted(WEB_SPEC_ROOT.rglob("*.spec.ts")):
        text = read_text(path)
        ids = []
        ids.extend(GET_BY_TEST_ID_RE.findall(text))
        ids.extend(DATA_TEST_ID_RE.findall(text))
        ids.extend(LOCATOR_DATA_TEST_ID_RE.findall(text))
        if ids:
            by_file[repo_path(path)] = unique_sorted(ids)
    return by_file


def extract_apple_accessibility_ids() -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for path in sorted(APPLE_SOURCE_ROOT.rglob("*.swift")):
        ids = ACCESSIBILITY_ID_RE.findall(read_text(path))
        if ids:
            by_file[repo_path(path)] = unique_sorted(ids)
    return by_file


def extract_counterpart_paths() -> dict[str, object]:
    if not COUNTERPARTS_PATH.exists():
        return {
            "path": repo_path(COUNTERPARTS_PATH),
            "exists": False,
            "web_paths": [],
            "swift_paths": [],
            "missing_paths": [],
        }

    text = read_text(COUNTERPARTS_PATH)
    paths = unique_sorted(MARKDOWN_PATH_RE.findall(text))
    web_paths = [p for p in paths if p.endswith((".svelte", ".css", ".ts"))]
    swift_paths = [p for p in paths if p.endswith(".swift")]
    missing_paths = [p for p in paths if not (REPO_ROOT / p).exists()]
    return {
        "path": repo_path(COUNTERPARTS_PATH),
        "exists": True,
        "web_paths": web_paths,
        "swift_paths": swift_paths,
        "missing_paths": missing_paths,
    }


def flatten_values(mapping: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for items in mapping.values():
        values.extend(items)
    return unique_sorted(values)


def build_inventory() -> dict[str, object]:
    web_ids_by_file = extract_web_test_ids()
    apple_ids_by_file = extract_apple_accessibility_ids()
    web_ids = flatten_values(web_ids_by_file)
    apple_ids = flatten_values(apple_ids_by_file)
    shared_ids = sorted(set(web_ids) & set(apple_ids))

    web_components = sorted((REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "components").rglob("*.svelte"))
    web_routes = sorted((REPO_ROOT / "frontend" / "apps" / "web_app" / "src" / "routes").rglob("*.svelte"))
    apple_feature_swift = sorted((REPO_ROOT / "apple" / "OpenMates" / "Sources" / "Features").rglob("*.swift"))
    apple_app_swift = sorted((REPO_ROOT / "apple" / "OpenMates" / "Sources" / "App").rglob("*.swift"))

    return {
        "counts": {
            "web_svelte_components": len(web_components),
            "web_svelte_routes": len(web_routes),
            "web_playwright_specs": len(list(WEB_SPEC_ROOT.rglob("*.spec.ts"))),
            "web_unique_test_ids": len(web_ids),
            "apple_feature_swift_files": len(apple_feature_swift),
            "apple_app_swift_files": len(apple_app_swift),
            "apple_unique_accessibility_ids": len(apple_ids),
            "shared_ids": len(shared_ids),
        },
        "web_test_ids": {
            "all": web_ids,
            "by_file": web_ids_by_file,
        },
        "apple_accessibility_ids": {
            "all": apple_ids,
            "by_file": apple_ids_by_file,
        },
        "shared_ids": shared_ids,
        "web_ids_missing_on_apple": sorted(set(web_ids) - set(apple_ids)),
        "apple_ids_not_used_by_web_specs": sorted(set(apple_ids) - set(web_ids)),
        "counterparts": extract_counterpart_paths(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Apple/web parity inventory JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--check", action="store_true", help="Do not write; fail if output is stale or missing.")
    args = parser.parse_args()

    inventory = build_inventory()
    serialized = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output

    if args.check:
        if not output.exists():
            print(f"Missing parity inventory: {output}")
            return 1
        current = read_text(output)
        if current != serialized:
            print(f"Stale parity inventory: {output}")
            return 1
        print(f"Parity inventory is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    print(f"Wrote {output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
