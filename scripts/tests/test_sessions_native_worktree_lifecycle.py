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
    def run_command(command, **_kwargs):
        if command[1] == "rev-parse":
            return 0, "upstream-commit\n", ""
        if command[-2:] == ["local-commit", "upstream-commit"]:
            return 1, "", "not integrated"
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    with pytest.raises(RuntimeError, match="HEAD is not integrated in origin/dev"):
        sessions.repair_worktree_routing("ses_parent")

    assert worktree["base_commit"] == "old-base"


def test_routing_repair_accepts_an_integrated_head_behind_origin(monkeypatch) -> None:
    sessions = load_sessions_module()
    worktree = {
        "path": "/repo/agent-abcd",
        "status": "merged",
        "base_commit": "old-base",
        "merged_commit": "deployed-head",
    }
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
            return 0, "newer-upstream\n", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "deployed-head")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.repair_worktree_routing("ses_parent")

    assert result["mode"] == "worktree_routed"
    assert worktree["status"] == "active"
    assert worktree["base_commit"] == "deployed-head"
    assert worktree["merged_commit"] == "deployed-head"


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
        if command[-2:] == ["upstream-head", "upstream-head"]:
            return 0, "", ""
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


def test_routing_repair_recovers_invalid_already_merged_worktree(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    (worktree_path / "preserved.txt").write_text("preserve me", encoding="utf-8")
    data = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_parent",
                "workspace_state": "recovery_needed",
                "auto_integration": {"status": "blocked", "block_reason": "stale checkpoint"},
                "worktree": {
                    "path": str(worktree_path),
                    "status": "merged",
                    "base_commit": "old",
                    "integration": {"status": "merged", "commit": "merged"},
                },
            }
        }
    }
    commands = []

    def run_command(command, **_kwargs):
        commands.append(command)
        if command[1] == "rev-parse":
            return 0, "current", ""
        if command[1:3] == ["status", "--porcelain"]:
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda path: Path(path) == worktree_path and any(command[1:3] == ["worktree", "add"] for command in commands))
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])
    monkeypatch.setattr(sessions, "refresh_worktree_base_after_fast_forward", lambda _worktree: "")

    result = sessions.repair_worktree_routing("ses_parent")

    archive = Path(data["sessions"]["abcd"]["worktree"]["recovered_from"])
    assert result["worktree_path"] == str(worktree_path)
    assert (archive / "preserved.txt").read_text(encoding="utf-8") == "preserve me"
    assert ["git", "worktree", "add", str(worktree_path), "current"] in commands
    assert data["sessions"]["abcd"]["workspace_state"] == "clean"
    assert "auto_integration" not in data["sessions"]["abcd"]


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


def test_opencode_session_reuse_keeps_resumes_but_rotates_new_preserved_tasks() -> None:
    sessions = load_sessions_module()

    merged = {
        "task": "old task",
        "worktree": {"status": "active", "integration": {"status": "merged"}},
    }
    checkpointed = {
        "task": "old task",
        "worktree": {"status": "active"},
        "auto_integration": {"checkpoint_ref": "refs/openmates/checkpoints/abcd"},
    }

    assert sessions.opencode_session_reusable_for_start(merged, "old task")
    assert not sessions.opencode_session_reusable_for_start(merged, "new task")
    assert not sessions.opencode_session_reusable_for_start(checkpointed, "new task")
    assert sessions.opencode_session_reusable_for_start({"worktree": {"status": "active"}})
    assert sessions.opencode_session_reusable_for_start({})


def test_register_session_rotates_preserved_chat_binding_atomically(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {
                "task": "old task",
                "opencode_session_id": "ses_parent",
                "opencode_top_level_session_id": "ses_parent",
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_prune_stale", lambda _data: [])
    monkeypatch.setattr(sessions, "_prune_stale_locks", lambda _data: [])
    monkeypatch.setattr(sessions, "_prune_checkpoint_lock_files", lambda _data: None)
    monkeypatch.setattr(sessions.secrets, "token_hex", lambda _size: "new1")

    session_id, _pruned, _locks, _updated, created = sessions.register_session_record(
        {"task": "new task", "opencode_session_id": None},
        "ses_parent",
        "old1",
    )

    assert created is True
    assert session_id == "new1"
    assert data["sessions"]["old1"]["opencode_session_id"] is None
    assert data["sessions"]["old1"]["opencode_top_level_session_id"] is None
    assert data["sessions"]["old1"]["rotated_opencode_session_id"] == "ses_parent"
    assert data["sessions"]["new1"]["opencode_session_id"] == "ses_parent"


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


def test_restore_routes_unmapped_child_session_through_parent_worktree(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "worktree": {"path": str(worktree_path), "status": "active", "base_commit": "base"}}}}

    def run_command(command, **_kwargs):
        if command[1:3] == ["status", "--porcelain"]:
            return 0, "", ""
        if command[1] == "rev-parse":
            return 0, "base", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_opencode_parent_chain", lambda session_id: ["ses_parent"] if session_id == "ses_child" else [])
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "base")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.prepare_opencode_restore("ses_child")

    assert result == {"cwd": str(worktree_path), "repository_session_id": "abcd", "advanced": False}


