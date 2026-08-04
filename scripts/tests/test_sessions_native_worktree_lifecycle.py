#!/usr/bin/env python3
"""Lifecycle contracts for routed and grandfathered worktree sessions.

The suite verifies migration-safe routing repair and rejects nested managed
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
    assert sessions.validate_worktree_binding_mode({"binding_mode": "worktree_routed"}) == "worktree_routed"


def test_routing_repair_migrates_obsolete_mode_and_touches_session(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "pending",
                "last_active": "old",
                "worktree": {"path": "/repo/agent-abcd", "status": "active"},
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)

    result = sessions.repair_worktree_routing("ses_parent")

    assert result == {"session_id": "abcd", "mode": "worktree_routed", "worktree_path": "/repo/agent-abcd"}
    assert data["sessions"]["abcd"]["binding_mode"] == "worktree_routed"
    assert data["sessions"]["abcd"]["last_active"] == "now"


def test_routing_repair_resumes_merged_worktree_after_deploy(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "worktree_routed",
                "worktree": {"path": "/repo/agent-abcd", "status": "merged"},
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)

    result = sessions.repair_worktree_routing("ses_parent")

    assert result["worktree_path"] == "/repo/agent-abcd"
    assert result["mode"] == "worktree_routed"


def test_routing_repair_failure_is_actionable(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "binding_mode": "pending"}}}
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))

    try:
        sessions.repair_worktree_routing("ses_parent")
    except RuntimeError as error:
        assert "Reason:" in str(error)
        assert "Next:" in str(error)
        assert "worktree ensure --session abcd" in str(error)
    else:
        raise AssertionError("repair must reject a missing worktree")


def test_existing_opencode_session_is_reused_after_restart() -> None:
    sessions = load_sessions_module()
    existing = {"task": "continue work", "worktree": {"path": "/repo/agent-abcd", "status": "active"}}
    data = {"sessions": {"abcd": {**existing, "opencode_session_id": "ses_parent"}}}

    result = sessions.session_for_opencode(data, "ses_parent")

    assert result is not None
    assert result[0] == "abcd"
    assert result[1]["worktree"]["path"] == "/repo/agent-abcd"


def test_managed_worktrees_cannot_nest(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    assert sessions.is_valid_managed_worktree_path(managed / "agent-abcd")
    assert not sessions.is_valid_managed_worktree_path(managed / "agent-abcd" / "managed" / "agent-efgh")
