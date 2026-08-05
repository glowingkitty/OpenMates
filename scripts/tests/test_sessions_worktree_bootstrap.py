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
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
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
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, cwd=None, timeout=None: (1, "", "offline cache miss"))

    result = sessions.bootstrap_session_worktree(worktree)

    assert result["status"] == "failed"
    assert result["reason"] == "dependency_install_failed"
    assert "offline cache miss" in result["message"]


def test_shared_runtime_resources_are_linked_into_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    reports = root / "logs" / "nightly-reports"
    reports.mkdir(parents=True)
    worktree.mkdir()
    (root / ".env").write_text("EXAMPLE=value\n", encoding="utf-8")
    (reports / "stale-code.json").write_text('{"findings": []}\n', encoding="utf-8")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    result = sessions.link_shared_worktree_resources(worktree)

    assert result == [".env", "logs/nightly-reports"]
    assert (worktree / ".env").is_symlink()
    assert (worktree / ".env").resolve() == root / ".env"
    assert (worktree / "logs" / "nightly-reports").is_symlink()
    assert (worktree / "logs" / "nightly-reports" / "stale-code.json").read_text(encoding="utf-8") == '{"findings": []}\n'


def test_shared_runtime_linking_refuses_to_replace_local_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    (root / ".env").write_text("ROOT=value\n", encoding="utf-8")
    (worktree / ".env").write_text("LOCAL=value\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    with pytest.raises(RuntimeError, match="Refusing to replace existing worktree runtime resource"):
        sessions.link_shared_worktree_resources(worktree)

    assert (worktree / ".env").read_text(encoding="utf-8") == "LOCAL=value\n"


def test_shared_runtime_links_survive_resources_created_later(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    result = sessions.link_shared_worktree_resources(worktree)

    assert result == [".env", "logs/nightly-reports"]
    assert (worktree / ".env").is_symlink()
    assert (worktree / "logs" / "nightly-reports").is_symlink()
    (root / ".env").write_text("LATER=value\n", encoding="utf-8")
    (root / "logs" / "nightly-reports").mkdir(parents=True)
    (root / "logs" / "nightly-reports" / "stale-code.json").write_text("{}\n", encoding="utf-8")
    assert (worktree / ".env").read_text(encoding="utf-8") == "LATER=value\n"
    assert (worktree / "logs" / "nightly-reports" / "stale-code.json").read_text(encoding="utf-8") == "{}\n"
