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
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda path: [".env"] if path == "/repo/agent-abcd" else [])

    result = sessions.repair_worktree_routing("ses_parent")

    assert result == {
        "session_id": "abcd",
        "mode": "worktree_routed",
        "worktree_path": "/repo/agent-abcd",
        "shared_runtime_resources": [".env"],
    }
    assert data["sessions"]["abcd"]["binding_mode"] == "worktree_routed"
    assert data["sessions"]["abcd"]["last_active"] == "now"


def test_routing_repair_refreshes_a_fast_forwarded_worktree_base(monkeypatch) -> None:
    sessions = load_sessions_module()
    worktree = {"path": "/repo/agent-abcd", "status": "active", "base_commit": "old-base"}
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "worktree_routed",
                "worktree": worktree,
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "new-head")
    monkeypatch.setattr(
        sessions,
        "_run_cmd",
        lambda command, **_kwargs: (0, "new-head\n" if command[1] == "rev-parse" else "", ""),
    )
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    sessions.repair_worktree_routing("ses_parent")

    assert worktree["base_commit"] == "new-head"


def test_routing_repair_preserves_an_unintegrated_local_commit(monkeypatch) -> None:
    sessions = load_sessions_module()
    worktree = {"path": "/repo/agent-abcd", "status": "active", "base_commit": "old-base"}
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "worktree_routed",
                "worktree": worktree,
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "local-commit")
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "upstream-commit\n", ""))
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    with pytest.raises(RuntimeError, match="HEAD does not match origin/dev"):
        sessions.repair_worktree_routing("ses_parent")

    assert worktree["base_commit"] == "old-base"


def test_routing_repair_preserves_a_divergent_recorded_base(monkeypatch) -> None:
    sessions = load_sessions_module()
    worktree = {"path": "/repo/agent-abcd", "status": "active", "base_commit": "divergent-base"}
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "worktree_routed",
                "worktree": worktree,
            }
        }
    }

    def run_command(command, **_kwargs):
        if command[1] == "rev-parse":
            return 0, "upstream-head\n", ""
        return 1, "", "not an ancestor"

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "upstream-head")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    with pytest.raises(RuntimeError, match="diverged from its recorded base"):
        sessions.repair_worktree_routing("ses_parent")

    assert worktree["base_commit"] == "divergent-base"


def test_routing_repair_reactivates_merged_worktree_after_deploy(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "worktree_routed",
                "worktree": {"path": "/repo/agent-abcd", "status": "merged", "merged_commit": "abc123456789"},
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [".env", "logs/nightly-reports"])

    result = sessions.repair_worktree_routing("ses_parent")

    assert result["session_id"] == "abcd"
    assert data["sessions"]["abcd"]["worktree"]["status"] == "active"


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


def test_routing_repair_does_not_commit_metadata_when_runtime_linking_fails(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "agent-abcd"
    root.mkdir()
    worktree.mkdir()
    (root / ".env").write_text("ROOT=value\n", encoding="utf-8")
    (worktree / ".env").write_text("LOCAL=value\n", encoding="utf-8")
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "binding_mode": "pending",
                "last_active": "old",
                "worktree": {"path": str(worktree), "status": "active", "last_active": "old"},
            }
        }
    }
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)

    with pytest.raises(RuntimeError, match="Refusing to replace existing worktree runtime resource"):
        sessions.repair_worktree_routing("ses_parent")

    assert data["sessions"]["abcd"]["binding_mode"] == "pending"
    assert data["sessions"]["abcd"]["last_active"] == "old"
    assert data["sessions"]["abcd"]["worktree"]["last_active"] == "old"


def test_existing_opencode_session_is_reused_after_restart() -> None:
    sessions = load_sessions_module()
    existing = {"task": "continue work", "worktree": {"path": "/repo/agent-abcd", "status": "active"}}
    data = {"sessions": {"abcd": {**existing, "opencode_session_id": "ses_parent"}}}

    result = sessions.session_for_opencode(data, "ses_parent")

    assert result is not None
    assert result[0] == "abcd"
    assert result[1]["worktree"]["path"] == "/repo/agent-abcd"


def test_start_refresh_restores_half_bound_opencode_session() -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": None,
                "opencode_top_level_session_id": "ses_parent",
                "binding_mode": "pending",
                "last_active": "old",
            }
        }
    }

    sessions.refresh_existing_session_for_start(
        data,
        "abcd",
        "ses_parent",
        mode="testing",
        tags=["test"],
        task="continue verification",
        repo_kind="control_plane",
        now="now",
    )

    session = data["sessions"]["abcd"]
    assert session["opencode_session_id"] == "ses_parent"
    assert session["opencode_top_level_session_id"] == "ses_parent"
    assert session["binding_mode"] == "pending"
    assert session["last_active"] == "now"
    assert sessions._resolve_session_id(data, opencode_session_id="ses_parent") == "abcd"


def test_start_refresh_does_not_steal_newer_opencode_binding() -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "stale": {
                "opencode_session_id": None,
                "opencode_top_level_session_id": "ses_parent",
            },
            "current": {
                "opencode_session_id": "ses_parent",
                "opencode_top_level_session_id": "ses_parent",
            },
        }
    }

    with pytest.raises(RuntimeError, match="binding changed while starting"):
        sessions.refresh_existing_session_for_start(
            data,
            "stale",
            "ses_parent",
            mode="testing",
            tags=["test"],
            task="continue verification",
            repo_kind="control_plane",
        )

    assert data["sessions"]["stale"]["opencode_session_id"] is None
    assert data["sessions"]["current"]["opencode_session_id"] == "ses_parent"


def test_merged_opencode_session_is_reused_for_start() -> None:
    sessions = load_sessions_module()

    assert sessions.opencode_session_reusable_for_start({"worktree": {"status": "merged"}})
    assert sessions.opencode_session_reusable_for_start({"worktree": {"status": "active"}})
    assert sessions.opencode_session_reusable_for_start({})


def test_managed_worktrees_cannot_nest(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    assert sessions.is_valid_managed_worktree_path(managed / "agent-abcd")
    assert not sessions.is_valid_managed_worktree_path(managed / "agent-abcd" / "managed" / "agent-efgh")
