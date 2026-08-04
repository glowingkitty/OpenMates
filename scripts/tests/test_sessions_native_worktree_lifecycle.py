#!/usr/bin/env python3
"""Red lifecycle contracts for native and grandfathered worktree sessions.

The suite verifies mutually exclusive rollout modes and rejects nested managed
worktrees without creating real Git worktrees or changing repository state.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_native_lifecycle", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_binding_modes_are_mutually_exclusive() -> None:
    sessions = load_sessions_module()

    assert sessions.validate_worktree_binding_mode({"binding_mode": "native"}) == "native"
    assert sessions.validate_worktree_binding_mode({"binding_mode": "pilot_fallback"}) == "pilot_fallback"
    assert sessions.validate_worktree_binding_mode({"binding_mode": "legacy_grandfathered"}) == "legacy_grandfathered"


def test_managed_worktrees_cannot_nest(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    assert sessions.is_valid_managed_worktree_path(managed / "agent-abcd")
    assert not sessions.is_valid_managed_worktree_path(managed / "agent-abcd" / "managed" / "agent-efgh")
