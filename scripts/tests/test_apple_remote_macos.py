#!/usr/bin/env python3
"""Tests for first-class remote macOS build and UI-test orchestration.

These Linux-safe tests inspect command construction and XcodeGen configuration;
they never connect to a Mac or execute Xcode. The assertions keep remote output
behind apple_remote.py's redaction boundary and preserve the real test target.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_remote.py"


def load_apple_remote():
    spec = importlib.util.spec_from_file_location("apple_remote_macos", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["apple_remote_macos"] = module
    spec.loader.exec_module(module)
    return module


def test_macos_commands_use_the_shared_scheme_and_native_destination() -> None:
    apple_remote = load_apple_remote()

    build = apple_remote.build_macos_command()
    test = apple_remote.test_macos_command("OpenMatesMacUITests/SettingsMacShellParityUITests")

    for command in (build, test):
        assert "npm run build:translations" in command
        assert "-scheme OpenMates_macOS" in command
        assert "-destination platform=macOS" in command
        assert "/Users/" not in command
    assert "-only-testing OpenMatesMacUITests/SettingsMacShellParityUITests" in test
    assert "-allowProvisioningUpdates" in test


def test_macos_parser_exposes_build_and_targeted_test_commands() -> None:
    apple_remote = load_apple_remote()
    parser = apple_remote.build_parser()

    assert parser.parse_args(["build-macos"]).command == "build-macos"
    test_args = parser.parse_args([
        "test-macos",
        "--only-testing",
        "OpenMatesMacUITests/SettingsMacShellParityUITests",
    ])
    assert test_args.command == "test-macos"
    assert test_args.only_testing == "OpenMatesMacUITests/SettingsMacShellParityUITests"


def test_xcodegen_declares_the_real_macos_ui_test_target() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(encoding="utf-8")

    assert "OpenMatesMacUITests:" in project
    assert "platform: macOS" in project
    assert "path: OpenMatesMacUITests" in project
    assert "target: OpenMates_macOS" in project
    assert "TEST_TARGET_NAME: OpenMates_macOS" in project
    assert "- OpenMatesMacUITests" in project
