#!/usr/bin/env python3
"""Tests for deterministic Apple native debugging remote commands.

These checks keep the Linux-to-Mac debugging workflow safe for AI agents. They
validate command construction and parser registration only, so no private SSH
configuration, simulator UUID, local Mac path, or Xcode installation is needed.
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


def test_parser_exposes_native_debugging_commands() -> None:
    apple_remote = load_apple_remote()
    parser = apple_remote.build_parser()

    doctor_args = parser.parse_args(["doctor"])
    ios_args = parser.parse_args(["verify-ios-startup", "--simulator", "iPhone 17", "--duration", "45"])
    fresh_ios_args = parser.parse_args(["verify-ios-startup", "--fresh-install"])
    macos_args = parser.parse_args(["verify-macos-startup", "--duration", "45"])

    assert doctor_args.command == "doctor"
    assert ios_args.command == "verify-ios-startup"
    assert ios_args.simulator == "iPhone 17"
    assert ios_args.duration == 45
    assert ios_args.fresh_install is False
    assert fresh_ios_args.fresh_install is True
    assert macos_args.command == "verify-macos-startup"
    assert macos_args.duration == 45


def test_doctor_command_checks_remote_readiness_without_exposing_repo_path() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.apple_remote_doctor_command("/Users/example/OpenMates")

    assert "xcodebuild" in command
    assert "simctl" in command
    assert "git" in command
    assert "OpenMates.xcodeproj" in command
    assert "watch_test_status" in command
    assert "no_dedicated_watch_test_scheme" in command
    assert "<repo-path>" in command


def test_ios_startup_verifier_builds_launches_screenshots_and_collects_logs() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.verify_ios_startup_command("iPhone 17", 60)

    assert "simulator_lock=waiting" in command
    assert "simulator_lock=acquired" in command
    assert "fresh_install = sys.argv[3]" in command
    assert "OpenMates_iOS" in command
    assert "npm" in command
    assert "build:translations" in command
    assert "cwd=\"frontend/packages/ui\"" in command
    assert "xcodebuild" in command
    assert "-showBuildSettings" in command
    assert "platform=iOS Simulator,name={simulator}" in command
    assert "'iPhone 17'" in command
    assert '"xcrun", "simctl", "bootstatus"' in command
    assert "fresh_install" in command
    assert "uninstall_status=skipped" in command
    assert "uninstall_status=already_absent" in command
    assert "print_tail(\"uninstall_status\"" in command
    assert '"xcrun", "simctl", "install"' in command
    assert '"xcrun", "simctl", "launch"' in command
    assert "org.openmates.app" in command
    assert "screenshot_5s" in command
    assert "screenshot_30s" in command
    assert "ios-startup.log" in command
    assert "shutil.rmtree(artifact_dir, ignore_errors=True)" in command
    assert 'f"startup_status={status}"' in command

    fresh_command = apple_remote.verify_ios_startup_command("iPhone 17", 60, fresh_install=True)
    assert fresh_command.endswith(" 1")


def test_macos_startup_verifier_builds_launches_screenshots_and_collects_logs() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.verify_macos_startup_command(60)

    assert "OpenMates_macOS" in command
    assert "def run(label, cmd, *, timeout, cwd=None)" in command
    assert "npm" in command
    assert "build:translations" in command
    assert "cwd=\"frontend/packages/ui\"" in command
    assert "xcodebuild" in command
    assert "-showBuildSettings" in command
    assert "platform=macOS" in command
    assert "subprocess.Popen" in command
    assert "launch_pid={process.pid}" in command
    assert "skipped_privacy" in command
    assert "screencapture" not in command
    assert "pkill" not in command
    assert "process.terminate" in command
    assert "shutil.rmtree(artifact_dir, ignore_errors=True)" in command
    assert 'f"startup_status={status}"' in command


def test_startup_verifiers_reject_invalid_duration() -> None:
    apple_remote = load_apple_remote()

    for verifier in (
        lambda: apple_remote.verify_ios_startup_command("iPhone 17", 0),
        lambda: apple_remote.verify_macos_startup_command(0),
    ):
        try:
            verifier()
        except apple_remote.AppleRemoteError as exc:
            assert "duration" in str(exc)
        else:
            raise AssertionError("Expected duration validation to fail")


def test_embedded_native_debugging_scripts_compile() -> None:
    apple_remote = load_apple_remote()

    for name in (
        "APPLE_REMOTE_DOCTOR_SCRIPT",
        "IOS_STARTUP_SCRIPT",
        "MACOS_STARTUP_SCRIPT",
    ):
        compile(getattr(apple_remote, name), name, "exec")
