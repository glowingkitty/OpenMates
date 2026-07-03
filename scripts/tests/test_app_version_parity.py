#!/usr/bin/env python3
"""Tests for public OpenMates app version parity.

The root package version is the release source of truth for the web app and CLI.
The Python SDK and Apple bundle marketing version must stay aligned so users see
the same public version across clients and package managers.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_app_versions_match_root_package_version() -> None:
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    canonical_version = root_package["version"]

    python_project = tomllib.loads((ROOT / "packages/openmates-python/pyproject.toml").read_text(encoding="utf-8"))
    assert python_project["project"]["version"] == canonical_version

    apple_project = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    marketing_version = re.search(r'MARKETING_VERSION:\s+"([^"]+)"', apple_project)
    assert marketing_version is not None
    assert marketing_version.group(1) == canonical_version

    xcode_project = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    xcode_versions = set(re.findall(r"MARKETING_VERSION = ([^;]+);", xcode_project))
    assert xcode_versions == {canonical_version}
