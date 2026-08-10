#!/usr/bin/env python3
"""Bump OpenMates to a new 0.MINOR.0 alpha product line.

Purpose: update the product/package version line deterministically.
Architecture: product_version.json is the source of truth; package manifests,
Apple metadata, self-host defaults, and active docs mirror it.
Safety: operates on an allowlist and audits active files for stale references.
Tests: scripts/tests/test_bump_alpha_version_line.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PACKAGE_JSON_PATHS = [
    "package.json",
    "frontend/apps/web_app/package.json",
    "frontend/packages/ui/package.json",
    "frontend/packages/openmates-cli/package.json",
    "backend/status/frontend/package.json",
    "frontend/packages/typescript-config/package.json",
    "frontend/packages/eslint-config/package.json",
    "frontend/packages/secret-scanner/package.json",
]

PACKAGE_LOCK_PATHS = [
    "backend/status/frontend/package-lock.json",
]

TEXT_VERSION_PATHS = [
    "frontend/packages/ui/src/i18n/sources/signup/main.yml",
    "backend/core/docker-compose.selfhost.yml",
    "backend/preview/main.py",
    "backend/apps/openapi_docs_gen.py",
    "apple/project.yml",
    "apple/OpenMates.xcodeproj/project.pbxproj",
    "frontend/packages/openmates-cli/src/serverConfig.ts",
    "frontend/packages/openmates-cli/src/server.ts",
    "docs/user-guide/cli/server-management.md",
    "docs/self-hosting/setup.md",
    "docs/architecture/platforms/cli-package.md",
    "frontend/packages/openmates-cli/README.md",
    "packages/openmates-python/README.md",
    "docs/contributing/guides/git-and-deployment.md",
    "docs/contributing/guides/publish-python-sdk.md",
    "README.md",
    ".claude/skills/create-release/SKILL.md",
    ".agents/skills/create-release/SKILL.md",
    ".claude/skills/new-task/SKILL.md",
    ".agents/skills/new-task/SKILL.md",
]

AUDIT_INCLUDE_PATHS = set(
    PACKAGE_JSON_PATHS
    + PACKAGE_LOCK_PATHS
    + TEXT_VERSION_PATHS
    + [
        "shared/config/product_version.json",
        "packages/openmates-python/pyproject.toml",
        ".github/workflows/publish-cli.yml",
        ".github/workflows/publish-python-sdk.yml",
        ".github/workflows/publish-selfhost-images.yml",
        "scripts/prepare_cli_publish_version.mjs",
        "scripts/prepare_python_publish_version.py",
    ]
)

AUDIT_EXCLUDE_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "test-results",
    "docs/releases",
    "docs/specs",
    "scripts/.tmp",
    "scripts/tests",
    "scripts/test_legacy_cli_cutover.py",
}

TEXT_EXTENSIONS = {".json", ".yml", ".yaml", ".md", ".py", ".ts", ".js", ".mjs", ".toml", ".pbxproj"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(f"{json.dumps(value, indent=2, ensure_ascii=False)}\n", encoding="utf-8")


def replace_text(path: Path, replacements: dict[str, str]) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = original
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def update_package_json(path: Path, version: str) -> bool:
    package = read_json(path)
    if package.get("version") == version:
        return False
    package["version"] = version
    write_json(path, package)
    return True


def update_package_lock(path: Path, version: str) -> bool:
    package = read_json(path)
    changed = False
    if package.get("version") != version:
        package["version"] = version
        changed = True
    root_package = package.get("packages", {}).get("")
    if isinstance(root_package, dict) and root_package.get("version") != version:
        root_package["version"] = version
        changed = True
    if changed:
        write_json(path, package)
    return changed


def update_pyproject(path: Path, version: str) -> bool:
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'^version = "[^"]+"$', f'version = "{version}"', content, count=1, flags=re.MULTILINE)
    if count != 1:
        fail(f"Unable to update project.version in {path}")
    if updated == content:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def update_product_config(path: Path, major: int, minor: int, version: str, product_line: str) -> bool:
    config = read_json(path)
    next_config = {
        "userFacing": product_line,
        "cli": {
            "stableBase": version,
            "prereleaseLabel": "alpha",
        },
        "python": {
            "stableBase": version,
            "prereleaseLabel": "a",
        },
    }
    if config == next_config:
        return False
    if major != 0:
        fail("This migration script currently supports 0.MINOR.0 alpha product lines only.")
    write_json(path, next_config)
    return True


def is_audit_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    path_parts = set(relative.split("/"))
    for excluded in AUDIT_EXCLUDE_PARTS:
        if "/" in excluded:
            if relative == excluded or relative.startswith(f"{excluded.rstrip('/')}/"):
                return False
        elif excluded in path_parts:
            return False
    return relative in AUDIT_INCLUDE_PATHS


def audit_old_references(root: Path, old_minor: int) -> list[str]:
    patterns = [
        re.compile(rf"\b0\.{old_minor}\.(?:0|\d+)(?:-alpha\.\d+|a\d+)?\b"),
        re.compile(rf"\bv0\.{old_minor}(?:\.0|-alpha|\.\d+)?\b"),
    ]
    stale: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS or not is_audit_path(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                stale.append(f"{path.relative_to(root).as_posix()}: {match.group(0)}")
                break
    return sorted(stale)


def migrate(root: Path, major: int, minor: int, check: bool = False) -> list[str]:
    config_path = root / "shared/config/product_version.json"
    if not config_path.exists():
        fail(f"Missing {config_path}")
    config = read_json(config_path)
    current = config.get("cli", {}).get("stableBase", "0.0.0")
    match = re.match(r"^(\d+)\.(\d+)\.0$", current)
    if not match:
        fail(f"Expected current cli.stableBase to be 0.MINOR.0, got {current}")
    old_major = int(match.group(1))
    old_minor = int(match.group(2))
    audit_minor = minor - 1 if check and old_minor == minor and minor > 0 else old_minor
    old_version = f"{old_major}.{old_minor}.0"
    old_product_line = config.get("userFacing", f"v{old_major}.{old_minor}")
    new_version = f"{major}.{minor}.0"
    new_product_line = f"v{major}.{minor}"
    changed: list[str] = []

    def record(path: Path, did_change: bool) -> None:
        if did_change:
            changed.append(path.relative_to(root).as_posix())

    if not check:
        record(config_path, update_product_config(config_path, major, minor, new_version, new_product_line))
        for item in PACKAGE_JSON_PATHS:
            path = root / item
            if path.exists():
                record(path, update_package_json(path, new_version))
        for item in PACKAGE_LOCK_PATHS:
            path = root / item
            if path.exists():
                record(path, update_package_lock(path, new_version))
        pyproject = root / "packages/openmates-python/pyproject.toml"
        if pyproject.exists():
            record(pyproject, update_pyproject(pyproject, new_version))

        replacements = {
            old_version: new_version,
            old_product_line: new_product_line,
            f"{old_major}.{old_minor}.N": f"{major}.{minor}.N",
            f"{old_major}.{old_minor}.x": f"{major}.{minor}.x",
        }
        for item in TEXT_VERSION_PATHS:
            path = root / item
            if path.exists():
                record(path, replace_text(path, replacements))

    stale = audit_old_references(root, audit_minor)
    if stale:
        fail("Stale active version references remain:\n" + "\n".join(stale))
    return sorted(set(changed))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minor", type=int, required=True, help="Target minor X in 0.X.0-alpha.N")
    parser.add_argument("--major", type=int, default=0, help="Target major, defaults to 0")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument("--check", action="store_true", help="Audit without writing")
    args = parser.parse_args()
    if args.minor < 0 or args.major < 0:
        fail("Major and minor must be non-negative integers.")
    changed = migrate(args.root.resolve(), args.major, args.minor, check=args.check)
    if args.check:
        print("Version line audit passed.")
    else:
        print(f"Updated OpenMates to v{args.major}.{args.minor} / {args.major}.{args.minor}.0")
        for path in changed:
            print(path)


if __name__ == "__main__":
    main()
