#!/usr/bin/env python3
"""Tests for serialized remote Apple simulator lifecycle commands.

These tests inspect generated commands without connecting to the remote Mac.
They prevent concurrent OpenCode sessions from shutting down a simulator while
another session's Xcode test runner is active.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_remote.py"


def load_apple_remote():
    spec = importlib.util.spec_from_file_location("apple_remote_simulator_lock", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["apple_remote_simulator_lock"] = module
    spec.loader.exec_module(module)
    return module


def test_ios_test_command_holds_shared_simulator_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_ios_command("iPhone 17e", "OpenMatesUITests/SettingsAppsParityUITests")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simulator_lock=acquired" in command
    assert "-only-testing OpenMatesUITests/SettingsAppsParityUITests" in command


def test_ios_build_command_holds_shared_simulator_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.build_ios_command("iPhone 17e")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "xcodebuild" in command


def test_cleanup_command_uses_same_lock_as_xcode_tests() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.simulator_cleanup_command("booted")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simctl shutdown booted" in command
