#!/usr/bin/env python3
"""Regression coverage for retired OpenCode monitor scheduling.

The monitor command/helper is removed; historical records are preserved.
General continuations still serve Task, decision and media workflows.
All checks are local tooling checks and never launch a chat or runtime.
"""
# contract-test-file: tooling

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_sessions():
    spec = importlib.util.spec_from_file_location("sessions_monitor_retirement", ROOT / "scripts/sessions.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_monitor_command_and_module_are_removed():
    assert not (ROOT / "scripts/_orchestration_monitor.py").exists()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/sessions.py"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for command in ("continuation", "media", "task-bridge", "ci-source", "ci-adopt", "deploy"):
        assert command in result.stdout
    result = subprocess.run([sys.executable, str(ROOT / "scripts/sessions.py"), "monitor", "--help"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid choice: 'monitor'" in result.stderr


def test_retired_ready_records_cannot_be_delivered_and_history_is_preserved(monkeypatch):
    sessions = load_sessions()
    data = {"sessions": {"abcd": {
        "opencode_session_id": "ses_test",
        "orchestration_monitor": {"status": "active", "workers": {"ses_worker": {}}},
        "continuation": {"operation_type": "monitor_ready", "operation_key": "old", "status": "ready", "attempts": 0},
    }}}
    before = copy.deepcopy(data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    assert sessions._claim_session_continuation("abcd") is None
    assert data == before
    with pytest.raises(RuntimeError, match="unsupported continuation operation type"):
        sessions._record_session_continuation("abcd", operation_type="monitor_ready", operation_key="new", next_action="Tick")
    assert data == before


def test_shared_continuation_operation_types_remain_available():
    sessions = load_sessions()
    assert sessions.CONTINUATION_ALLOWED_TYPES == {
        "resource_ready", "health_ready", "deployment_ready", "media_delivery", "task_ready",
    }
