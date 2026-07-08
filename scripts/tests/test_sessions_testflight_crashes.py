#!/usr/bin/env python3
"""Regression tests for session startup TestFlight crash context.

These tests keep the developer workflow deterministic without reaching Apple or
the remote Mac during CI. The production command is intentionally non-blocking
from sessions.py, so failures should render as context hints rather than aborting
session startup.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_apple_context_detects_apple_feature_sessions() -> None:
    sessions = load_sessions_module()

    assert sessions._is_apple_session_context("feature", [], "Fix Apple composer visibility")
    assert sessions._is_apple_session_context("bug", [], "Investigate iOS crash on launch")
    assert sessions._is_apple_session_context("testing", [], "Verify TestFlight build")


def test_apple_context_skips_question_and_non_apple_sessions() -> None:
    sessions = load_sessions_module()

    assert not sessions._is_apple_session_context("question", [], "How does iOS auth work?")
    assert not sessions._is_apple_session_context("feature", ["backend"], "Add backend provider logging")


def test_prefetch_testflight_crashes_uses_remote_wrapper(monkeypatch) -> None:
    sessions = load_sessions_module()
    calls = []

    def fake_run_cmd(cmd, timeout):
        calls.append((cmd, timeout))
        return 0, "testflight_crashes_status=ok\ncrash_submission_count=0", ""

    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)

    output = sessions._prefetch_testflight_crashes(limit=2)

    assert "testflight_crashes_status=ok" in output
    assert calls[0][0][-2:] == ["--limit", "2"]
    assert calls[0][0][2] == "testflight-crashes"
    assert calls[0][0][1].endswith("scripts/apple_remote.py")
    assert calls[0][1] == 20


def test_prefetch_testflight_crashes_is_non_blocking(monkeypatch) -> None:
    sessions = load_sessions_module()

    monkeypatch.setattr(
        sessions,
        "_run_cmd",
        lambda _cmd, timeout: (1, "", "AppleRemoteError: Set OPENMATES_APPLE_SSH_TARGET"),
    )

    output = sessions._prefetch_testflight_crashes()

    assert "could not fetch TestFlight crashes" in output
    assert "OPENMATES_APPLE_SSH_TARGET" in output
