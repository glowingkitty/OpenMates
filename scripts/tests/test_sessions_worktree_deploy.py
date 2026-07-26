#!/usr/bin/env python3
"""Tests for worktree-backed deploy planning in sessions.py.

The deploy integration helpers are intentionally tested without committing to
the real repository. They verify that the root index is no longer the source of
truth for a session's change set.
"""

from __future__ import annotations

import importlib.util
import sys
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
