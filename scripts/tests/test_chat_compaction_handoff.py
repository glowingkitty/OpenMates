# contract-test-file: tooling
"""Compaction counter, policy notes and handoff prompt of scripts/chat_compaction_handoff.py."""

import argparse
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import chat_compaction_handoff as h  # noqa: E402


def _run(tmp_path, chat="c1", **extra):
    payload = {"source": "compact", "session_id": chat, **extra}
    return h.hook(json.dumps(payload), tmp_path / "c.json")


def test_counts_per_chat_and_policy(tmp_path):
    assert _run(tmp_path) == "" and _run(tmp_path) == ""
    assert "compacted 3 times" in _run(tmp_path) and "hand off" in _run(tmp_path).lower()
    assert "Hand off NOW" in _run(tmp_path)  # 5th still instructs
    assert _run(tmp_path, chat="c2") == ""
    assert json.loads((tmp_path / "c.json").read_text())["c2"] == 1


def test_only_compact_counts(tmp_path):
    for source in ("startup", "resume", "clear"):
        assert h.hook(json.dumps({"source": source, "session_id": "c1"}), tmp_path / "c.json") == ""
    assert not (tmp_path / "c.json").exists()


def test_note_text_at_three_and_four():
    assert "next compaction" in h.policy_note(3)
    assert "NOW" in h.policy_note(4) and h.policy_note(2) == ""


def test_subagent_ignored(tmp_path):
    for _ in range(5):
        assert _run(tmp_path, agent_id="a1") == ""
    assert not (tmp_path / "c.json").exists()


def test_fails_open(tmp_path):
    assert h.hook("not json", tmp_path / "c.json") == ""
    assert h.hook("[]", tmp_path / "c.json") == ""
    assert h.hook(json.dumps({"source": "compact", "session_id": "x"}), tmp_path / "missing" / "\0") == ""


def test_handoff_dry_run_builds_prompt_without_launching(tmp_path, capsys):
    summary = tmp_path / "s.md"
    summary.write_text("Goal: ship X")
    sessions = tmp_path / ".claude"
    sessions.mkdir()
    (sessions / "sessions.json").write_text(json.dumps(
        {"sessions": {"ab12": {"agent_task_id": "chat-1", "worktree": {"path": "/wt/ab12"}}}}))
    args = argparse.Namespace(summary_file=str(summary), session="", chat="chat-1", dry_run=True)
    with mock.patch.object(h, "canonical_root", return_value=tmp_path), \
         mock.patch.object(h, "_find_task", return_value="task-9"), \
         mock.patch.dict(sys.modules, {"claude_dispatch": mock.Mock()}) as mods:
        assert h.handoff(args) == 0
        mods["claude_dispatch"].launch_claude_chat.assert_not_called()
    out = json.loads(capsys.readouterr().out)
    assert out["session"] == "ab12" and out["task"] == "task-9"
    assert "worktree bind-task --session ab12" in out["prompt"] and "Goal: ship X" in out["prompt"]
