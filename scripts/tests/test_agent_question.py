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
    assert len(aq.build_message("x " * 9000, "", [], "", "", "t")) <= aq.MAX_CHARS * aq.MAX_PARTS


# Token-shaped strings below are concatenated so secret scanners do not flag the synthetic values.
# Real-shaped (synthetic) values from broken pushes: presigned review videos, Task/chat UUIDs, commits.
TASK_UUID = "1b0f9375-84d4-4e0b-8f96-d677a4f1da2d"
CHAT_UUID = "0c808c39-d681-4369-99a8-8cb7cce7056d"
COMMIT = "69e58d3cf0b1a2c3d4e5f60718293a4b5c6d7e8f"
DIGEST = "9f2c" * 16
PRESIGNED = ("https://nbg1.your-objectstorage.com/dev-openmates-opencode-response-media/review-responses/"
             f"2026/11/15/{CHAT_UUID}/video.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256"
             "&X-Amz-Credential=EXAMPLEACCESSKEY0001%2F20261115%2Fnbg1%2Fs3%2Faws4_request"
             "&X-Amz-Date=20261115T101500Z&X-Amz-Expires=172800&X-Amz-SignedHeaders=host"
             "&X-Amz-Signature=" + "a3f1c9d2" * 8)
VHOST = ("https://openmates-public-examples.nbg1.your-objectstorage.com/runs/7b9e2f4a1c3d5e6f8a0b2c4d6e8f0a1b/"
         "shot.png?X-Amz-Signature=" + "0d1e2f3a" * 8)


def test_ids_hashes_and_own_media_links_stay_intact():
    text = (f"Task: {TASK_UUID} | Chat: {CHAT_UUID} | commit {COMMIT} (69e58d3cf0) digest sha256:{DIGEST} "
            f"web video {PRESIGNED} and screenshot {VHOST} . Set SECRET__FIGMA__OAUTH_CLIENT_SECRET in Vault; "
            "test test_agent_question_keeps_presigned_links_whole and branch fix-discord-push-redaction-ids.")
    out = aq.scrub(text)
    for kept in (TASK_UUID, CHAT_UUID, COMMIT, DIGEST, PRESIGNED, VHOST, "SECRET__FIGMA__OAUTH_CLIENT_SECRET",
                 "test_agent_question_keeps_presigned_links_whole", "fix-discord-push-redaction-ids"):
        assert kept in out, kept
    assert "[removed]" not in out


def test_task_line_of_a_built_message_keeps_the_task_id(root):
    message = aq.build_message(f"Video: {PRESIGNED}", "", [], TASK_UUID, "3c39", "Fix pushes")
    assert f"Task: {TASK_UUID} | Session: 3c39" in message and PRESIGNED in message