def test_restore_advances_clean_merged_worktree_and_routes_current_coordinator(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "worktree": {"path": str(worktree_path), "status": "merged", "base_commit": "old"}}}}
    commands = []

    def run_command(command, **_kwargs):
        commands.append(command)
        if command[1:3] == ["status", "--porcelain"]:
            return 0, "", ""
        if command[1] == "rev-parse":
            return 0, "new", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "old")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.prepare_opencode_restore("ses_parent")

    assert result == {"cwd": str(worktree_path), "repository_session_id": "abcd", "advanced": True}
    assert ["git", "switch", "--detach", "new"] in commands
    assert data["sessions"]["abcd"]["worktree"]["base_commit"] == "new"
    assert data["sessions"]["abcd"]["worktree"]["status"] == "active"


def test_restore_advances_dirty_active_worktree_when_upstream_paths_do_not_overlap(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "worktree": {"path": str(worktree_path), "status": "active", "base_commit": "old"}}}}

    def run_command(command, **_kwargs):
        if command[1:3] == ["status", "--porcelain"]:
            return 0, " M local-only.py", ""
        if command[1] == "rev-parse":
            return 0, "new", ""
        if command[1:3] == ["diff", "--name-only"]:
            return 0, "upstream-only.py", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "old")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.prepare_opencode_restore("ses_parent")

    assert result["advanced"] is True
    assert data["sessions"]["abcd"]["worktree"]["base_commit"] == "new"


def test_restore_preserves_dirty_active_worktree_when_upstream_paths_overlap(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "worktree": {"path": str(worktree_path), "status": "active", "base_commit": "old"}}}}

    def run_command(command, **_kwargs):
        if command[1:3] == ["status", "--porcelain"]:
            return 0, " M overlap.py", ""
        if command[1] == "rev-parse":
            return 0, "new", ""
        if command[1:3] == ["diff", "--name-only"]:
            return 0, "overlap.py", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "old")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.prepare_opencode_restore("ses_parent")

    assert result == {
        "cwd": str(worktree_path),
        "repository_session_id": "abcd",
        "advanced": False,
        "preserved_conflicts": ["overlap.py"],
    }


def test_restore_archives_dirty_merged_worktree_when_upstream_paths_overlap(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree_path = tmp_path / "agent-abcd"
    worktree_path.mkdir()
    (worktree_path / "overlap.py").write_text("preserved", encoding="utf-8")
    data = {"sessions": {"abcd": {"opencode_session_id": "ses_parent", "worktree": {"path": str(worktree_path), "status": "merged", "base_commit": "old", "integration": {"status": "merged"}}}}}
    commands = []

    def run_command(command, **_kwargs):
        commands.append(command)
        if command[1:3] == ["status", "--porcelain"]:
            return 0, " M overlap.py", ""
        if command[1] == "rev-parse":
            return 0, "new", ""
        if command[1:3] == ["diff", "--name-only"]:
            return 0, "overlap.py", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "old")
    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [])

    result = sessions.prepare_opencode_restore("ses_parent")

    archive = Path(data["sessions"]["abcd"]["worktree"]["recovered_from"])
    assert result["advanced"] is True
    assert (archive / "overlap.py").read_text(encoding="utf-8") == "preserved"
    assert ["git", "worktree", "add", str(worktree_path), "new"] in commands


def test_managed_worktrees_cannot_nest(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    assert sessions.is_valid_managed_worktree_path(managed / "agent-abcd")
    assert not sessions.is_valid_managed_worktree_path(managed / "agent-abcd" / "managed" / "agent-efgh")
