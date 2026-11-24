# contract-test-file: tooling
"""Persistent recovery and notification decisions across watchdog passes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_recovery_watchdog as watchdog  # noqa: E402

CHAT = "a0533bd1-70ce-4f30-bf68-51b9781c1219"


def test_same_refusal_alerts_once_and_is_retried_until_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog.lifecycle, "live_chats", lambda *a, **k: [])
    monkeypatch.setattr(watchdog.codex_chats, "live", lambda: {})
    monkeypatch.setattr(watchdog, "protected_chats", lambda *a: set())
    monkeypatch.setattr(watchdog, "cached_tasks", lambda _: [])
    monkeypatch.setattr(watchdog, "problems", lambda *a: {
        CHAT: {"kind": "handoff", "reason": "Task handoff could not be confirmed"}})
    messages, attempts = [], []
    monkeypatch.setattr(watchdog.chat_usage_watch, "send", lambda text: messages.append(text) or True)

    def attempt(*args):
        attempts.append(args[0])
        return "ok" if len(attempts) == 3 else "Task transfer could not be confirmed"

    monkeypatch.setattr(watchdog, "attempt", attempt)
    for timestamp in (1000, 2800, 4600):
        report = watchdog.cycle(tmp_path, timestamp)
    assert len(messages) == 1 and "handoff" in messages[0]
    assert attempts == [CHAT] * 3
    assert report[CHAT]["outcome"] == "ok"
