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


# contract-test: infrastructure
def test_ios_test_command_holds_shared_simulator_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_ios_command("iPhone 17e", "OpenMatesUITests/SettingsAppsParityUITests")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simulator_lock=acquired" in command
    assert "-only-testing OpenMatesUITests/SettingsAppsParityUITests" in command
    assert "-scheme OpenMates_iOS_UI_Tests" in command


# contract-test: infrastructure
def test_ios_unit_test_command_skips_ui_test_target() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_ios_command("iPhone 17e", "OpenMatesTests/SettingsModesParityTests")

    assert "-only-testing OpenMatesTests/SettingsModesParityTests" in command
    assert "-scheme OpenMates_iOS_Unit_Tests" in command
    assert "DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" in command


# contract-test: infrastructure
def test_ios_test_command_enforces_expected_commit_before_xcodebuild() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_ios_command(
        "iPhone 17e",
        "OpenMatesTests/ChatSyncParityTests",
        expected_commit="a" * 40,
    )

    assert "rev-parse" in command
    assert "HEAD" in command
    assert "apple_remote_commit_mismatch" in command
    assert ("a" * 40) in command
    assert command.index("rev-parse") < command.index("xcodebuild test")


# contract-test: infrastructure
def test_ios_test_command_can_forward_real_account_environment() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.test_ios_command(
        "iPhone 17e",
        "OpenMatesTests/WatchChatRuntimeTests/testLiveReservedAccountLoginLoadsAndOpensWatchChat",
        {
            "OPENMATES_TEST_ACCOUNT_EMAIL": "watch@example.test",
            "OPENMATES_TEST_ACCOUNT_PASSWORD": "p@ss word",
            "OPENMATES_TEST_ACCOUNT_OTP_KEY": "ABCDEF234567",
        },
    )

    assert "OPENMATES_TEST_ACCOUNT_EMAIL=watch@example.test" in command
    assert "OPENMATES_TEST_ACCOUNT_PASSWORD='p@ss word'" in command
    assert "OPENMATES_TEST_ACCOUNT_OTP_KEY=ABCDEF234567" in command
    assert "SIMCTL_CHILD_OPENMATES_TEST_ACCOUNT_EMAIL=watch@example.test" in command
    assert "SIMCTL_CHILD_OPENMATES_TEST_ACCOUNT_PASSWORD='p@ss word'" in command
    assert "SIMCTL_CHILD_OPENMATES_TEST_ACCOUNT_OTP_KEY=ABCDEF234567" in command
    assert "apple/.openmates-live-test-account.env" in command
    assert "trap" in command
    assert "xcodebuild test" in command


# contract-test: infrastructure
def test_real_account_environment_filter_excludes_unrelated_secrets(monkeypatch) -> None:
    apple_remote = load_apple_remote()
    monkeypatch.setattr(apple_remote, "load_local_dotenv", lambda: {})

    env = apple_remote.local_test_account_env({
        "OPENMATES_TEST_ACCOUNT_EMAIL": "watch@example.test",
        "OPENMATES_TEST_ACCOUNT_PASSWORD": "p@ss word",
        "OPENMATES_TEST_ACCOUNT_OTP_KEY": "ABCDEF234567",
        "OPENMATES_TEST_ACCOUNT_SESSION_TOKEN": "must-not-forward",
        "APP_STORE_CONNECT_API_KEY_ID": "must-not-forward",
    })

    assert env == {
        "OPENMATES_TEST_ACCOUNT_EMAIL": "watch@example.test",
        "OPENMATES_TEST_ACCOUNT_PASSWORD": "p@ss word",
        "OPENMATES_TEST_ACCOUNT_OTP_KEY": "ABCDEF234567",
    }


# contract-test: infrastructure
def test_xcodegen_declares_isolated_ios_test_schemes() -> None:
    project = (ROOT / "apple" / "project.yml").read_text(encoding="utf-8")
    unit_scheme = (
        ROOT
        / "apple"
        / "OpenMates.xcodeproj"
        / "xcshareddata"
        / "xcschemes"
        / "OpenMates_iOS_Unit_Tests.xcscheme"
    ).read_text(encoding="utf-8")

    assert "OpenMates_iOS_UI_Tests:" in project
    assert "OpenMates_iOS_Unit_Tests:" in project
    assert "OPENMATES_TEST_ACCOUNT_EMAIL: $(OPENMATES_TEST_ACCOUNT_EMAIL)" in project
    assert "OPENMATES_TEST_ACCOUNT_EMAIL" in unit_scheme
    assert "$(OPENMATES_TEST_ACCOUNT_EMAIL)" in unit_scheme
    assert (ROOT / "apple" / "OpenMates.xcodeproj" / "xcshareddata" / "xcschemes" / "OpenMates_iOS_UI_Tests.xcscheme").exists()
    assert (ROOT / "apple" / "OpenMates.xcodeproj" / "xcshareddata" / "xcschemes" / "OpenMates_iOS_Unit_Tests.xcscheme").exists()


# contract-test: infrastructure
def test_ios_build_command_holds_shared_simulator_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.build_ios_command("iPhone 17e")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "xcodebuild" in command


# contract-test: infrastructure
def test_cleanup_command_uses_same_lock_as_xcode_tests() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.simulator_cleanup_command("booted")

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simctl shutdown booted" in command
    assert "DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" in command


# contract-test: infrastructure
def test_direct_simctl_command_uses_shared_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.simctl_remote_command(["uninstall", "booted", "org.openmates.app"])

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simctl uninstall booted org.openmates.app" in command
    assert "DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" in command


# contract-test: infrastructure
def test_watch_startup_command_uses_shared_lock() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.verify_watch_startup_command("Apple Watch Series 11 (46mm)", 60)

    assert apple_remote.SIMULATOR_LOCK_PATH in command
    assert "fcntl.flock" in command
    assert "simulator_lock=acquired" in command
