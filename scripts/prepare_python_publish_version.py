#!/usr/bin/env python3
"""Prepare the OpenMates Python SDK version before PyPI publish.

Purpose: keep PyPI package versions aligned with product releases.
Architecture: mirrors scripts/prepare_cli_publish_version.mjs for npm.
Security: uses public PyPI JSON only; no credentials or tokens are read.
Scope: rewrites packages/openmates-python/pyproject.toml version in CI.
Tests: scripts/tests/test_prepare_python_publish_version.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "shared" / "config" / "product_version.json"
PYPROJECT_PATH = ROOT / "packages" / "openmates-python" / "pyproject.toml"
PYPI_JSON_URL = "https://pypi.org/pypi/openmates/json"
VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_pyproject_version(path: Path = PYPROJECT_PATH) -> str:
    match = VERSION_PATTERN.search(path.read_text(encoding="utf-8"))
    if not match:
        fail(f"Unable to find project.version in {path}")
    return match.group(1)


def write_pyproject_version(version: str, path: Path = PYPROJECT_PATH) -> None:
    content = path.read_text(encoding="utf-8")
    path.write_text(VERSION_PATTERN.sub(f'version = "{version}"', content, count=1), encoding="utf-8")


def parse_version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        fail(f"Invalid stable Python package version: {version}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def release_line_entries(config: dict, versions: list[str]) -> tuple[tuple[int, int, int], list[int]]:
    major, minor, base_patch = parse_version_tuple(config["stableBase"])
    label = config.get("prereleaseLabel", "a")
    prerelease_pattern = re.compile(rf"^(\d+)\.(\d+)\.(\d+){re.escape(label)}(\d+)$")
    prerelease_indexes: list[int] = []

    for version in versions:
        match = prerelease_pattern.match(version)
        if not match:
            continue
        parsed_major = int(match.group(1))
        parsed_minor = int(match.group(2))
        patch = int(match.group(3))
        index = int(match.group(4))
        if parsed_major == major and parsed_minor == minor and patch == base_patch:
            prerelease_indexes.append(index)

    return (major, minor, base_patch), prerelease_indexes


def published_versions(args: argparse.Namespace) -> list[str]:
    if args.published_versions is not None:
        return [version.strip() for version in args.published_versions.split(",") if version.strip()]
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return sorted((payload.get("releases") or {}).keys())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []


def next_prerelease_version(config: dict, versions: list[str]) -> str:
    if config["stableBase"] in versions:
        fail(
            f"Cannot publish a prerelease below existing stable base {config['stableBase']}; "
            "bump the product minor line first."
        )
    (major, minor, base_patch), indexes = release_line_entries(config, versions)
    label = config.get("prereleaseLabel", "a")
    index = max(indexes, default=-1) + 1
    return f"{major}.{minor}.{base_patch}{label}{index}"


def next_stable_version(config: dict, versions: list[str]) -> str:
    major, minor, base_patch = parse_version_tuple(config["stableBase"])
    return f"{major}.{minor}.{base_patch}"


def validate_config(config: dict) -> None:
    stable_base = config.get("stableBase", "")
    prerelease_label = config.get("prereleaseLabel", "a")
    if not SEMVER_PATTERN.match(stable_base):
        fail(f"python.stableBase must be a PEP 440 stable version, got {stable_base}")
    if prerelease_label != "a":
        fail(f"python.prereleaseLabel must be 'a' for alpha prereleases, got {prerelease_label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=["check", "dev", "main"], default="check")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--published-versions", help="Comma-separated versions for deterministic tests")
    args = parser.parse_args()

    product_config = load_json(CONFIG_PATH)
    config = product_config.get("python") or {}
    validate_config(config)
    current = read_pyproject_version()
    if args.channel == "check":
        if current != config["stableBase"]:
            fail(f"Python pyproject.toml version must be {config['stableBase']}, got {current}")
        print(current)
        return

    versions = published_versions(args)
    version = next_prerelease_version(config, versions) if args.channel == "dev" else next_stable_version(config, versions)
    if not args.dry_run:
        write_pyproject_version(version)
    print(version)


if __name__ == "__main__":
    main()
