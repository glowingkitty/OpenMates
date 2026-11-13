#!/usr/bin/env python3
# contract-test-file: tooling
"""Discord question sender of scripts/agent_question.py (tooling test, no network)."""

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_question as aq  # noqa: E402


def args(**overrides) -> argparse.Namespace:
    values = dict(question="Which region?", recommendation="eu", option=["eu", "us"], task="TASK-1",
                  dry_run=False, force=False)
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in aq.WEBHOOK_KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/sessions.json").write_text(json.dumps({"sessions": {
        "aa11": {"agent_task_id": "chat-1", "task": "Fix billing", "last_active": "2026"}}}))
    return tmp_path


def test_message_content_and_scrubbing(root):
    message = aq.build_message("Mail me@example.org? token sk-abcdefghijklmnopqrst", "eu", ["a", "b"],
                               "TASK-1", "aa11", "Fix billing")
    assert message.startswith("Question from Claude chat: Fix billing")
    assert "1. a" in message and "2. b" in message and "TASK-1" in message and "aa11" in message
    assert "example.org" not in message and "sk-abc" not in message
    assert len(aq.build_message("x" * 5000, "", [], "", "", "t")) <= aq.MAX_CHARS


def test_dry_run_writes_nothing(root):
    text = aq.ask(args(dry_run=True), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert "Fix billing" in text
    assert not (root / "logs").exists()


def test_no_webhook_fails(root):
    with pytest.raises(aq.QuestionError, match="no Discord webhook"):
        aq.ask(args(), root, "chat-1", 1000.0, post=lambda **_: {"message_id": "1"})


def test_post_marker_rate_limit_and_fallback_key(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_DEV_NIGHTLY", "https://example.org/hook")
    sent = []

    def post(**kwargs):
        sent.append(kwargs)
        return {"message_id": "1"}

    aq.ask(args(), root, "chat-1", 1000.0, post=post)
    assert sent[0]["webhook_url"] == "https://example.org/hook"
    marker = json.loads(aq.marker_path(root, "chat-1").read_text())
    assert marker["ts"] == 1000.0 and marker["question"] == "Which region?"
    with pytest.raises(aq.QuestionError, match="20 minutes"):
        aq.ask(args(), root, "chat-1", 1100.0, post=post)
    aq.ask(args(force=True), root, "chat-1", 1100.0, post=post)
    aq.ask(args(), root, "chat-1", 1100.0 + aq.RATE_LIMIT_SECONDS + 1, post=post)
    assert len(sent) == 3


def test_unconfirmed_delivery_fails_without_marker(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    with pytest.raises(aq.QuestionError, match="not confirmed"):
        aq.ask(args(), root, "chat-1", 1.0, post=lambda **_: None)
    assert not aq.marker_path(root, "chat-1").exists()
