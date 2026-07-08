#!/usr/bin/env python3
"""Tests for Python SDK PyPI publish version preparation.

The workflow publishes from dev and main with PyPI Trusted Publishing. These
tests cover the version arithmetic locally so CI does not discover duplicate or
invalid package versions only after reaching the publish step.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_python_publish_version.py"


def load_module():
    spec = importlib.util.spec_from_file_location("prepare_python_publish_version", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next_prerelease_version_uses_seed_when_no_matching_release_exists():
    module = load_module()
    config = {"prereleaseBase": "0.13.0a", "prereleaseSeed": "0.13.0a0"}

    assert module.next_prerelease_version(config, ["0.12.0a9", "0.12.0"]) == "0.13.0a0"


def test_next_prerelease_version_increments_latest_matching_alpha():
    module = load_module()
    config = {"prereleaseBase": "0.13.0a", "prereleaseSeed": "0.13.0a0"}

    assert module.next_prerelease_version(config, ["0.13.0a0", "0.13.0a3"]) == "0.13.0a4"


def test_next_stable_version_uses_base_until_it_has_been_published():
    module = load_module()
    config = {"stableBase": "0.13.0"}

    assert module.next_stable_version(config, ["0.12.9", "0.13.0a4"]) == "0.13.0"


def test_next_stable_version_patch_bumps_when_base_exists():
    module = load_module()
    config = {"stableBase": "0.13.0"}

    assert module.next_stable_version(config, ["0.13.0", "0.13.1"]) == "0.13.2"
