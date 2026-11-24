# contract-test-file: tooling
"""Persistent recovery and notification decisions across watchdog passes."""

import json
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_recovery_watchdog as watchdog  # noqa: E402

CHAT = "a0533bd1-70ce-4f30-bf68-51b9781c1219"


def test_same_refusal_alerts_once_after_two_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog.lifecycle, "live_chats", lambda *a, **k: [])
    monkeypatch.setattr(watchdog.codex_chats, "live", lambda: {})
    monkeypatch.setattr(watchdog, "protected_chats", lambda *a: set())
    monkeypatch.setattr(watchdog, "cached_tasks", lambda _: [])
    monkeypatch.setattr(watchdog, "problems", lambda *a: {
        CHAT: {"kind": "handoff", "title": "Workspace work", "reason": "Task transfer failed"}})
    messages, attempts = [], []
    monkeypatch.setattr(watchdog.chat_usage_watch, "send", lambda text, **kw: messages.append(text) or True)

    def attempt(chat_id, incident, *_):
        attempts.append((chat_id, incident["fresh_context"]))
        return "Task transfer could not be confirmed"

    monkeypatch.setattr(watchdog, "attempt", attempt)
    for timestamp in (1000, 1300):
        watchdog.cycle(tmp_path, timestamp)
    assert messages == []
    for timestamp in (1600, 1900):
        watchdog.cycle(tmp_path, timestamp)
    assert attempts == [(CHAT, False), (CHAT, True)]
    assert len(messages) == 1 and messages[0].startswith("Workspace work is still stalled")


START = 1_799_200_000


