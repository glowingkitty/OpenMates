#!/usr/bin/env python3
"""Lifecycle contracts for routed and grandfathered worktree sessions.

The suite verifies migration-safe routing repair and rejects nested managed
worktrees without creating real Git worktrees or changing repository state.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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


def test_register_session_reuses_codex_binding_when_description_changes(monkeypatch):
    sessions = load_sessions_module()
    task = "01a08fff-fdcb-7270-97bf-76e608bed3b5"
    data = {"sessions": {"old1": {"task": "old task", "codex_task_id": task, "codex_host": "test-host"}}}
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    sid, _, _, _, created = sessions.register_session_record({"task": "new task", "codex_task_id": task, "codex_host": "test-host"})
    assert sid == "old1" and created is False
    assert list(data["sessions"]) == ["old1"]


def test_stale_resource_waits_are_pruned(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "stale": {
                "resource_wait": {
                    "status": "waiting",
                    "resource": "docker_rebuild",
                    "heartbeat_at": "old",
                    "waiter_pid": 12345,
                }
            },
            "live": {
                "resource_wait": {
                    "status": "waiting",
                    "resource": "docker_rebuild",
                    "heartbeat_at": "recent",
                    "waiter_pid": 23456,
                }
            },
        }
    }

    monkeypatch.setattr(sessions, "_minutes_since", lambda value: 10 if value == "old" else 1)
    monkeypatch.setattr(sessions, "_process_is_alive", lambda pid: pid == 23456)

    assert sessions._prune_stale_resource_waits(data) == 1
    assert "resource_wait" not in data["sessions"]["stale"]
    assert data["sessions"]["live"]["resource_wait"]["waiter_pid"] == 23456


def test_refresh_session_worktree_base_updates_safe_fast_forward(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {
        "sessions": {
            "abcd": {
                "binding_mode": "legacy_grandfathered",
                "worktree": {
                    "path": str(worktree_path),
                    "base_commit": "old",
                    "status": "active",
                }
            }
        }
    }

    def run_command(command, **_kwargs):
        if command[1] == "rev-parse":
            return 0, "new\n", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "new")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")

    result = sessions.refresh_session_worktree_base("abcd")

    assert result["previous_base"] == "old"
    assert result["base_commit"] == "new"
    assert result["binding_mode"] == "worktree_routed"
    assert data["sessions"]["abcd"]["binding_mode"] == "worktree_routed"
    assert data["sessions"]["abcd"]["worktree"]["base_commit"] == "new"
    assert data["sessions"]["abcd"]["worktree"]["last_active"] == "now"


def test_refresh_session_worktree_base_updates_stale_merged_commit(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {
        "sessions": {
            "abcd": {
                "binding_mode": "worktree_routed",
                "worktree": {
                    "path": str(worktree_path),
                    "base_commit": "new",
                    "merged_commit": "old-merged",
                    "status": "active",
                },
            }
        }
    }

    def run_command(command, **_kwargs):
        if command[1] == "rev-parse":
            return 0, "new\n", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "new")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")

    result = sessions.refresh_session_worktree_base("abcd")

    assert result["previous_base"] == ""
    assert result["base_commit"] == "new"
    assert data["sessions"]["abcd"]["worktree"]["merged_commit"] == "new"
    assert data["sessions"]["abcd"]["worktree"]["last_active"] == "now"


def test_managed_worktrees_cannot_nest(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    assert sessions.is_valid_managed_worktree_path(managed / "agent-abcd")
    assert not sessions.is_valid_managed_worktree_path(managed / "agent-abcd" / "managed" / "agent-efgh")


@pytest.mark.parametrize('shared_name', ['code', 'configured-server'])
def test_codex_session_completion_never_kills_shared_opencode_zellij(monkeypatch, shared_name):
    """Codex lacks an OpenCode id but still must not own the shared server terminal."""
    import argparse
    import types
    sessions = load_sessions_module()
    data = {'sessions': {'abcd': {'mode': 'feature', 'zellij_session': shared_name,
                                'worktree': {'path': '/fixture/agent-abcd'}}}}
    killed = []
    monkeypatch.setenv('OPENCODE_ZELLIJ_SESSION', shared_name)
    monkeypatch.delenv('ZELLIJ_SESSION_NAME', raising=False)
    monkeypatch.setattr(sessions, '_load_sessions', lambda: data)
    monkeypatch.setattr(sessions, '_session_is_control_plane_repo', lambda _: False)
    monkeypatch.setattr(sessions, 'finalize_session_worktree', lambda *a, **k: None)
    monkeypatch.setattr(sessions, '_linear_complete_session', lambda *a: None)
    monkeypatch.setitem(sys.modules, '_zellij_utils', types.SimpleNamespace(kill_session=killed.append))
    sessions.cmd_end(argparse.Namespace(session='abcd', force=False))
    assert killed == []


def test_completion_can_still_close_an_owned_private_zellij_session(monkeypatch):
    import argparse
    import types
    sessions = load_sessions_module()
    data = {'sessions': {'abcd': {'mode': 'feature', 'zellij_session': 'private-worker',
                                'worktree': {'path': '/fixture/agent-abcd'}}}}
    killed = []
    monkeypatch.delenv('ZELLIJ_SESSION_NAME', raising=False)
    monkeypatch.setenv('OPENCODE_ZELLIJ_SESSION', 'code')
    monkeypatch.setattr(sessions, '_load_sessions', lambda: data)
    monkeypatch.setattr(sessions, '_session_is_control_plane_repo', lambda _: False)
    monkeypatch.setattr(sessions, 'finalize_session_worktree', lambda *a, **k: None)
    monkeypatch.setattr(sessions, '_linear_complete_session', lambda *a: None)
    monkeypatch.setitem(sys.modules, '_zellij_utils', types.SimpleNamespace(kill_session=killed.append))
    sessions.cmd_end(argparse.Namespace(session='abcd', force=False))
    assert killed == ['private-worker']
