#!/usr/bin/env python3
"""Regression tests for remote Apple Watch startup diagnostics.

These tests guard the remote Mac workflow that verifies a Watch simulator build
before TestFlight upload. A build that launches once is not enough: the verifier
must keep the process alive long enough to catch startup crashes and collect
sanitized evidence for debugging.
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


def test_parser_exposes_watch_startup_verifier() -> None:
    apple_remote = load_apple_remote()

    args = apple_remote.build_parser().parse_args([
        "verify-watch-startup",
        "--simulator",
        "Apple Watch Series 11 (46mm)",
        "--duration",
        "60",
    ])

    assert args.command == "verify-watch-startup"
    assert args.simulator == "Apple Watch Series 11 (46mm)"
    assert args.duration == 60


def test_watch_startup_verifier_builds_installs_launches_and_collects_evidence() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.verify_watch_startup_command("Apple Watch Series 11 (46mm)", 60)

    assert "OpenMatesWatch" in command
    assert "xcodebuild" in command
    assert "-showBuildSettings" in command
    assert '"xcrun", "simctl", "bootstatus"' in command
    assert '"xcrun", "simctl", "uninstall"' in command
    assert '"xcrun", "simctl", "install"' in command
    assert '"xcrun", "simctl", "launch"' in command
    assert "org.openmates.app.watch" in command
    assert '"xcrun", "simctl", "spawn"' in command
    assert '"launchctl", "procinfo", pid' in command
    assert '"pgrep"' not in command
    assert 'f"system/{bundle_id}"' not in command
    assert "DiagnosticReports" in command
    assert "screenshot_5s" in command
    assert "screenshot_30s" in command
    assert 'status = "passed"' in command
    assert 'f"startup_status={status}"' in command
    assert 'status = "process_exited"' in command
    assert 'status = "crash_report_found"' in command
    assert "artifact_dir=" in command
    assert "shutil.rmtree(artifact_dir, ignore_errors=True)" in command
    assert "60" in command


def test_watch_startup_verifier_rejects_invalid_duration() -> None:
    apple_remote = load_apple_remote()

    try:
        apple_remote.verify_watch_startup_command("Apple Watch Series 11 (46mm)", 0)
    except apple_remote.AppleRemoteError as exc:
        assert "duration" in str(exc)
    else:
        raise AssertionError("Expected duration validation to fail")
