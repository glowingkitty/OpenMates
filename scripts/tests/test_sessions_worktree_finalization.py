#!/usr/bin/env python3
"""Tests for transactional worktree finalization at session end.

Session metadata must survive until a fully integrated physical worktree is
removed. Residual or unintegrated changes remain visible and block normal end.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_finalization", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_finalize_removes_fully_integrated_worktree_before_session(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    metadata = {
        "path": str(tmp_path / "agent-abcd"),
        "base_commit": "base",
        "status": "merged",
        "root_applied_patch_id": "patch",
        "merged_commit": "commit",
    }
    sessions_file.write_text(json.dumps({"sessions": {"abcd": {"worktree": metadata}}, "deploy_queue": []}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_worktree_pending_files", lambda _session: [])
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda commit, target: commit == "commit" and target == "origin/dev")
    order: list[str] = []
    monkeypatch.setattr(sessions, "_remove_git_worktree", lambda _metadata: order.append("worktree"))

    sessions.finalize_session_worktree("abcd", target_ref="origin/dev")

    assert order == ["worktree"]
    assert "abcd" not in json.loads(sessions_file.read_text(encoding="utf-8"))["sessions"]


def test_finalize_blocks_residual_changes_and_preserves_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    metadata = {
        "path": str(tmp_path / "agent-abcd"),
        "base_commit": "base",
        "status": "merged",
        "root_applied_patch_id": "deployed-patch",
        "merged_commit": "commit",
    }
    sessions_file.write_text(json.dumps({"sessions": {"abcd": {"worktree": metadata}}, "deploy_queue": []}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_worktree_pending_files", lambda _session: ["amended.py"])
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda _commit, _target: True)

    with pytest.raises(RuntimeError, match="residual"):
        sessions.finalize_session_worktree("abcd", target_ref="origin/dev")

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["sessions"]["abcd"]["worktree"]["status"] == "changes_pending"


def test_finalize_refuses_worktree_outside_managed_directory(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    managed = tmp_path / "managed"
    metadata = {
        "path": str(tmp_path / "unmanaged"),
        "base_commit": "base",
        "status": "merged",
        "root_applied_patch_id": "patch",
        "merged_commit": "commit",
    }
    sessions_file.write_text(json.dumps({"sessions": {"abcd": {"worktree": metadata}}, "deploy_queue": []}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_worktree_pending_files", lambda _session: [])
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda _commit, _target: True)

    with pytest.raises(RuntimeError, match="outside"):
        sessions.finalize_session_worktree("abcd", target_ref="origin/dev")

    assert "abcd" in json.loads(sessions_file.read_text(encoding="utf-8"))["sessions"]
