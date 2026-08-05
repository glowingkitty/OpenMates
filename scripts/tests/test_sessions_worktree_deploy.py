#!/usr/bin/env python3
"""Tests for worktree-backed deploy planning in sessions.py.

The deploy integration helpers are intentionally tested without committing to
the real repository. They verify that the root index is no longer the source of
truth for a session's change set.
"""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_deploy", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worktree_changed_files_are_scoped_to_session_diff(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    def fake_run(cmd, cwd=None):
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return 0, "scripts/sessions.py\ndocs/example.md\n", ""
        if cmd == ["git", "ls-files", "--others", "--exclude-standard"]:
            return 0, "scripts/tests/new_test.py\n", ""
        return 0, "", ""

    monkeypatch.setattr(
        sessions,
        "_run_cmd",
        fake_run,
    )

    changed = sessions._worktree_changed_files({"path": str(worktree), "base_commit": "abc123"})

    assert changed == ["docs/example.md", "scripts/sessions.py", "scripts/tests/new_test.py"]


def test_worktree_patch_id_is_scoped_to_selected_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    included = tmp_path / "included.txt"
    excluded = tmp_path / "excluded.txt"
    included.write_text("included", encoding="utf-8")
    excluded.write_text("first", encoding="utf-8")
    commands = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"tracked diff", stderr=b"")

    monkeypatch.setattr(sessions.subprocess, "run", fake_run)
    monkeypatch.setattr(sessions, "_worktree_untracked_files", lambda _metadata: {"included.txt", "excluded.txt"})
    metadata = {"path": str(tmp_path), "base_commit": "abc123"}

    first = sessions._worktree_patch_id(metadata, ["tracked.py", "included.txt"])
    excluded.write_text("second", encoding="utf-8")
    second = sessions._worktree_patch_id(metadata, ["tracked.py", "included.txt"])

    assert first == second
    assert commands == [
        ["git", "diff", "--binary", "abc123", "--", "tracked.py"],
        ["git", "diff", "--binary", "abc123", "--", "tracked.py"],
    ]


def test_apply_worktree_diff_with_only_untracked_file_skips_tracked_diff(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "worktree"
    root = tmp_path / "root"
    source = worktree / "new.txt"
    source.parent.mkdir(parents=True)
    source.write_text("new file", encoding="utf-8")
    root.mkdir()
    subprocess_calls = []

    def fake_run(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_worktree_untracked_files", lambda _metadata: {"new.txt"})
    monkeypatch.setattr(sessions.subprocess, "run", fake_run)

    sessions._apply_worktree_diff_to_root(
        {"path": str(worktree), "base_commit": "abc123"},
        ["new.txt"],
    )

    assert subprocess_calls == []
    assert (root / "new.txt").read_text(encoding="utf-8") == "new file"


def test_session_deploy_files_ignore_foreign_root_dirty(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    session = {
        "modified_files": ["scripts/sessions.py", "docs/example.md"],
        "worktree": {"path": str(worktree), "base_commit": "abc123", "status": "active"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["scripts/sessions.py"])

    to_commit = sessions._session_deploy_files(session, exclude={"docs/example.md"})

    assert to_commit == ["scripts/sessions.py"]


def test_session_deploy_files_accept_legacy_worktree_tracking(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    session = {
        "modified_files": [
            ".openmates-agent-worktrees/agent-abcd/.openmates-agent-worktrees/agent-abcd/scripts/sessions.py"
        ],
        "worktree": {"path": str(tmp_path / "agent-abcd"), "base_commit": "abc123", "status": "active"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["scripts/sessions.py"])

    assert sessions._session_deploy_files(session, exclude=set()) == ["scripts/sessions.py"]


def test_merged_worktree_deploy_selects_only_changes_after_recorded_snapshot(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    unchanged = tmp_path / "unchanged.py"
    amended = tmp_path / "amended.py"
    unchanged.write_text("same\n", encoding="utf-8")
    amended.write_text("after\n", encoding="utf-8")
    session = {
        "modified_files": ["unchanged.py", "amended.py"],
        "worktree": {
            "path": str(tmp_path),
            "status": "merged",
            "merged_commit": "last-deploy",
            "root_applied_files": {
                "amended.py": {
                    "exists": True,
                    "sha256": "previous",
                    "executable": False,
                },
            },
        },
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["unchanged.py", "amended.py"])
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda _metadata, _files: {
            "unchanged.py": sessions._snapshot_file_states(tmp_path, ["unchanged.py"])["unchanged.py"],
            "amended.py": {"exists": True, "sha256": "previous", "executable": False},
        },
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["amended.py"]


def test_merged_worktree_deploy_selects_revert_and_deletion(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    reverted = tmp_path / "reverted.py"
    reverted.write_text("original\n", encoding="utf-8")
    session = {
        "modified_files": ["reverted.py", "added.py"],
        "worktree": {"path": str(tmp_path), "status": "merged", "merged_commit": "last-deploy"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: [])
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda _metadata, _files: {
            "reverted.py": {"exists": True, "sha256": "deployed-content", "executable": False},
            "added.py": {"exists": True, "sha256": "deployed-added", "executable": False},
        },
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["added.py", "reverted.py"]


def test_relative_repo_path_prefers_session_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    repo = tmp_path / "OpenMates"
    worktree = repo / ".openmates-agent-worktrees" / "agent-abcd"
    monkeypatch.setattr(sessions, "PROJECT_ROOT", repo)

    session = {"worktree": {"path": str(worktree), "base_commit": "abc123", "status": "active"}}

    assert sessions._relative_repo_path_for_session(worktree / "scripts" / "sessions.py", session) == "scripts/sessions.py"
    assert sessions._relative_repo_path_for_session(repo / "scripts" / "sessions.py", session) == "scripts/sessions.py"


def test_prune_stale_preserves_managed_worktree_sessions(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_hours_since", lambda _value: sessions.STALE_SESSION_HOURS + 1)
    data = {
        "sessions": {
            "plain": {"last_active": "old"},
            "bound": {"last_active": "old", "opencode_session_id": "ses_active"},
            "worktree": {"last_active": "old", "worktree": {"path": "/tmp/agent", "status": "active"}},
            "archived": {"last_active": "old", "worktree": {"path": "/tmp/archive", "status": "archived"}},
        }
    }

    assert sessions._prune_stale(data) == ["plain", "bound", "archived"]
    assert set(data["sessions"]) == {"worktree"}
