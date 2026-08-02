#!/usr/bin/env python3
"""Tests for OpenCode multi-file edit leases.

Purpose: keep concurrent execute-mode agents from editing the same source file
at the same time while preserving sessions.py as the single coordination store.
The tests use a temporary sessions.json and never touch real agent sessions.
Run: python3 -m pytest scripts/tests/test_sessions_edit_leases.py.
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
    spec = importlib.util.spec_from_file_location("openmates_sessions_edit_leases", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sessions_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "locks": {},
                "edit_leases": {},
                "sessions": {
                    "a111": {"task": "first", "opencode_session_id": "oc-a", "modified_files": [], "last_active": "2026-08-01T00:00:00Z"},
                    "b222": {"task": "second", "opencode_session_id": "oc-b", "modified_files": [], "last_active": "2026-08-01T00:00:00Z"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_edit_lease_blocks_other_opencode_session(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file)
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-08-01T00:01:00Z")
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 1)

    result = sessions.acquire_edit_leases(opencode_session_id="oc-a", files=[str(PROJECT_ROOT / "scripts/sessions.py")])

    assert result == {"session_id": "a111", "files": ["scripts/sessions.py"]}
    with pytest.raises(RuntimeError, match="Another live agent has an edit lease"):
        sessions.acquire_edit_leases(opencode_session_id="oc-b", files=[str(PROJECT_ROOT / "scripts/sessions.py")])

    release = sessions.release_edit_leases(opencode_session_id="oc-a", files=[str(PROJECT_ROOT / "scripts/sessions.py")])

    assert release == {"session_id": "a111", "files": ["scripts/sessions.py"]}
    second = sessions.acquire_edit_leases(opencode_session_id="oc-b", files=[str(PROJECT_ROOT / "scripts/sessions.py")])
    assert second == {"session_id": "b222", "files": ["scripts/sessions.py"]}


def test_edit_lease_respects_manual_write_claim(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file)
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    data["sessions"]["a111"]["writing"] = "scripts/sessions.py"
    sessions_file.write_text(json.dumps(data) + "\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-08-01T00:01:00Z")
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 1)

    with pytest.raises(RuntimeError, match="manual WRITING claim"):
        sessions.acquire_edit_leases(opencode_session_id="oc-b", files=[str(PROJECT_ROOT / "scripts/sessions.py")])


def test_edit_lease_normalizes_session_worktree_paths(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file)
    worktree = tmp_path / "worktrees" / "agent-a111"
    worktree_file = worktree / "frontend" / "example.ts"
    worktree_file.parent.mkdir(parents=True)
    worktree_file.write_text("export {};\n", encoding="utf-8")
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    data["sessions"]["a111"]["worktree"] = {"path": str(worktree), "status": "active"}
    sessions_file.write_text(json.dumps(data) + "\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-08-01T00:01:00Z")
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 1)

    result = sessions.acquire_edit_leases(opencode_session_id="oc-a", files=[str(worktree_file)])

    assert result == {"session_id": "a111", "files": ["frontend/example.ts"]}


def test_edit_lease_normalizes_worktree_nested_inside_project_root(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    repo = tmp_path / "OpenMates"
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file)
    worktree = repo / ".openmates-agent-worktrees" / "agent-a111"
    worktree_file = worktree / "scripts" / "sessions.py"
    worktree_file.parent.mkdir(parents=True)
    worktree_file.write_text("# test\n", encoding="utf-8")
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    data["sessions"]["a111"]["worktree"] = {"path": str(worktree), "status": "active"}
    sessions_file.write_text(json.dumps(data) + "\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "PROJECT_ROOT", repo)
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-08-01T00:01:00Z")
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 1)

    result = sessions.acquire_edit_leases(opencode_session_id="oc-a", files=[str(worktree_file)])

    assert result == {"session_id": "a111", "files": ["scripts/sessions.py"]}
    saved = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert saved["sessions"]["a111"]["modified_files"] == ["scripts/sessions.py"]
    assert list(saved["edit_leases"]) == ["scripts/sessions.py"]


def test_session_state_migrates_legacy_worktree_paths(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "a111": {
                        "modified_files": [
                            ".openmates-agent-worktrees/agent-a111/scripts/sessions.py",
                            ".openmates-agent-worktrees/agent-a111/.openmates-agent-worktrees/agent-a111/scripts/sessions.py",
                            "scripts/sessions.py",
                        ],
                        "writing": ".openmates-agent-worktrees/agent-a111/docs/example.md",
                    }
                },
                "edit_leases": {
                    ".openmates-agent-worktrees/agent-a111/scripts/sessions.py": {
                        "session_id": "a111",
                        "last_updated": "2026-08-01T00:00:00Z",
                    },
                    "scripts/sessions.py": {
                        "session_id": "a111",
                        "last_updated": "2026-08-01T00:01:00Z",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    data = sessions._load_sessions()

    assert data["sessions"]["a111"]["modified_files"] == ["scripts/sessions.py"]
    assert data["sessions"]["a111"]["writing"] == "docs/example.md"
    assert list(data["edit_leases"]) == ["scripts/sessions.py"]
    assert data["edit_leases"]["scripts/sessions.py"]["last_updated"] == "2026-08-01T00:01:00Z"
