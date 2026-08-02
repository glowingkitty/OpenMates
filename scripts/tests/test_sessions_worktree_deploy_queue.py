#!/usr/bin/env python3
"""Tests for visible blocked deploy fallback metadata.

The record is stored in sessions.json so blocked worktree deploys remain
visible until a human resolves the root integration conflict and retries.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_deploy_queue", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_enqueue_deploy_records_visible_blocked_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"locks": {}, "sessions": {}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-07-26T00:00:00Z")

    item = sessions.enqueue_worktree_deploy("abcd", "fix: thing", "patch123", reason="lock busy")

    assert item["session_id"] == "abcd"
    assert item["status"] == "blocked"
    assert item["title"] == "fix: thing"
    assert item["patch_id"] == "patch123"
    assert item["reason"] == "lock busy"
    assert "rerun sessions.py deploy" in item["next_action"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["deploy_queue"] == [item]


def test_recorded_root_integration_is_idempotent(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({"sessions": {"abcd": {"worktree": {"path": "/tmp/agent-abcd"}}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    assert sessions._worktree_root_patch_is_applied("abcd", "patch123") is False
    sessions._record_worktree_root_patch("abcd", "patch123")
    assert sessions._worktree_root_patch_is_applied("abcd", "patch123") is True
    assert sessions._worktree_root_patch_is_applied("abcd", "different") is False


def test_resolve_deploy_removes_superseded_records_for_merged_session(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {"abcd": {"worktree": {"path": "/tmp/agent-abcd"}}},
                "deploy_queue": [
                    {"session_id": "abcd", "patch_id": "patch123"},
                    {"session_id": "abcd", "patch_id": "older"},
                    {"session_id": "other", "patch_id": "patch123"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    sessions._mark_worktree_deployed("abcd", "patch123", "commit456")

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["sessions"]["abcd"]["worktree"]["status"] == "merged"
    assert data["sessions"]["abcd"]["worktree"]["merged_commit"] == "commit456"
    assert data["deploy_queue"] == [{"session_id": "other", "patch_id": "patch123"}]


def test_pending_worktree_commit_is_used_only_for_exact_clean_retry(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {
            "sessions": {
                "abcd": {
                    "worktree": {
                        "root_applied_patch_id": "patch123",
                        "pending_commit": "commit456",
                        "pending_commit_patch_id": "patch123",
                    }
                }
            }
        },
    )
    monkeypatch.setattr(sessions, "_run_cmd", lambda _cmd: (0, "commit456\n", ""))
    monkeypatch.setattr(sessions, "_get_git_status_summary", lambda: {"unpushed": 1})

    assert sessions._pending_worktree_push_commit("abcd", "patch123", ["scripts/sessions.py"], []) == "commit456"
    assert sessions._pending_worktree_push_commit("abcd", "different", ["scripts/sessions.py"], []) == ""
    assert sessions._pending_worktree_push_commit(
        "abcd", "patch123", ["scripts/sessions.py"], ["scripts/sessions.py"]
    ) == ""


def test_pending_worktree_commit_accepts_matching_rebased_head(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    for base in (root, worktree):
        path = base / "scripts" / "sessions.py"
        path.parent.mkdir(parents=True)
        path.write_text("same content\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {
            "sessions": {
                "abcd": {
                    "worktree": {
                        "path": str(worktree),
                        "root_applied_patch_id": "patch123",
                        "pending_commit": "before-rebase",
                        "pending_commit_patch_id": "patch123",
                    }
                }
            }
        },
    )
    monkeypatch.setattr(sessions, "_run_cmd", lambda _cmd: (0, "after-rebase\n", ""))
    monkeypatch.setattr(sessions, "_get_git_status_summary", lambda: {"unpushed": 1})

    assert sessions._pending_worktree_push_commit("abcd", "patch123", ["scripts/sessions.py"], []) == "after-rebase"

    (root / "scripts" / "sessions.py").write_text("different\n", encoding="utf-8")
    assert sessions._pending_worktree_push_commit("abcd", "patch123", ["scripts/sessions.py"], []) == ""


def test_worktree_retry_blocks_root_drift_and_refreshes_safe_amendment(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    relative_path = "scripts/sessions.py"
    for base in (root, worktree):
        path = base / relative_path
        path.parent.mkdir(parents=True)
        path.write_text("first\n", encoding="utf-8")
    sessions_file.write_text(
        json.dumps({"sessions": {"abcd": {"worktree": {"path": str(worktree)}}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    sessions._record_worktree_root_patch("abcd", "patch-one", [relative_path])
    assert sessions._worktree_root_patch_action("abcd", "patch-one", [relative_path]) == "applied"

    (root / relative_path).write_text("foreign change\n", encoding="utf-8")
    assert sessions._worktree_root_patch_action("abcd", "patch-one", [relative_path]) == "conflict"

    (root / relative_path).write_text("first\n", encoding="utf-8")
    (worktree / relative_path).write_text("amended\n", encoding="utf-8")
    assert sessions._worktree_root_patch_action("abcd", "patch-two", [relative_path]) == "refresh"
    sessions._sync_worktree_files_to_root({"path": str(worktree)}, [relative_path])
    assert (root / relative_path).read_text(encoding="utf-8") == "amended\n"
