"""New chats go to Codex at 30% or less weekly Claude usage left until the reset (owner, 2026-11-23)."""

from datetime import datetime, timedelta, timezone

import pytest

import scripts.claude_weekly_model as weekly

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
RESETS = NOW + timedelta(days=2)


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_USAGE_GUARD_DIR", str(tmp_path))
    return tmp_path


def _pushes():
    sent = []
    return sent, lambda text: sent.append(text) or ""


# contract-test: tooling
def test_below_the_threshold_new_chats_keep_their_model():
    sent, notify = _pushes()
    assert weekly.update(69.9, RESETS, NOW, notify) == ""
    assert weekly.new_chat_model("claude-opus-5-5", now=NOW) == "claude-opus-5-5"
    assert sent == []


# contract-test: tooling
def test_switch_turns_on_once_at_70_percent_with_one_push():
    sent, notify = _pushes()
    assert weekly.update(70.0, RESETS, NOW, notify) == "on"
    assert weekly.update(74.0, RESETS, NOW + timedelta(minutes=5), notify) == ""
    assert len(sent) == 1 and "70%" in sent[0] and "Codex" in sent[0] and len(sent[0]) < 140
    assert weekly.route("claude-opus-5-5", text="Fix the settings layout", now=NOW) == ("codex", "gpt-6.2-sol")
    assert weekly.new_chat_model("claude-opus-5-5", now=NOW) == "claude-opus-5-5", "no Sonnet switch any more"


# contract-test: tooling
def test_owner_named_model_is_kept_while_the_switch_is_on():
    _, notify = _pushes()
    weekly.update(80.0, RESETS, NOW, notify)
    assert weekly.new_chat_model("claude-opus-5-5", explicit_model=True, now=NOW) == "claude-opus-5-5"


# contract-test: tooling
def test_switch_ends_at_the_reset_with_one_push():
    sent, notify = _pushes()
    weekly.update(75.0, RESETS, NOW, notify)
    after = RESETS + timedelta(minutes=3)
    assert weekly.new_chat_model("claude-opus-5-5", now=after) == "claude-opus-5-5", "off at the reset time"
    assert weekly.update(2.0, after + timedelta(days=7), after, notify) == "off"
    assert weekly.update(3.0, after + timedelta(days=7), after + timedelta(minutes=5), notify) == ""
    assert len(sent) == 2 and "Claude" in sent[1] and len(sent[1]) < 110
    assert weekly.route("claude-opus-5-5", text="anything", now=after) == ("claude", "claude-opus-5-5")


# contract-test: tooling
def test_next_week_can_switch_on_again():
    sent, notify = _pushes()
    weekly.update(75.0, RESETS, NOW, notify)
    later = RESETS + timedelta(days=5)
    weekly.update(10.0, RESETS + timedelta(days=7), RESETS + timedelta(minutes=1), notify)
    assert weekly.update(71.0, RESETS + timedelta(days=7), later, notify) == "on"
    assert len(sent) == 3


# contract-test: tooling
def test_failed_push_is_recorded_not_raised(state):
    weekly.update(90.0, RESETS, NOW, lambda text: "webhook down")
    assert weekly.load()["push_error"] == "webhook down"
    assert weekly.sonnet_active(NOW)


# contract-test: tooling
def test_security_and_encryption_work_stays_on_claude_while_the_switch_is_on():
    _, notify = _pushes()
    weekly.update(85.0, RESETS, NOW, notify)
    for text in ("Security fix: rate limit login", "Chat key mismatch after sync", "decrypt fails on iOS",
                 "CVE-2026-1234 in pillow", "Encryption of drafts"):
        assert weekly.route("claude-opus-5-5", text=text, now=NOW) == ("claude", "claude-opus-5-5"), text
    assert weekly.route("claude-sonnet-5-5", text="Rename a button", now=NOW) == ("codex", "gpt-6.2-sol")


# contract-test: tooling
def test_explicit_choices_always_win():
    _, notify = _pushes()
    weekly.update(85.0, RESETS, NOW, notify)
    assert weekly.route("claude-opus-5-5", explicit_model=True, text="x", now=NOW) == ("claude", "claude-opus-5-5")
    assert weekly.route("claude-fable-5-2", explicit_model=True, text="x", now=NOW) == ("claude", "claude-fable-5-2")
    assert weekly.route("gpt-6.2-astra", explicit_model=True, text="x", now=NOW) == ("codex", "gpt-6.2-astra")
    weekly.update(10.0, RESETS + timedelta(days=7), RESETS + timedelta(minutes=1), notify)
    assert weekly.route("gpt-6.2-sol", explicit_model=True, text="x", now=RESETS + timedelta(minutes=2)) \
        == ("codex", "gpt-6.2-sol"), "Codex when named even with plenty of Claude usage"


# contract-test: tooling
def test_reserve_threshold_preserves_named_models_and_voice():
    _, notify = _pushes()
    weekly.update(89.9, RESETS, NOW, notify)
    assert not weekly.reserve_active(NOW)
    assert weekly.route("claude-opus-5-5", text="Review encryption", now=NOW)[0] == "claude"
    weekly.update(90, RESETS, NOW, notify)
    assert not weekly.reserve_active(NOW)
    assert weekly.route("claude-opus-5-5", text="Review encryption", now=NOW)[0] == "codex"
    weekly.update(90.1, RESETS, NOW, notify)
    assert weekly.reserve_active(NOW)
    assert weekly.needs_handoff("paused", NOW)
    assert weekly.route("claude-opus-5-5", True, "Review encryption", NOW)[0] == "claude"
    assert weekly.route("claude-opus-5-5", now=NOW, live_voice=True)[0] == "claude"
    assert not weekly.needs_handoff("voice", NOW, exemption="live-voice")
    assert not weekly.needs_handoff("named", NOW, exemption="owner-model")
    assert not weekly.reserve_active(RESETS)