@pytest.mark.parametrize("secret, leaked", [
    ("API key " + "sk" + "-proj-AbCdEfGhIjKlMnOpQrStUvWx", "AbCdEfGhIj"),
    ("token " + "gh" + "p_aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5", "aB3dE5gH7j"),
    ("github" + "_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuv", "abcdefghijklmnop"),
    ("slack " + "xo" + "xb-1234567890-abcdefghijklmnop", "abcdefghijklmnop"),
    ("aws " + "AK" + "IAIOSFODNN7EXAMPLE", "IOSFODNN7"),
    ("Authorization: Bearer abcdef0123456789ABCDEF.ghij", "abcdef0123456789"),
    ("jwt " + "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "dozjg"),
    ("DIRECTUS_ADMIN_PASSWORD=Hunter2-very-secret", "Hunter2"),
    ("vault value " + "hv" + "s.CAESIJ7xK2mQ9pL4vR8tW1zY6nB3cF5gH0jD2kS7aE9uN4o", "CAESIJ7xK2mQ9pL4vR8tW1zY6nB3cF5gH0jD2kS7aE9uN4o"),
    ("raw key Zx81Kq0LmP3nR5tV7wY9aB2cD4eF6gH8jK0mN2pQ4s", "Zx81Kq0LmP3n"),
    ("32 hex key 5f4dcc3b5aa765d61d8327deb882cf99", "5f4dcc3b5aa765d61d8327deb882cf99"),
    ("hook https://discord.com/api/" + "webhooks/123456/abcDEF-ghi", "abcDEF"),
    ("mail owner@example.org", "owner@"),
    ("foreign link https://evil.example.org/x?token=Zx81Kq0LmP3nR5tV7wY9aB2cD4eF6gH8jK0m", "Zx81Kq0LmP3n"),
    ("other bucket https://nbg1.your-objectstorage.com/someone-else/v.mp4?X-Amz-Signature=" + "Ab12" * 16, "Ab12Ab12"),
])
def test_real_secrets_are_still_removed(secret, leaked):
    out = aq.scrub(secret)
    assert leaked not in out and "[removed]" in out


def test_setup_steps_keep_placeholders_public_keys_and_image_tags():
    pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPcrLk/uTTvE04WCQ23H2TNr1GLu9qyoxctJR9VtESh/ openmates-status-deploy"
    text = (f"Add SECRET__FIGMA__OAUTH_CLIENT_ID=... and SECRET__FIGMA__OAUTH_CLIENT_SECRET=<value> to .env. "
            f"SSH key, paste exactly: {pub} then run setup --image ghcr.io/example/openmates-status:sha-{COMMIT}")
    assert aq.scrub(text) == text


def test_private_key_next_to_a_public_key_is_still_removed():
    out = aq.scrub("pub ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPcrLk/uTTvE04WCQ23 and "
                   "-----BEGIN OPENSSH PRIVATE KEY-----b3BlbnNzaC1rZXktdjEAAAAA-----END OPENSSH PRIVATE KEY-----")
    assert "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPcrLk/uTTvE04WCQ23" in out and "b3BlbnNz" not in out


def test_assignment_keeps_the_name_and_drops_the_value():
    assert aq.scrub("set SERVER_OWNER_TOKEN=abc123def and VIDEO_URL=" + PRESIGNED) == (
        "set SERVER_OWNER_TOKEN=[removed] and VIDEO_URL=" + PRESIGNED)


def test_long_push_is_split_into_parts_without_cutting_links(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    question = " ".join(f"Flow {n}: {PRESIGNED}" for n in range(5))
    sent = []
    text = aq.ask(args(question=question), root, "chat-1", 1.0, post=lambda **kw: sent.append(kw) or {"message_id": "1"})
    parts = [call["payload"]["content"] for call in sent]
    assert len(parts) >= 2 and all(len(part) <= aq.MAX_CHARS for part in parts)
    assert sum(part.count(PRESIGNED) for part in parts) == 5 and text.count(PRESIGNED) == 5


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
        aq.ask(args(), root, "chat-1", 1.0, post=lambda **_: None, sleep=lambda _: None)
    assert not aq.marker_path(root, "chat-1").exists()

def test_transient_failure_is_retried_then_delivered(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    results, waits = [None, None, {"message_id": "9"}], []
    aq.ask(args(), root, "chat-1", 1.0, post=lambda **_: results.pop(0), sleep=waits.append)
    assert waits == list(aq.RETRY_DELAYS) and not results
    assert aq.marker_path(root, "chat-1").exists()

def test_gives_up_after_all_attempts(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    calls = []
    with pytest.raises(aq.QuestionError, match="after 3 attempts"):
        aq.ask(args(), root, "chat-1", 1.0, post=lambda **_: calls.append(1), sleep=lambda _: None)
    assert len(calls) == 3


def test_delivered_push_is_logged_for_the_connector(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    monkeypatch.setenv("CLAUDE_CHAT_TITLE", "Billing fix")
    text = aq.ask(args(), root, "chat-1", 1000.0, post=lambda **_: {"message_id": "1"})
    entry = json.loads((root / aq.PUSH_LOG).read_text().splitlines()[-1])
    assert entry["chat_id"] == "chat-1" and entry["title"] == "Billing fix" and entry["ts"] == 1000.0
    assert entry["asks"] == "Which region?" and entry["recommendation"] == "eu"
    assert entry["options"] == ["eu", "us"] and entry["task"] == "TASK-1" and entry["text"] == text

def test_failed_push_is_not_logged(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    with pytest.raises(aq.QuestionError):
        aq.ask(args(), root, "chat-1", 1.0, post=lambda **_: None, sleep=lambda _: None)
    assert not (root / aq.PUSH_LOG).exists()
