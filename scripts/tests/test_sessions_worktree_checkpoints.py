#!/usr/bin/env python3
# contract-test-file: tooling
"""Durable checkpoint contracts for forgotten mutating OpenCode chats.

The fixtures use isolated Git repositories. Checkpoint creation must preserve
both the source worktree and dev while storing an exact local recovery commit.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_checkpoints", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def create_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "tests@openmates.invalid")
    git(root, "config", "user.name", "OpenMates Tests")
    (root / ".gitignore").write_text(".openmates-agent-worktrees/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    base = git(root, "rev-parse", "HEAD")
    worktree = tmp_path / "agent-abcd"
    git(root, "worktree", "add", "--detach", str(worktree), base)
    (worktree / "tracked.txt").write_text("after\n", encoding="utf-8")
    return root, worktree, base


def test_idle_mutating_session_creates_exact_local_checkpoint(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root, worktree, base = create_fixture(tmp_path)
    managed = root / ".openmates-agent-worktrees"
    managed.mkdir()
    data = {
        "sessions": {
            "abcd": {
                "mode": "bug",
                "task": "repair lifecycle",
                "opencode_session_id": "ses-parent",
                "auto_integration_policy": "enabled",
                "binding_mode": "worktree_routed",
                "modified_files": ["tracked.txt"],
                "worktree": {
                    "path": str(worktree),
                    "base_commit": base,
                    "status": "active",
                },
            }
        },
        "edit_leases": {},
    }
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", root / ".claude" / "checkpoint-locks")
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    root_head = git(root, "rev-parse", "HEAD")
    source_status = git(worktree, "status", "--porcelain")

    result = sessions.checkpoint_session_worktree("ses-parent", event="idle")

    checkpoint = data["sessions"]["abcd"]["auto_integration"]
    assert result["status"] == "checkpointed"
    assert checkpoint["status"] == "checkpointed"
    assert checkpoint["files"] == ["tracked.txt"]
    assert checkpoint["patch_id"]
    assert checkpoint["checkpoint_commit"] == git(root, "rev-parse", "refs/openmates/checkpoints/abcd")
    assert data["sessions"]["abcd"]["workspace_state"] == "checkpointed"
    assert git(root, "rev-parse", "HEAD") == root_head
    assert git(worktree, "status", "--porcelain") == source_status
    assert git(root, "show", f"{checkpoint['checkpoint_commit']}:tracked.txt") == "after"
    assert sessions.select_auto_integration_candidates() == []
    submission = sessions.submit_ready_worktree(
        "abcd", patch_id=checkpoint["patch_id"], checkpoint_commit=checkpoint["checkpoint_commit"],
    )
    assert submission["patch_id"] == checkpoint["patch_id"]
    assert data["sessions"]["abcd"]["auto_integration"]["status"] == "eligible"
    with pytest.raises(RuntimeError, match="stale"):
        sessions.submit_ready_worktree("abcd", patch_id="stale", checkpoint_commit=checkpoint["checkpoint_commit"])



def test_checkpoint_preserves_hold_and_separates_workspace_state(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "mode": "feature",
                "opencode_session_id": "ses-parent",
                "auto_integration_policy": "enabled",
                "binding_mode": "worktree_routed",
                "worktree": {
                    "path": "/repo/agent-abcd",
                    "status": "active",
                },
                "auto_integration": {"hold": True},
            }
        },
        "edit_leases": {},
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", Path("/tmp/openmates-test-checkpoint-locks"))
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["feature.py"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")
    monkeypatch.setattr(sessions, "_create_worktree_checkpoint_commit", lambda *_args: "commit-1")

    result = sessions.checkpoint_session_worktree("ses-parent", event="closed")

    assert result["status"] == "held"
    assert data["sessions"]["abcd"]["workspace_state"] == "held"
    assert data["sessions"]["abcd"]["auto_integration"]["checkpoint_commit"] == "commit-1"


def test_question_and_child_sessions_do_not_checkpoint(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "question": {"mode": "question", "opencode_session_id": "ses-question"},
            "parent": {"mode": "bug", "opencode_session_id": "ses-parent"},
        }
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)

    assert sessions.checkpoint_session_worktree("ses-question", event="idle")["status"] == "skipped"
    assert sessions.checkpoint_session_worktree("ses-child", event="idle")["status"] == "skipped"


def test_legacy_session_cannot_checkpoint(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "legacy": {
                "mode": "bug",
                "opencode_session_id": "ses-legacy",
                "binding_mode": "legacy_grandfathered",
                "worktree": {
                    "path": "/repo/agent-legacy",
                },
            }
        }
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)

    result = sessions.checkpoint_session_worktree("ses-legacy", event="idle")

    assert result == {"status": "skipped", "reason": "automatic_recovery_not_enabled"}


def test_compare_and_swap_delete_preserves_newer_checkpoint(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root, _worktree, old_commit = create_fixture(tmp_path)
    (root / "tracked.txt").write_text("newer checkpoint\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "newer checkpoint")
    newer_commit = git(root, "rev-parse", "HEAD")
    checkpoint_ref = sessions._worktree_checkpoint_ref("abcd")
    git(root, "update-ref", checkpoint_ref, newer_commit)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    sessions._delete_worktree_checkpoint_ref("abcd", expected_commit=old_commit)

    assert git(root, "rev-parse", checkpoint_ref) == newer_commit


def test_checkpoint_failure_records_recovery_reason(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "abcd": {
                "mode": "bug",
                "opencode_session_id": "ses-parent",
                "auto_integration_policy": "enabled",
                "binding_mode": "worktree_routed",
                "worktree": {"path": "/repo/agent-abcd", "status": "active"},
            }
        },
        "edit_leases": {},
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["safe.py"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")
    monkeypatch.setattr(
        sessions,
        "_create_worktree_checkpoint_commit",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic checkpoint failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic checkpoint failure"):
        sessions.checkpoint_session_worktree("ses-parent", event="idle")

    auto = data["sessions"]["abcd"]["auto_integration"]
    assert data["sessions"]["abcd"]["workspace_state"] == "recovery_needed"
    assert auto["block_reason"] == "checkpoint_failed:synthetic checkpoint failure"


def test_prune_checkpoint_lock_files_removes_only_old_orphans(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    locks = tmp_path / "checkpoint-locks"
    locks.mkdir()
    active = locks / "abcd.lock"
    stale_orphan = locks / "stale.lock"
    recent_orphan = locks / "recent.lock"
    for lock in (active, stale_orphan, recent_orphan):
        lock.write_text("", encoding="utf-8")
    old_mtime = 1_700_000_000
    recent_mtime = old_mtime + 25 * 60 * 60
    monkeypatch.setattr(sessions.time, "time", lambda: recent_mtime)
    for lock in (active, stale_orphan):
        lock.touch()
        sessions.os.utime(lock, (old_mtime, old_mtime))
    sessions.os.utime(recent_orphan, (recent_mtime, recent_mtime))

    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", locks)

    assert sessions._prune_checkpoint_lock_files({"sessions": {"abcd": {}}}) == ["stale"]
    assert active.exists()
    assert not stale_orphan.exists()
    assert recent_orphan.exists()
