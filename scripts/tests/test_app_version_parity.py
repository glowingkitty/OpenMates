#!/usr/bin/env python3
"""Tests for public OpenMates app version parity.

The root package version is the release source of truth for the web app and CLI.
The Python SDK and Apple bundle marketing version must stay aligned so users see
the same public version across clients and package managers.
"""

from __future__ import annotations

import json
import plistlib
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


def test_apple_app_store_metadata_is_upload_ready() -> None:
    apple_project = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    project_build_number = re.search(r"CURRENT_PROJECT_VERSION:\s+(\d+)", apple_project)
    assert project_build_number is not None
    assert int(project_build_number.group(1)) >= 2

    xcode_project = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    xcode_build_numbers = set(re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", xcode_project))
    assert xcode_build_numbers == {project_build_number.group(1)}

    info_plist = plistlib.loads((ROOT / "apple/OpenMates/Resources/Info.plist").read_bytes())
    assert info_plist["NSMicrophoneUsageDescription"]
    assert info_plist["ITSAppUsesNonExemptEncryption"] is True
