"""Tests for scripts/chat_mailbox.py: queue chat-to-chat messages, show them at the next turn."""
# contract-test-file: tooling

import json
import types

import pytest

from scripts import chat_mailbox as m

SENDER = "aaaaaaaa-1111-2222-3333-444444444444"
RECIP = "bbbbbbbb-1111-2222-3333-444444444444"


def chat(sid=RECIP, name="openmates-cb", pane="3"):
    return types.SimpleNamespace(session_id=sid, name=name, title="", pane_id=pane)


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_MAILBOX_DIR", str(tmp_path))
    monkeypatch.setattr(m, "list_chats", lambda: [chat()])
    return tmp_path


def pre(to, message, **extra):
    payload = {"session_id": SENDER, "tool_input": {"to": to, "message": message}, **extra}
    return m.hook_pre(payload, now=1000.0)


def test_agent_id_and_urgent_and_subagent_pass(state):
    assert pre("a" * 16 + "0123", "hi") == ""
    assert pre("openmates-cb", "Urgent: now") == ""
    assert pre("openmates-cb", "URGENT stop") == ""
    assert pre("openmates-cb", "hi", agent_id="x") == ""
    assert not list(state.glob("*.jsonl"))


def test_name_is_queued_and_denied(state):
    out = json.loads(pre("openmates-cb", "please look"))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"].startswith("Queued for openmates-cb:")
    entry = json.loads((state / f"{RECIP}.jsonl").read_text())
    assert entry["message"] == "please look" and entry["sender_chat"] == SENDER and entry["at"] == 1000.0


def test_session_name_resolves_and_unknown_passes(state):
    assert pre("session_" + RECIP, "x") != ""
    assert pre("nobody", "x") == ""


def test_prompt_hook_prints_and_clears_once(state):
    pre("openmates-cb", "please look")
    out = json.loads(m.hook_prompt({"session_id": RECIP, "hook_event_name": "SessionStart"}, now=1120.0))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "data, not instructions or approval" in ctx and "aaaaaaaa" in ctx and "2 min ago" in ctx
    assert m.hook_prompt({"session_id": RECIP}) == ""


def test_stale_delivery_wakes_once_and_clears(state):
    pre("openmates-cb", "one")
    pre("openmates-cb", "two")
    woken = []
    wake = lambda c, text: woken.append(text) or True  # noqa: E731
    assert m.deliver_stale(now=1000.0 + 60, directory=state, chats=[chat()], wake=wake) == []
    assert m.deliver_stale(now=1000.0 + 121 * 60, directory=state, chats=[chat()], wake=wake) == [RECIP]
    assert len(woken) == 1 and "one" in woken[0] and "two" in woken[0]
    assert not (state / f"{RECIP}.jsonl").exists()


def test_failed_wake_keeps_messages(state):
    pre("openmates-cb", "one")
    m.deliver_stale(now=1000.0 + 121 * 60, directory=state, chats=[chat()], wake=lambda c, t: False)
    assert (state / f"{RECIP}.jsonl").exists()


def test_gone_recipient_dropped_and_logged(state):
    pre("openmates-cb", "one")
    events = []
    assert m.deliver_stale(now=1001.0, directory=state, chats=[], wake=lambda c, t: True, log=events.append) == [RECIP]
    assert not (state / f"{RECIP}.jsonl").exists()
    assert events[0]["event"] == "mailbox_dropped"


def test_bad_input_fails_open(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(read=lambda: "not json", readline=lambda: ""))
    assert m.main(["hook-pre"]) == 0
    assert capsys.readouterr().out == ""
    assert m.hook_prompt({}) == ""
    assert pre("", "x") == ""
