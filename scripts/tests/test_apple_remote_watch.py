#!/usr/bin/env python3
"""Tests for deterministic Apple Watch remote verification commands.

These checks keep the Linux-to-Mac wrapper aligned with the Apple Watch spec.
They validate command construction only and never reveal or require private Mac
connection details, simulator UUIDs, or local checkout paths.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_remote.py"


def load_apple_remote():
    spec = importlib.util.spec_from_file_location("apple_remote", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["apple_remote"] = module
    spec.loader.exec_module(module)
    return module


def test_build_watch_command_targets_watch_scheme_and_simulator() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.build_watch_command("Apple Watch Series 11 (46mm)")

    assert "xcodebuild" in command
    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "-scheme OpenMatesWatch" in command
    assert "platform=watchOS Simulator,name=Apple Watch Series 11 (46mm)" in command
    assert command.endswith(" build")


def test_test_watch_command_targets_dedicated_ui_test_scheme() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_watch_command(
        "Apple Watch Series 11 (46mm)",
        "OpenMatesWatchUITests/WatchChatLayoutUITests",
    )

    assert "xcodebuild test" in command
    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "-scheme OpenMatesWatchUITests" in command
    assert "platform=watchOS Simulator,name=Apple Watch Series 11 (46mm)" in command
    assert "-only-testing OpenMatesWatchUITests/WatchChatLayoutUITests" in command


def test_project_declares_dedicated_watch_ui_test_target_and_scheme() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(encoding="utf-8")

    assert "  OpenMatesWatchUITests:\n" in project
    assert "      - path: OpenMatesWatchUITests\n" in project
    assert "        TEST_TARGET_NAME: OpenMatesWatch\n" in project
    assert "        - OpenMatesWatchUITests\n" in project


def test_watch_commands_are_registered_in_parser() -> None:
    apple_remote = load_apple_remote()
    parser = apple_remote.build_parser()

    build_args = parser.parse_args(["build-watch"])
    test_args = parser.parse_args(["test-watch", "--only-testing", "OpenMatesWatchTests/WatchChatRuntimeTests"])

    assert build_args.command == "build-watch"
    assert build_args.simulator == "Apple Watch Series 11 (46mm)"
    assert test_args.command == "test-watch"
    assert test_args.only_testing == "OpenMatesWatchTests/WatchChatRuntimeTests"
