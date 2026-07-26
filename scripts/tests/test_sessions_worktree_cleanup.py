#!/usr/bin/env python3
"""Tests for cleaning and archiving agent worktrees.

Dirty idle worktrees must become visible archive records instead of being
silently committed, pushed, or discarded.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_cleanup", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cleanup_archives_dirty_idle_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    worktree = tmp_path / "worktrees" / "agent-abcd"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "modified_files": ["scripts/sessions.py"],
                        "worktree": {"path": str(worktree), "status": "active", "last_active": "2026-07-25T00:00:00Z"},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_hours_since", lambda _value: 13)
    monkeypatch.setattr(sessions, "_worktree_has_changes", lambda _metadata: True)

    archived = sessions.cleanup_session_worktrees(idle_hours=12)

    assert archived == ["abcd"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["sessions"]["abcd"]["worktree"]["status"] == "archived"
    assert data["worktree_archive"][0]["session_id"] == "abcd"


def test_cleanup_removes_clean_merged_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    worktree = tmp_path / "worktrees" / "agent-abcd"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "modified_files": [],
                        "worktree": {"path": str(worktree), "status": "merged", "last_active": "2026-07-26T00:00:00Z"},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_worktree_has_changes", lambda _metadata: False)
    removed: list[str] = []
    monkeypatch.setattr(sessions, "_remove_git_worktree", lambda metadata: removed.append(metadata["path"]))

    archived = sessions.cleanup_session_worktrees(idle_hours=12)

    assert archived == []
    assert removed == [str(worktree)]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert "abcd" not in data["sessions"]
