#!/usr/bin/env python3
"""
Vercel ignored-build preflight for dependency update previews.

Runs before Vercel installs dependencies. Dependabot can raise dependency
engine floors before the Vercel project runtime has been upgraded, which makes
preview deployments fail during `pnpm install` and spam failure notifications.
This script returns Vercel's ignore exit code only for that known class.

Architecture context: docs/contributing/guides/git-and-deployment.md
Tests: scripts/tests/test_vercel_ignore_build.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


BUILD_CONTINUE = 1
BUILD_IGNORE = 0
DEFAULT_VERCEL_NODE_MAJOR = 24
DEPENDABOT_NPM_BRANCH_PREFIX = "dependabot/npm_and_yarn/"
INLINE_ENGINE_PATTERN = re.compile(
    r"engines:\s*\{\s*node:\s*(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<bare>[^}\n]+))\s*\}"
)
BLOCK_ENGINE_PATTERN = re.compile(
    r"engines:\s*\n\s+node:\s*(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<bare>[^\n#]+))"
)
VERSION_CONDITION_PATTERN = re.compile(r"(>=|>|<=|<|=)?\s*v?(\d+)(?:\.\d+)?(?:\.\d+)?(?:\.x|\.X|\.\*)?")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_node_major(value: str | None) -> int:
    if not value:
        return DEFAULT_VERCEL_NODE_MAJOR
    match = re.search(r"\d+", value)
    if not match:
        return DEFAULT_VERCEL_NODE_MAJOR
    return int(match.group(0))


def _condition_allows_major(operator: str, required_major: int, current_major: int) -> bool:
    if operator == ">=":
        return current_major >= required_major
    if operator == ">":
        return current_major > required_major
    if operator == "<=":
        return current_major <= required_major
    if operator == "<":
        return current_major < required_major
    return current_major == required_major


def _alternative_allows_major(alternative: str, current_major: int) -> bool:
    alternative = alternative.strip()
    if not alternative:
        return True

    if alternative.startswith("^") or alternative.startswith("~"):
        match = re.search(r"\d+", alternative)
        return bool(match and current_major == int(match.group(0)))

    conditions = VERSION_CONDITION_PATTERN.findall(alternative)
    if not conditions:
        return True

    for operator, required in conditions:
        if not _condition_allows_major(operator or "=", int(required), current_major):
            return False
    return True


def node_range_allows_major(node_range: str, current_major: int) -> bool:
    """Return True when a Node engine range has any branch compatible with major."""
    alternatives = node_range.split("||")
    return any(_alternative_allows_major(alternative, current_major) for alternative in alternatives)


def extract_node_engine_ranges(lockfile_text: str) -> list[str]:
    ranges: list[str] = []
    for pattern in (INLINE_ENGINE_PATTERN, BLOCK_ENGINE_PATTERN):
        for match in pattern.finditer(lockfile_text):
            node_range = match.group("quoted") or match.group("bare") or ""
            node_range = node_range.strip()
            if node_range:
                ranges.append(node_range)
    return ranges


def incompatible_node_engine_ranges(lockfile_text: str, current_major: int) -> list[str]:
    incompatible: list[str] = []
    for node_range in extract_node_engine_ranges(lockfile_text):
        if not node_range_allows_major(node_range, current_major):
            incompatible.append(node_range)
    return sorted(set(incompatible))


def should_ignore_build(branch: str, lockfile_text: str, current_major: int) -> tuple[bool, list[str]]:
    if not branch.startswith(DEPENDABOT_NPM_BRANCH_PREFIX):
        return False, []

    incompatible = incompatible_node_engine_ranges(lockfile_text, current_major)
    return bool(incompatible), incompatible


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Return Vercel ignoreCommand exit codes for preventable dependency-preview failures."
    )
    parser.add_argument("--branch", default=os.environ.get("VERCEL_GIT_COMMIT_REF", ""))
    parser.add_argument(
        "--node-major",
        type=int,
        default=_parse_node_major(os.environ.get("OPENMATES_VERCEL_NODE_MAJOR")),
        help="Configured Vercel Node major. Defaults to current project setting: 20.",
    )
    parser.add_argument("--lockfile", type=Path, default=_repo_root() / "pnpm-lock.yaml")
    args = parser.parse_args()

    if not args.lockfile.exists():
        print(f"[vercel-ignore] pnpm lockfile not found: {args.lockfile}; continuing build")
        return BUILD_CONTINUE

    lockfile_text = args.lockfile.read_text(encoding="utf-8")
    ignore, incompatible = should_ignore_build(args.branch, lockfile_text, args.node_major)
    if not ignore:
        print(f"[vercel-ignore] continuing build for branch {args.branch or '<unknown>'}")
        return BUILD_CONTINUE

    ranges = ", ".join(incompatible)
    print(
        f"[vercel-ignore] skipping Dependabot npm preview for {args.branch}: "
        f"lockfile requires Node range(s) {ranges}, Vercel is configured for Node {args.node_major}.x"
    )
    print("[vercel-ignore] update Vercel/project Node runtime or review the dependency update manually.")
    return BUILD_IGNORE


if __name__ == "__main__":
    sys.exit(main())
