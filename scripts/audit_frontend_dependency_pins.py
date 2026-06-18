#!/usr/bin/env python3
"""Audit frontend dependency pins that protect editor and asset loading.

This catches lockfile drift that can reintroduce duplicate ProseMirror packages
or the SvelteKit asset-path regression that broke the chat composer and font
loading in the daily smoke run. It is intentionally narrow and cheap so agents
can run it after dependency updates without running local frontend builds.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCKFILE = REPO_ROOT / "pnpm-lock.yaml"
LOCKFILE_ENTRY_RE = re.compile(r"^\s{2}(['\"]?[^:'\"]+@[^:'\"]+['\"]?):", re.MULTILINE)
PINNED_PACKAGE_VERSIONS = {
    "@sveltejs/kit": "2.60.1",
    "prosemirror-model": "1.25.7",
    "prosemirror-view": "1.41.8",
}
PINNED_PACKAGE_PREFIXES = {
    "@tiptap/": "3.26.0",
}


@dataclass(frozen=True)
class AuditIssue:
    package: str
    message: str


def _packages_section(lockfile_text: str) -> str:
    packages_start = lockfile_text.find("\npackages:\n")
    snapshots_start = lockfile_text.find("\nsnapshots:\n")
    if packages_start == -1 or snapshots_start == -1 or snapshots_start <= packages_start:
        return ""
    return lockfile_text[packages_start:snapshots_start]


def _split_package_key(package_key: str) -> tuple[str, str] | None:
    normalized = package_key.strip().strip("'\"")
    if "@" not in normalized:
        return None
    name, version = normalized.rsplit("@", 1)
    if not name or not version:
        return None
    return name, version


def collect_package_versions(lockfile_text: str) -> dict[str, set[str]]:
    """Collect package versions from the pnpm lockfile packages section."""
    packages: dict[str, set[str]] = {}
    for match in LOCKFILE_ENTRY_RE.finditer(_packages_section(lockfile_text)):
        parsed = _split_package_key(match.group(1))
        if parsed is None:
            continue
        name, version = parsed
        packages.setdefault(name, set()).add(version)
    return packages


def audit_lockfile(lockfile_text: str) -> list[AuditIssue]:
    packages = collect_package_versions(lockfile_text)
    issues: list[AuditIssue] = []

    for package_name, expected_version in PINNED_PACKAGE_VERSIONS.items():
        versions = packages.get(package_name, set())
        if versions != {expected_version}:
            found = ", ".join(sorted(versions)) if versions else "not found"
            issues.append(
                AuditIssue(
                    package_name,
                    f"expected only {expected_version} in pnpm-lock.yaml, found {found}",
                )
            )

    for package_prefix, expected_version in PINNED_PACKAGE_PREFIXES.items():
        for package_name, versions in sorted(packages.items()):
            if not package_name.startswith(package_prefix):
                continue
            if versions != {expected_version}:
                found = ", ".join(sorted(versions))
                issues.append(
                    AuditIssue(
                        package_name,
                        f"expected only {expected_version} in pnpm-lock.yaml, found {found}",
                    )
                )

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit frontend dependency pins that protect editor and asset loading."
    )
    parser.add_argument(
        "lockfile",
        nargs="?",
        default=str(DEFAULT_LOCKFILE),
        help="Path to pnpm-lock.yaml. Defaults to the repository lockfile.",
    )
    args = parser.parse_args(argv)

    lockfile_path = Path(args.lockfile)
    if not lockfile_path.is_file():
        print(f"[frontend-dependency-pins] Lockfile not found: {lockfile_path}", file=sys.stderr)
        return 1

    issues = audit_lockfile(lockfile_path.read_text(encoding="utf-8", errors="replace"))
    if issues:
        print("[frontend-dependency-pins] Issues found:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue.package}: {issue.message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
