#!/usr/bin/env python3
"""Red contracts for deterministic session-worktree bootstrap.

The tests isolate sessions.py state and command execution so bootstrap behavior
can be implemented without modifying root dependencies or generated artifacts.
Real package installation remains covered by the isolated runtime verifier.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_bootstrap", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bootstrap_is_worktree_local_and_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    calls: list[tuple[tuple[str, ...], Path | None]] = []

    def fake_run(command, cwd=None, timeout=None):
        calls.append((tuple(command), Path(cwd) if cwd else None))
        return 0, "", ""

    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run)

    first = sessions.bootstrap_session_worktree(worktree)
    second = sessions.bootstrap_session_worktree(worktree)

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert calls
    assert all(cwd == worktree for _, cwd in calls)
    assert all(str(root / "node_modules") not in " ".join(command) for command, _ in calls)
    assert "--config.engine-strict=false" in calls[0][0]


def test_bootstrap_failure_never_reports_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, cwd=None, timeout=None: (1, "", "offline cache miss"))

    result = sessions.bootstrap_session_worktree(worktree)

    assert result["status"] == "failed"
    assert result["reason"] == "dependency_install_failed"
    assert "offline cache miss" in result["message"]
