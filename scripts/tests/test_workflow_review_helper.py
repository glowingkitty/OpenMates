"""Tests for explicit, OpenCode-only workflow review collection.

Purpose: ensure reports contain aggregate evidence without chat contents.
Scope: temporary SQLite fixtures and local report paths only.
Privacy: sentinel values prove titles, IDs, and raw tool data are excluded.
Run: python3 -m pytest scripts/tests/test_workflow_review_helper.py.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / "scripts" / "_workflow_review_helper.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("workflow_review_helper", HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["workflow_review_helper"] = module
    spec.loader.exec_module(module)
    return module


def create_opencode_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE session (id TEXT, directory TEXT, parent_id TEXT, title TEXT, time_created INTEGER, time_updated INTEGER);"
        "CREATE TABLE part (session_id TEXT, data TEXT);"
    )
    connection.executemany(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("ses-top-secret", str(ROOT), None, "PRIVATE_SESSION_TITLE", 1_783_030_000_000, 1_783_116_400_000),
            ("ses-top-empty", str(ROOT), "", "PRIVATE_EMPTY_PARENT_TITLE", 1_783_030_000_000, 1_783_116_400_000),
            ("ses-child", str(ROOT), "ses-top-secret", "PRIVATE_CHILD_TITLE", 1_783_030_000_000, 1_783_116_400_000),
            ("ses-other", "/other", None, "OTHER", 1_783_030_000_000, 1_783_116_400_000),
        ],
    )
    connection.execute(
        "INSERT INTO part VALUES (?, ?)",
        ("ses-top-secret", json.dumps({"type": "tool", "tool": "bash", "state": {"status": "error", "error": "PRIVATE_ERROR timeout"}})),
    )
    connection.commit()
    connection.close()


def test_query_uses_top_level_opencode_sessions_and_redacts_tool_errors(tmp_path, monkeypatch) -> None:
    helper = load_helper()
    database = tmp_path / "opencode.db"
    create_opencode_fixture(database)
    monkeypatch.setattr(helper, "OPENCODE_DB_PATH", database)
    monkeypatch.setattr(helper, "PROJECT_ROOT", ROOT)

    summary = helper.collect_opencode_metadata("2026-07-03T00:00:00Z", "2026-07-04T00:00:00Z")

    assert summary["top_level_sessions"] == 2
    assert summary["subagents_excluded"] == 1
    assert summary["tool_failures"] == [{"tool": "bash", "error_kind": "timeout", "count": 1}]
    assert "PRIVATE_ERROR" not in json.dumps(summary)
    assert "PRIVATE_SESSION_TITLE" not in json.dumps(summary)
    assert "ses-top-secret" not in json.dumps(summary)


def test_collect_writes_fingerprinted_report_without_claude_or_auto_launcher(tmp_path, monkeypatch) -> None:
    helper = load_helper()
    database = tmp_path / "opencode.db"
    create_opencode_fixture(database)
    monkeypatch.setattr(helper, "OPENCODE_DB_PATH", database)
    monkeypatch.setattr(helper, "PROJECT_ROOT", ROOT)
    monkeypatch.setattr(helper, "STATE_FILE", tmp_path / "workflow-state.json")
    monkeypatch.setattr(helper, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(helper, "collect_git_metadata", lambda *_args: {"commits": [{"sha": "abc", "changed_file_count": 2}], "path_churn": []})
    monkeypatch.setattr(helper, "collect_test_metadata", lambda *_args: {"runs": [{"git_sha": "abc", "status": "passed"}], "flake_history_available": False})

    report = helper.collect("2026-07-03T00:00:00Z", "2026-07-04T00:00:00Z")

    assert report["correlations"] == [{"git_sha": "abc", "test_run_count": 1}]
    assert report["recommendations"][0]["rule_id"] == "repeated_tool_failure"
    assert report["recommendations"][0]["fingerprint"].startswith("sha256:")
    assert (tmp_path / "reports" / "2026-07-03_2026-07-04.json").is_file()
    assert "PRIVATE_SESSION_TITLE" not in json.dumps(report)
    assert "run_opencode_session" not in HELPER_PATH.read_text(encoding="utf-8")
    assert "Claude Code" not in HELPER_PATH.read_text(encoding="utf-8")


def test_daily_meeting_no_longer_invokes_workflow_review() -> None:
    daily_helper = (ROOT / "scripts" / "_daily_meeting_helper.py").read_text(encoding="utf-8")

    assert "_workflow_review_helper" not in daily_helper
    assert not (ROOT / "scripts" / "nightly-workflow-review.sh").exists()
    assert not (ROOT / "scripts" / "prompts" / "workflow-review.md").exists()
