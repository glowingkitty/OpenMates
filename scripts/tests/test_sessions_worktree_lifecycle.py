#!/usr/bin/env python3
"""Tests for sessions.py session worktree lifecycle helpers.

These tests keep the new agent worktree contract deterministic without
creating real repository worktrees. Git command execution is monkeypatched so
the lifecycle can be verified safely in a temporary state file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_lifecycle", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ensure_session_worktree_creates_deterministic_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({"locks": {}, "sessions": {"abcd": {"task": "work", "modified_files": []}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(sessions, "_current_git_sha", lambda cwd=None: "abc123def456")
    calls: list[tuple[str, ...]] = []

    def fake_run(cmd, cwd=None):
        calls.append(tuple(cmd))
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", fake_run)

    metadata = sessions.ensure_session_worktree("abcd")

    assert metadata["session_id"] == "abcd"
    assert metadata["base_commit"] == "abc123def456"
    assert metadata["status"] == "active"
    assert metadata["path"].endswith("agent-abcd")
    assert ("git", "worktree", "add", metadata["path"], "abc123def456") in calls

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["sessions"]["abcd"]["worktree"] == metadata


def test_default_agent_worktree_directory_stays_inside_project_root():
    sessions = load_sessions_module()

    assert sessions.AGENT_WORKTREES_DIR == sessions.PROJECT_ROOT / ".openmates-agent-worktrees"


def test_ensure_session_worktree_reuses_existing_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree_path = tmp_path / "worktrees" / "agent-abcd"
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "task": "work",
                        "modified_files": [],
                        "worktree": {
                            "session_id": "abcd",
                            "path": str(worktree_path),
                            "base_commit": "abc123def456",
                            "status": "active",
                            "created_at": "2026-07-26T00:00:00Z",
                            "last_active": "2026-07-26T00:00:00Z",
                        },
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(sessions, "_current_git_sha", lambda cwd=None: "newsha")
    monkeypatch.setattr(sessions, "_run_cmd", lambda cmd, cwd=None: (_ for _ in ()).throw(AssertionError(cmd)))

    metadata = sessions.ensure_session_worktree("abcd")

    assert metadata["base_commit"] == "abc123def456"
    assert metadata["path"] == str(worktree_path)


def test_cmd_worktree_reports_missing_session_without_traceback(monkeypatch, capsys):
    sessions = load_sessions_module()

    def missing_session(_session_id):
        raise RuntimeError("Session missing not found")

    monkeypatch.setattr(sessions, "ensure_session_worktree", missing_session)

    with pytest.raises(SystemExit) as exc_info:
        sessions.cmd_worktree(argparse.Namespace(worktree_action="ensure", session="missing"))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Session missing not found\n"
    assert "Traceback" not in captured.err
