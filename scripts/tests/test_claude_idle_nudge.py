#!/usr/bin/env python3
# contract-test-file: tooling
"""Decision rules and run loop of scripts/claude_idle_nudge.py (tooling test, no delivery)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_idle_nudge as nudge  # noqa: E402
from claude_idle_chats import Chat  # noqa: E402

NOW = 1_000_000.0
MIN, MAX = 20 * 60, 50 * 60


def chat(**overrides) -> Chat:
    values = dict(pid=1, session_id="chat-a", name="n", status="idle", kind="pane",
                  last_activity=NOW - 30 * 60, children=["npx figma-mcp"])
    values.update(overrides)
    return Chat(**values)


def decide(c=None, **overrides):
    values = dict(question_ts=0.0, nudged=False, finished=["j1"], running=[], last_text="")
    values.update(overrides)
    return nudge.decide(c or chat(), NOW, MIN, MAX, "other", **values)[0]


def test_qualifies_with_finished_ci_jobs():
    assert decide()


def test_idle_window_bounds():
    assert not decide(chat(last_activity=NOW - 10 * 60))
    assert not decide(chat(last_activity=NOW - 60 * 60))


def test_blockers():
    assert not decide(chat(status="busy"))
    assert not decide(chat(kind="rc_worker"))
    assert not decide(chat(protected=True))
    assert not decide(chat(last_speaker="assistant", last_text="CI blocked by GitHub billing."))
    assert not decide(chat(children=["/bin/bash -c cargo test"]))
    assert not decide(chat(session_id="other"))
    assert not decide(question_ts=NOW - 60)
    assert not decide(nudged=True)


def test_old_question_before_last_activity_does_not_block():
    assert decide(question_ts=NOW - 3 * 3600)


def test_waiting_text_evidence():
    assert not decide(finished=[], running=[], last_text="Nothing to do.")
    assert decide(finished=[], running=[], last_text="The E2E run is now running, I'll continue.")
    assert not decide(finished=[], running=[], last_text="It is running. Shall I wait?")


def write_world(tmp_path: Path):
    home = tmp_path / "home"
    (home / "sessions").mkdir(parents=True)
    root = tmp_path / "root"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude/sessions.json").write_text(json.dumps({"sessions": {"aa11": {"agent_task_id": "chat-a"}}}))
    (root / "logs/ci-coordinator").mkdir(parents=True)
    db = sqlite3.connect(root / "logs/ci-coordinator/queue.sqlite3")
    db.execute("CREATE TABLE jobs (id TEXT, owner TEXT, state TEXT, updated REAL)")
    db.execute("INSERT INTO jobs VALUES ('job9','aa11','success',?)", (NOW - 60,))
    db.commit()
    db.close()
    return home, root


def test_ci_evidence_and_run_nudges_once(tmp_path, monkeypatch):
    home, root = write_world(tmp_path)
    assert nudge.ci_evidence(root, "chat-a", NOW - 600) == (["job9"], [])
    assert nudge.ci_evidence(root, "chat-a", NOW) == ([], [])
    monkeypatch.setattr(nudge, "live_chats", lambda _home, _config: [chat()])
    monkeypatch.setattr(nudge, "transcripts", lambda _root: {})
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sent = []
    def sender(target, text):
        sent.append((target.session_id, text))
        return True

    assert nudge.run("nudge", False, 20, 50, root, home, now=NOW, sender=sender) == 0
    assert nudge.run("nudge", False, 20, 50, root, home, now=NOW, sender=sender) == 0
    assert len(sent) == 1 and "job9" in sent[0][1] and "30 minutes" in sent[0][1]
    events = (root / "logs/claude-idle-chats/events.jsonl").read_text().splitlines()
    assert json.loads(events[0])["event"] == "nudged"


def test_dry_run_sends_nothing(tmp_path, monkeypatch, capsys):
    home, root = write_world(tmp_path)
    monkeypatch.setattr(nudge, "live_chats", lambda _home, _config: [chat()])
    monkeypatch.setattr(nudge, "transcripts", lambda _root: {})
    nudge.run("nudge", True, 20, 50, root, home, now=NOW, sender=lambda *a: (_ for _ in ()).throw(AssertionError))
    assert "would nudge" in capsys.readouterr().out
    assert not (root / "logs/claude-idle-chats/nudges.json").exists()


def test_unavailable_target_is_recorded_once(tmp_path, monkeypatch):
    home, root = write_world(tmp_path)
    monkeypatch.setattr(nudge, "live_chats", lambda _home, _config: [chat()])
    monkeypatch.setattr(nudge, "transcripts", lambda _root: {})
    attempts = []

    def sender(target, _text):
        attempts.append(target.session_id)
        return False

    assert nudge.run("nudge", False, 20, 50, root, home, now=NOW, sender=sender) == 1
    assert nudge.run("nudge", False, 20, 50, root, home, now=NOW + 60, sender=sender) == 0
    assert attempts == ["chat-a"]