@pytest.fixture
def fake_release(tmp_path, monkeypatch):
    rollout = tmp_path / "rollout.jsonl"
    messages, wakes = [], []
    meta = {"title": "Release PR dev to main", "thread_id": "thread"}
    monkeypatch.setattr(watchdog.lifecycle, "live_chats", lambda *a, **k: [])
    monkeypatch.setattr(watchdog.lifecycle, "questions_dir", lambda: tmp_path / "questions")
    monkeypatch.setattr(watchdog.lifecycle, "pushed", lambda *a: {})
    monkeypatch.setattr(watchdog, "cached_tasks", lambda _: [])
    monkeypatch.setattr(watchdog.codex_chats, "live", lambda: {CHAT: {}})
    monkeypatch.setattr(watchdog.codex_chats, "load", lambda _: meta)
    monkeypatch.setattr(watchdog.codex_chats, "rollout_path", lambda _: rollout)
    monkeypatch.setattr(watchdog.codex_chats, "turn_activity", lambda _: (START, "working"))
    monkeypatch.setattr(watchdog.codex_chats, "type_into", lambda *a, **kw: wakes.append(a) or "ok")
    monkeypatch.setattr(watchdog.chat_usage_watch, "send", lambda text, **kw: messages.append(text) or True)
    monkeypatch.setattr(watchdog.worktree_wip, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(watchdog.worktree_wip, "sessions_file", lambda: tmp_path / "sessions.json")

    def record(at, kind="function_call"):
        payload = {"type": kind, "arguments": "run an installer"}
        row = {"timestamp": watchdog.lifecycle._utc(at), "type": "response_item", "payload": payload}
        with rollout.open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    record(START)
    return messages, wakes, record, meta


def test_release_wakes_at_ten_minutes_then_alerts_once_if_quiet(tmp_path, fake_release):
    messages, wakes, _, _ = fake_release
    assert watchdog.cycle(tmp_path, START + 599) == {}
    watchdog.cycle(tmp_path, START + 600)
    assert len(wakes) == 1 and not messages
    watchdog.cycle(tmp_path, START + 719)
    assert not messages
    watchdog.cycle(tmp_path, START + 720)
    assert len(wakes) == 2 and not messages
    assert "prior wake" in wakes[-1][1]
    watchdog.cycle(tmp_path, START + 840)
    watchdog.cycle(tmp_path, START + 900)
    assert len(messages) == 1
    assert "Release PR dev to main" in messages[0]
    assert "an installer" in messages[0] and "got no new step" in messages[0]


def test_failed_wake_notifies_ordinary_chat_at_thirty_minutes(tmp_path, fake_release, monkeypatch):
    messages, wakes, _, meta = fake_release
    meta["title"] = "Fix settings"
    monkeypatch.setattr(watchdog.codex_chats, "type_into", lambda *a, **kw: wakes.append(a) or "pane unavailable")
    assert watchdog.cycle(tmp_path, START + 1799) == {}
    watchdog.cycle(tmp_path, START + 1800)
    watchdog.cycle(tmp_path, START + 2100)
    assert len(wakes) == 2 and not messages
    watchdog.cycle(tmp_path, START + 2400)
    assert len(messages) == 1 and "could not reach it safely" in messages[0]


def test_new_step_after_wake_suppresses_alert_until_a_new_stall(tmp_path, fake_release):
    messages, wakes, record, _ = fake_release
    watchdog.cycle(tmp_path, START + 600)
    record(START + 660, "function_call_output")
    watchdog.cycle(tmp_path, START + 720)
    assert not messages and len(wakes) == 1
    watchdog.cycle(tmp_path, START + 1260)
    watchdog.cycle(tmp_path, START + 1380)
    watchdog.cycle(tmp_path, START + 1500)
    assert len(messages) == 1 and len(wakes) == 3


def test_owner_only_wait_is_quiet(tmp_path, fake_release):
    messages, wakes, _, _ = fake_release
    (tmp_path / "registered.json").write_text(json.dumps({
        "owner": {"chat_id": CHAT, "kind": "handoff", "on": "Marco's approval"},
    }))
    assert watchdog.cycle(tmp_path, START + 3600) == {}
    assert not messages and not wakes


def test_waiting_claude_chat_uses_its_wait_description(tmp_path, monkeypatch):
    row = {"session_id": CHAT, "title": "Production rollout", "kinds": ["background"],
           "since": watchdog.lifecycle._utc(START), "waits_on": ["background: installer (waiting)"]}
    chat = watchdog.lifecycle.Chat(1, CHAT, "Worker", "idle", "pane", START)
    cases = watchdog.active_stalls(START + 600, {CHAT: chat}, {}, {"waiting": [row]}, {}, set(), [])
    assert cases[CHAT]["reason"] == "installer"
    woke = []
    monkeypatch.setattr(watchdog.lifecycle, "wake", lambda *a, **kw: woke.append(a) or True)
    assert watchdog.attempt(CHAT, cases[CHAT], {CHAT: chat}, {}) == "ok" and woke


def test_unseen_delivery_recovers_once_without_exposing_message(tmp_path, fake_release):
    messages, wakes, _, meta = fake_release
    meta["title"] = "Collaboration"
    (tmp_path / "connector-deliveries.json").write_text(json.dumps({
        f"{CHAT}:a": {"chat": CHAT, "title": "Collaboration", "state": "pending",
                       "sent_at": START, "text": "Check live editing on remote access Projects",
                       "body": "private draft material"},
        f"{CHAT}:b": {"chat": CHAT, "title": "Collaboration", "state": "undelivered",
                       "sent_at": START + 1},
    }))
    assert not watchdog.cycle(tmp_path, START + 599)
    assert watchdog.cycle(tmp_path, START + 600)[CHAT]["kind"] == "unseen_delivery"
    assert len(wakes) == 1 and not messages
    watchdog.cycle(tmp_path, START + 900)
    assert len(wakes) == 2 and not messages
    watchdog.cycle(tmp_path, START + 1200)
    assert len(messages) == 1 and "ten minutes" in messages[0]
    assert messages[0].splitlines()[0] == "Collaboration still has an unread message about remote-access live editing."
    assert "private draft material" not in messages[0]
    assert "Check live editing" not in messages[0]
    assert "Collaboration" in (tmp_path / "watchdog-daily-list.json").read_text()


def test_completed_chat_with_old_open_task_cache_stays_quiet(tmp_path, fake_release, monkeypatch):
    messages, wakes, _, _ = fake_release
    monkeypatch.setattr(watchdog.codex_chats, "live", lambda: {})
    monkeypatch.setattr(watchdog.lifecycle, "load_registry", lambda _: {
        CHAT: {"state": "stopped", "reason": "reported done"},
    })
    monkeypatch.setattr(watchdog, "cached_tasks", lambda _: [{
        "title": "Finished work", "status": "todo", "external_chat": {"provider": "claude", "id": CHAT},
    }])
    assert not watchdog.cycle(tmp_path, START + 5000)
    assert not messages and not wakes
