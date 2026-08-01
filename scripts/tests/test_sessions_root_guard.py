#!/usr/bin/env python3
"""Tests for root checkout control-plane guard helpers.

The root checkout remains useful for orchestration but must not be the default
place for session source edits once automatic worktrees are available.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_root_guard", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_root_guard_warns_in_transition_mode(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setenv("OPENMATES_ROOT_GUARD", "warn")

    result = sessions.evaluate_root_guard("edit", PROJECT_ROOT / "scripts" / "sessions.py", session_id="abcd")

    assert result["decision"] == "warn"
    assert "worktree" in result["message"]
    assert "abcd" in result["message"]


def test_root_guard_blocks_strict_source_edit(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setenv("OPENMATES_ROOT_GUARD", "strict")

    result = sessions.evaluate_root_guard("edit", PROJECT_ROOT / "scripts" / "sessions.py", session_id="abcd")

    assert result["decision"] == "block"


def test_root_guard_blocks_source_edit_by_default(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.delenv("OPENMATES_ROOT_GUARD", raising=False)

    result = sessions.evaluate_root_guard("edit", PROJECT_ROOT / "scripts" / "sessions.py", session_id="abcd")

    assert result["decision"] == "block"


def test_root_guard_allows_control_plane_command(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setenv("OPENMATES_ROOT_GUARD", "strict")

    result = sessions.evaluate_root_guard("control-plane", PROJECT_ROOT / "scripts" / "sessions.py", session_id="abcd")

    assert result["decision"] == "allow"
