#!/usr/bin/env python3
"""Contracts for explicit canonical-root to session-worktree handoff."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_root_handoff", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_root_handoff_rejects_escape_secret_and_control_plane_paths() -> None:
    sessions = load_sessions_module()

    for path in ("../outside", "/tmp/outside", ".env", ".env.local", "config.json", "scripts/sessions.py"):
        with pytest.raises(ValueError):
            sessions._normalize_root_handoff_path(path)


def test_root_dirty_lists_safe_metadata_without_contents(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "release.md").write_text("private draft contents", encoding="utf-8")
    (root / "config.json").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: {"docs/release.md", "config.json"})
    monkeypatch.setattr(sessions, "_get_staged_files", lambda **_kwargs: {"docs/release.md"})

    def run_command(command, **_kwargs):
        if command[1:3] == ["ls-files", "--others"]:
            return 0, "config.json\n", ""
        if command[1:3] == ["diff", "--name-only"]:
            return 0, "docs/release.md\n", ""
        if command[1:3] == ["rev-parse", "origin/dev"]:
            return 0, "abc123\n", ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    result = sessions.list_root_dirty_files(path_prefix="docs")

    assert result["files"] == [{
        "path": "docs/release.md",
        "state": "modified",
        "staged": True,
        "differs_from_origin": True,
    }]
    assert "private draft contents" not in str(result)


def test_import_root_dirty_file_copies_and_records_provenance(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktrees = tmp_path / "managed"
    worktree = worktrees / "agent-abcd"
    (root / "docs").mkdir(parents=True)
    (worktree / "docs").mkdir(parents=True)
    source = root / "docs" / "release.md"
    source.write_text("root draft", encoding="utf-8")
    destination = worktree / "docs" / "release.md"
    destination.write_text("base", encoding="utf-8")
    data = {"sessions": {"abcd": {"modified_files": [], "worktree": {"path": str(worktree)}}}}
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", worktrees)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_session_is_control_plane_repo", lambda _session: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _path=None: "root-head")
    monkeypatch.setattr(
        sessions,
        "_get_dirty_files",
        lambda *, checkout_root=None: {"docs/release.md"} if checkout_root == root else set(),
    )

    result = sessions.import_root_dirty_file("docs/release.md", session_id="abcd")

    assert result["path"] == "docs/release.md"
    assert destination.read_text(encoding="utf-8") == "root draft"
    assert data["sessions"]["abcd"]["modified_files"] == ["docs/release.md"]
    assert data["sessions"]["abcd"]["workspace_state"] == "changes_pending"
    assert data["sessions"]["abcd"]["worktree"]["root_imports"][-1]["root_head"] == "root-head"


def test_import_root_dirty_file_requires_dirty_root_and_clean_target(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktrees = tmp_path / "managed"
    worktree = worktrees / "agent-abcd"
    (root / "docs").mkdir(parents=True)
    (worktree / "docs").mkdir(parents=True)
    (root / "docs" / "release.md").write_text("root", encoding="utf-8")
    data = {"sessions": {"abcd": {"worktree": {"path": str(worktree)}}}}
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", worktrees)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_session_is_control_plane_repo", lambda _session: True)
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: set())
    with pytest.raises(RuntimeError, match="not currently dirty"):
        sessions.import_root_dirty_file("docs/release.md", session_id="abcd")

    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: {"docs/release.md"})
    with pytest.raises(RuntimeError, match="already has local changes"):
        sessions.import_root_dirty_file("docs/release.md", session_id="abcd")
