#!/usr/bin/env python3
# contract-test-file: tooling
"""Stop-hook gate of scripts/pending_work_gate.py (tooling test)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pending_work_gate as gate  # noqa: E402


def make_root(tmp_path: Path, jobs: list[tuple]) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/sessions.json").write_text(json.dumps({"sessions": {
        "aa11": {"agent_task_id": "chat-1"}, "bb22": {"agent_task_id": "chat-2"}}}))
    db_dir = tmp_path / "logs/ci-coordinator"
    db_dir.mkdir(parents=True)
    db = sqlite3.connect(db_dir / "queue.sqlite3")
    db.execute("CREATE TABLE jobs (id TEXT, owner TEXT, specs TEXT, mode TEXT, state TEXT, created REAL)")
    db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?)", jobs)
    db.commit()
    db.close()
    return tmp_path


def test_blocks_pending_job_without_waiter(tmp_path):
    root = make_root(tmp_path, [("job1", "aa11", '["a.spec.ts"]', "e2e", "running", 1)])
    message = gate.evaluate({"session_id": "chat-1"}, root, commands=[])
    assert "1 CI job(s)" in message and "job1" in message and "e2e" in message


def test_waiter_terminal_other_chat_and_flags_do_not_block(tmp_path):
    root = make_root(tmp_path, [("job1", "aa11", "[]", "e2e", "running", 1),
                                ("job2", "aa11", "[]", "e2e", "success", 2),
                                ("job3", "bb22", "[]", "e2e", "queued", 3)])
    waiter = ["python3 scripts/ci_coordinator.py wait job1"]
    assert gate.evaluate({"session_id": "chat-1"}, root, commands=waiter) == ""
    assert gate.evaluate({"session_id": "chat-1"}, root, commands=[]) != ""
    assert gate.evaluate({"session_id": "chat-1", "stop_hook_active": True}, root, commands=[]) == ""
    assert gate.evaluate({"session_id": "chat-1", "agent_id": "x"}, root, commands=[]) == ""


def test_list_is_capped_at_eight(tmp_path):
    jobs = [(f"j{i}", "aa11", "[]", "e2e", "queued", i) for i in range(10)]
    message = gate.evaluate({"session_id": "chat-1"}, make_root(tmp_path, jobs), commands=[])
    assert "10 CI job(s)" in message and "j7" in message and "j8" not in message and "+2 more" in message


def test_missing_db_raises_for_main_to_fail_open(tmp_path, monkeypatch, capsys):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/sessions.json").write_text(json.dumps({"sessions": {"aa11": {"agent_task_id": "c"}}}))
    monkeypatch.setenv("OPENMATES_CANONICAL_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"session_id": "c"})))
    assert gate.main() == 0
