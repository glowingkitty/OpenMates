#!/usr/bin/env python3
# contract-test-file: tooling
"""Decision rules of scripts/claude_idle_chats.py (tooling test)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_idle_chats import Chat, decide  # noqa: E402  (path set above)

NOW = 1_000_000.0
DAY = 24 * 3600


def chat(**overrides) -> Chat:
    values = dict(
        pid=1, session_id="chat-a", name="openmates-aa", status="idle", is_worker=True,
        last_change=NOW - DAY - 60,
        children=["npm exec @remotion/mcp@latest", "node /opt/bin/figma-developer-mcp --stdio"],
    )
    values.update(overrides)
    return Chat(**values)


def test_idle_worker_past_the_limit_is_closed():
    assert decide(chat(), NOW, DAY, own_session_id="other").close


def test_chat_inside_the_limit_is_kept():
    assert not decide(chat(last_change=NOW - DAY + 60), NOW, DAY, "other").close


def test_busy_chat_is_kept_even_when_its_transcript_is_old():
    assert not decide(chat(status="busy"), NOW, DAY, "other").close


def test_chat_with_a_background_command_is_kept():
    decision = decide(chat(children=["npm exec @remotion/mcp", "/bin/bash -c cargo test"]), NOW, DAY, "other")
    assert not decision.close
    assert "background process" in decision.reason


def test_hand_started_chat_and_own_chat_are_kept():
    assert not decide(chat(is_worker=False), NOW, DAY, "other").close
    assert not decide(chat(), NOW, DAY, own_session_id="chat-a").close


def test_default_limit_is_three_hours() -> None:
    import claude_idle_chats
    assert claude_idle_chats.DEFAULT_MAX_IDLE_HOURS == 3.0
