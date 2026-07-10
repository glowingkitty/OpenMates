"""Unit tests for OpenCode-only stale-read edit protection.

Purpose: verify hash comparisons prevent stale editor writes across sessions.
Scope: redirects local runtime state to tmp_path and never reads OpenCode data.
Privacy: state contains only relative paths, hashes, and timestamps.
Run: python3 -m pytest scripts/tests/test_sessions_stale_read.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PY = ROOT / "scripts" / "sessions.py"


@pytest.fixture
def sessions_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("sessions_stale_read", SESSIONS_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sessions_stale_read"] = module
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "OPENCODE_STALE_READ_STATE_FILE", tmp_path / ".opencode" / "stale-read-state.json")
    monkeypatch.setattr(module, "OPENCODE_STALE_READ_LOCK_FILE", tmp_path / ".opencode" / "stale-read-state.lock")
    return module


def test_changed_file_blocks_current_opencode_session(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("before\n", encoding="utf-8")

    sessions_module.record_opencode_stale_read("ses-current", target)
    target.write_text("after\n", encoding="utf-8")

    assert sessions_module.opencode_stale_read_error("ses-current", target) == (
        "BLOCKED: src/example.py changed since this OpenCode session read it. Re-read the file before editing."
    )


def test_unchanged_file_is_editable(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("unchanged\n", encoding="utf-8")

    sessions_module.record_opencode_stale_read("ses-current", target)

    assert sessions_module.opencode_stale_read_error("ses-current", target) is None


def test_other_session_hash_does_not_block_current_session(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("before\n", encoding="utf-8")
    sessions_module.record_opencode_stale_read("ses-other", target)
    target.write_text("after\n", encoding="utf-8")

    assert sessions_module.opencode_stale_read_error("ses-current", target) is None


def test_sync_refreshes_current_session_hash_after_edit(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("before\n", encoding="utf-8")
    sessions_module.record_opencode_stale_read("ses-current", target)
    target.write_text("after\n", encoding="utf-8")

    sessions_module.sync_opencode_stale_read("ses-current", target)

    assert sessions_module.opencode_stale_read_error("ses-current", target) is None


def test_paths_are_repository_relative_and_external_paths_are_ignored(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("content\n", encoding="utf-8")

    assert sessions_module.normalize_opencode_stale_read_path(target) == "src/example.py"
    assert sessions_module.normalize_opencode_stale_read_path("./src/example.py") == "src/example.py"
    assert sessions_module.normalize_opencode_stale_read_path(tmp_path.parent / "outside.py") is None


def test_expired_opencode_state_is_pruned(sessions_module, tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("content\n", encoding="utf-8")
    state = {
        "version": 1,
        "sessions": {
            "ses-expired": {"last_active": "2000-01-01T00:00:00+00:00", "files": {"example.py": {"sha256": "old"}}},
        },
    }
    sessions_module.OPENCODE_STALE_READ_STATE_FILE.parent.mkdir()
    sessions_module.OPENCODE_STALE_READ_STATE_FILE.write_text(__import__("json").dumps(state), encoding="utf-8")

    sessions_module.record_opencode_stale_read("ses-current", target)
    loaded = __import__("json").loads(sessions_module.OPENCODE_STALE_READ_STATE_FILE.read_text(encoding="utf-8"))

    assert set(loaded["sessions"]) == {"ses-current"}
