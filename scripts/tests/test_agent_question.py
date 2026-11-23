#!/usr/bin/env python3
# contract-test-file: tooling
"""Discord done (✅) and ask (❓) pushes of scripts/agent_question.py (tooling test, no network)."""

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_question as aq  # noqa: E402


def no_model(*_):
    raise aq.discord_summary.ShortenFailed("test: no model")

def args(**overrides) -> argparse.Namespace:
    values = dict(command="ask", question="Which region?", recommendation="eu", option=["eu", "us"],
                  task="TASK-1", dry_run=False, force=False)
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in aq.WEBHOOK_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CLAUDE_CHAT_TITLE", raising=False)
    monkeypatch.setattr(aq, "shorten_with_model", no_model)  # never call a real model from tests
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/sessions.json").write_text(json.dumps({"sessions": {
        "aa11": {"agent_task_id": "chat-1", "task": "Fix billing", "last_active": "2026"}}}))
    return tmp_path


def done_args(**overrides) -> argparse.Namespace:
    values = dict(command="done", summary="Billing retries ship on dev; the E2E is green.", paused_until=None,
                  task="TASK-1", dry_run=True, force=False)
    values.update(overrides)
    return argparse.Namespace(**values)


def test_done_dry_run_format(root, monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_TITLE", "Billing fix")
    text = aq.send(done_args(), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert text == "✅ Billing fix: Billing retries ship on dev; the E2E is green."
    paused = aq.send(done_args(summary="Parked until the provider quota resets", paused_until="2026-11-24"), root,
                     "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert paused == "✅ Billing fix: Parked until the provider quota resets. Paused until 2026-11-24."
    assert not (root / "logs").exists()


@pytest.mark.parametrize("summary", [
    "Encryption report is on dev: it costs little, keep it. Open for you: allow opt-in job keys?",
    "Sandbox plan is ready: much faster, large repos work, four decisions for you; link inside.",
    "Project chat works on dev: files, build, commit; the preview card awaits your answer.",
    "Test users run daily on dev; production stays off until your go-ahead.",
    "Parked until Marco decides the backup region.",
    "Fix is on dev. Should I also release it to production",
    "Report is ready. One question: keep the founder as contact",
])
def test_a_done_push_that_asks_the_user_is_refused(root, summary):
    # Owner rule (22 Nov): a question always goes out as its own ❓ push, never inside a ✅ push.
    with pytest.raises(aq.QuestionError, match="must not ask the user anything"):
        aq.send(done_args(summary=summary), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert not (root / "logs").exists()


@pytest.mark.parametrize("summary", [
    "Live payment keys are off dev, and real-AI tests now run in their own CI stack.",
    "Users now see your answer history in settings; the E2E is green.",
    "Specification approved as an owner decision on record; deployed to dev.",
    "Proof video: https://bucket.your-objectstorage.com/a.webm?X-Amz-Algorithm=AWS4 shows the reply.",
])
def test_ordinary_done_texts_still_pass(root, summary):
    assert aq.send(done_args(summary=summary), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))


def test_the_same_question_goes_out_as_an_ask_push(root):
    text = aq.send(args(dry_run=True, question="Allow opt-in job keys?", recommendation="yes"), root, "chat-1",
                   1000.0, post=lambda **_: pytest.fail("posted"))
    assert text.startswith("❓")


def test_ask_dry_run_format_has_no_option_list(root):
    text = aq.send(args(dry_run=True, question="Which S3 region for backups?", recommendation="EU (Falkenstein)"),
                   root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert text == "❓ Fix billing: Which S3 region for backups? Recommendation: EU (Falkenstein)"
    assert "eu" not in text.replace("EU", "") and "\n" not in text  # --option goes to the log only


def test_over_long_text_is_rejected_with_a_rewrite_instruction_not_truncated(root):
    long = "This sentence keeps going with more words than any push should hold. " * 3
    for make, limit in ((lambda t: done_args(summary=t), aq.discord_summary.SUMMARY_MAX),
                        (lambda t: args(dry_run=True, question=t), aq.discord_summary.ASK_MAX)):
        with pytest.raises(aq.discord_summary.SummaryTooLong, match=f"under {limit} characters, one sentence"):
            aq.send(make(long), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))

def test_rejections_count_per_kind_and_fall_back_after_two(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    monkeypatch.setattr(aq, "shorten_with_model", lambda text, limit: "Billing retries ship on dev, E2E green.")
    long, sent = "Billing retries and many other things changed in a very long and detailed way. " * 3, []
    post = lambda **kw: sent.append(kw["payload"]["content"]) or {"message_id": "1"}  # noqa: E731 - test stub
    for _ in range(2):
        with pytest.raises(aq.discord_summary.SummaryTooLong):
            aq.send(done_args(summary=long, dry_run=False), root, "chat-1", 1000.0, post=post)
    assert aq.rejection_count(root, "chat-1", aq.DONE) == 2 and aq.rejection_count(root, "chat-1", aq.ASK) == 0
    assert not sent
    text = aq.send(done_args(summary=long, dry_run=False), root, "chat-1", 1000.0, post=post)
    assert text == "✅ Fix billing: Billing retries ship on dev, E2E green." and sent == [text]
    assert aq.rejection_count(root, "chat-1", aq.DONE) == 0  # a delivered push resets the counter

def test_dry_run_does_not_count_rejections(root):
    with pytest.raises(aq.discord_summary.SummaryTooLong):
        aq.send(done_args(summary="word " * 60), root, "chat-1", 1000.0)
    assert aq.rejection_count(root, "chat-1", aq.DONE) == 0

def test_last_fallback_cuts_at_a_word_boundary_when_the_model_fails(root, monkeypatch):
    monkeypatch.setattr(aq, "shorten_with_model", no_model)
    aq.write_rejections(root, "chat-1", aq.DONE, aq.discord_summary.MAX_REJECTIONS)
    text = aq.send(done_args(summary="Billing retries ship on dev " * 10), root, "chat-1", 1000.0)
    body = text.partition(": ")[2]
    assert len(body) <= aq.discord_summary.SUMMARY_MAX and body.endswith("…") and not body.endswith(" …")
    assert set(body[:-1].split()) <= {"Billing", "retries", "ship", "on", "dev"}  # whole words only

def test_model_answer_that_is_still_too_long_is_cut_instead(root, monkeypatch):
    monkeypatch.setattr(aq, "shorten_with_model", lambda text, limit: "word " * 60)
    aq.write_rejections(root, "chat-1", aq.ASK, aq.discord_summary.MAX_REJECTIONS)
    text = aq.send(args(dry_run=True, question="Which region? " * 30), root, "chat-1", 1000.0)
    assert len(text.partition(": ")[2]) <= aq.discord_summary.ASK_MAX

def test_shortener_gets_only_scrubbed_text(root, monkeypatch):
    seen = []
    monkeypatch.setattr(aq, "shorten_with_model", lambda text, limit: seen.append(text) or "Mail sent.")
    aq.write_rejections(root, "chat-1", aq.DONE, aq.discord_summary.MAX_REJECTIONS)
    aq.send(done_args(summary="Mailed me@example.org with token sk-abcdefghijklmnopqrst. " * 5), root, "chat-1", 1.0)
    assert seen and "example.org" not in seen[0] and "sk-abc" not in seen[0]

def test_shorten_with_model_runs_headless_haiku_and_reports_failures():
    import subprocess
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="  Short result.\n", stderr="")

    assert aq.shorten_with_model("long text", 110, run=run) == "Short result."
    command, kwargs = calls[0]
    assert command[:4] == ["claude", "-p", "--model", aq.SHORTEN_MODEL] and kwargs["input"] == "long text"
    for failing in (lambda c, **k: subprocess.CompletedProcess(c, 1, stdout="", stderr="x"),
                    lambda c, **k: subprocess.CompletedProcess(c, 0, stdout=" ", stderr=""),
                    lambda c, **k: (_ for _ in ()).throw(FileNotFoundError("claude"))):
        with pytest.raises(aq.discord_summary.ShortenFailed):
            aq.shorten_with_model("long text", 110, run=failing)

def test_exactly_one_icon_and_no_markdown_ids_or_title_repeat(root, monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_TITLE", "Check production health now")
    text = aq.send(done_args(summary="Check production health now: ✅ **Production** is healthy (see TASK-119, abc1234)."),
                   root, "chat-1", 1000.0)
    assert text == "✅ Check production health now: Production is healthy."
    assert text.count("✅") == 1 and "**" not in text and "TASK-119" not in text and "abc1234" not in text
    monkeypatch.delenv("CLAUDE_CHAT_TITLE")
    ask = aq.send(args(dry_run=True, question="❓ Quietly ignore resent messages?", recommendation="yes"), root, "chat-1", 1.0)
    assert ask == "❓ Fix billing: Quietly ignore resent messages? Recommendation: yes"

def test_long_titles_are_shortened_to_30_characters_without_task_ids(root, monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_TITLE", "TASK-1063: Project encryption architecture review for agentic coding")
    text = aq.send(done_args(), root, "chat-1", 1000.0)
    title = text.partition(": ")[0][2:]
    assert len(title) <= aq.discord_summary.TITLE_MAX and title.endswith("…") and "TASK" not in title
    assert aq.short_title("Billing fix") == "Billing fix"

@pytest.mark.parametrize("make", [lambda text: done_args(summary=text), lambda text: args(dry_run=True, question=text)])
def test_both_formats_are_scrubbed(root, make):
    text = aq.send(make("Mail me@example.org, token sk-abcdefghijklmnopqrst, task " + "1b0f9375-84d4-4e0b-8f96-d677a4f1da2d"),
                   root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert "example.org" not in text and "sk-abc" not in text
    assert "1b0f9375-84d4-4e0b-8f96-d677a4f1da2d" not in text  # ids never belong in a push summary


def test_links_are_never_cut_by_the_length_cap(root):
    text = aq.send(done_args(summary="Proof video " + PRESIGNED + " and a few more words."), root, "chat-1",
                   1000.0, post=lambda **_: pytest.fail("posted"))
    assert PRESIGNED in text and "[removed]" not in text
    aq.write_rejections(root, "chat-1", aq.DONE, aq.discord_summary.MAX_REJECTIONS)
    cut = aq.send(done_args(summary="Proof video " + PRESIGNED + " " + "more words " * 60), root, "chat-1", 1000.0)
    assert PRESIGNED in cut and cut.endswith("…")


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
    text = aq.send(args(question=question), root, "chat-1", 1.0, post=lambda **kw: sent.append(kw) or {"message_id": "1"})
    parts = [call["payload"]["content"] for call in sent]
    assert len(parts) >= 2 and all(len(part) <= aq.MAX_CHARS for part in parts)
    assert sum(part.count(PRESIGNED) for part in parts) == 5 and text.count(PRESIGNED) == 5


def test_dry_run_writes_nothing(root):
    text = aq.send(args(dry_run=True), root, "chat-1", 1000.0, post=lambda **_: pytest.fail("posted"))
    assert "Fix billing" in text
    assert not (root / "logs").exists()


def test_no_webhook_fails(root):
    with pytest.raises(aq.QuestionError, match="no Discord webhook"):
        aq.send(args(), root, "chat-1", 1000.0, post=lambda **_: {"message_id": "1"})


def test_post_marker_rate_limit_and_fallback_key(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_DEV_NIGHTLY", "https://example.org/hook")
    sent = []

    def post(**kwargs):
        sent.append(kwargs)
        return {"message_id": "1"}

    aq.send(args(), root, "chat-1", 1000.0, post=post)
    assert sent[0]["webhook_url"] == "https://example.org/hook"
    marker = json.loads(aq.marker_path(root, "chat-1").read_text())
    assert marker["ts"] == 1000.0 and marker["question"] == "Which region?"
    aq.send(args(), root, "chat-1", 1100.0, post=post)  # within 20 minutes: queued, not sent, not dropped
    assert len(sent) == 1 and len(aq._queue_lines(root)) == 1
    aq.send(args(force=True), root, "chat-1", 1100.0, post=post)
    aq.send(args(), root, "chat-1", 1100.0 + aq.RATE_LIMIT_SECONDS + 1, post=post)
    assert len(sent) == 3


def test_unconfirmed_delivery_is_queued_and_flush_sends_it_later(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    parsed = args()
    aq.send(parsed, root, "chat-1", 1.0, post=lambda **_: None, sleep=lambda _: None)
    assert parsed.queued and aq.marker_path(root, "chat-1").exists() and not (root / aq.PUSH_LOG).exists()
    (held,) = aq._queue_lines(root)
    assert held["due"] == 1.0 + aq.QUEUE_RETRY_SECONDS and "not confirmed" in held["last_error"]
    assert aq.flush(root, 2.0, post=lambda **_: pytest.fail("not due yet")) == []
    assert aq.flush(root, 1.0 + aq.QUEUE_RETRY_SECONDS, post=lambda **_: None, sleep=lambda _: None) == []
    assert aq._queue_lines(root)[0]["attempts"] == 1  # still unconfirmed: kept, retried later
    sent = aq.flush(root, 1.0 + 2 * aq.QUEUE_RETRY_SECONDS, post=lambda **_: {"message_id": "1"})
    assert len(sent) == 1 and sent[0].startswith("❓") and aq._queue_lines(root) == []
    entry = json.loads((root / aq.PUSH_LOG).read_text().splitlines()[-1])
    assert entry["source"] == "agent_question_queue" and entry["asks"] == "Which region?"

def test_transient_failure_is_retried_then_delivered(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    results, waits = [None, None, {"message_id": "9"}], []
    aq.send(args(), root, "chat-1", 1.0, post=lambda **_: results.pop(0), sleep=waits.append)
    assert waits == list(aq.RETRY_DELAYS) and not results
    assert aq.marker_path(root, "chat-1").exists()

def test_queues_after_all_attempts(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    calls = []
    aq.send(args(), root, "chat-1", 1.0, post=lambda **_: calls.append(1), sleep=lambda _: None)
    assert len(calls) == 3 and "after 3 attempts" in aq._queue_lines(root)[0]["last_error"]


def test_delivered_push_is_logged_for_the_connector(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    monkeypatch.setenv("CLAUDE_CHAT_TITLE", "Billing fix")
    text = aq.send(args(), root, "chat-1", 1000.0, post=lambda **_: {"message_id": "1"})
    entry = json.loads((root / aq.PUSH_LOG).read_text().splitlines()[-1])
    assert entry["chat_id"] == "chat-1" and entry["title"] == "Billing fix" and entry["ts"] == 1000.0
    assert entry["asks"] == "Which region?" and entry["recommendation"] == "eu"
    assert entry["options"] == ["eu", "us"] and entry["task"] == "TASK-1" and entry["text"] == text
    assert entry["kind"] == "ask" and text.startswith("❓ Billing fix: ")


def test_done_push_is_logged_and_rate_limited_apart_from_the_question(root, monkeypatch):
    """Blocked then finished: one ❓ then one ✅ go out; a second ✅ within 20 min is refused."""
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    sent = []
    post = lambda **kw: sent.append(kw["payload"]["content"]) or {"message_id": "1"}  # noqa: E731 - test stub
    aq.send(args(), root, "chat-1", 1000.0, post=post)
    aq.send(done_args(dry_run=False), root, "chat-1", 1100.0, post=post)
    aq.send(done_args(dry_run=False), root, "chat-1", 1200.0, post=post)  # second ✅ within 20 min: queued
    assert [m[0] for m in sent] == [aq.ASK, aq.DONE]
    assert aq._queue_lines(root)[0]["due"] == 1100.0 + aq.RATE_LIMIT_SECONDS
    kinds = [json.loads(line)["kind"] for line in (root / aq.PUSH_LOG).read_text().splitlines()]
    assert kinds == ["ask", "done"]
    assert json.loads(aq.marker_path(root, "chat-1").read_text())["kind"] == aq.DONE


def test_other_scripts_alerts_are_logged_without_a_kind(root):
    aq.record_push(root, "Feedback needed: E2B credits run out in 20 days", 1.0, title="E2B credits")
    assert json.loads((root / aq.PUSH_LOG).read_text())["kind"] == ""

def test_failed_push_is_not_logged(root, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    aq.send(args(), root, "chat-1", 1.0, post=lambda **_: None, sleep=lambda _: None)
    assert not (root / aq.PUSH_LOG).exists()  # logged only once flush delivers it


def test_urgent_question_is_never_held_by_the_rate_limit(root, monkeypatch):
    """Owner, 23 Nov: an urgent production question was held by the 20-minute limit."""
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://example.org/hook")
    sent = []
    post = lambda **kw: sent.append(kw["payload"]["content"]) or {"message_id": "1"}  # noqa: E731 - test stub
    aq.send(args(), root, "chat-1", 1000.0, post=post)
    aq.send(args(urgent=True, question="Roll back the deploy?"), root, "chat-1", 1100.0, post=post)
    aq.send(args(question="Production chats fail: restart the AI worker?"), root, "chat-1", 1200.0, post=post)
    aq.send(args(question="Merge the release PR now?"), root, "chat-1", 1300.0, post=post)
    assert len(sent) == 4 and aq._queue_lines(root) == []
    aq.send(args(question="Which colour for the badge?"), root, "chat-1", 1400.0, post=post)
    assert len(sent) == 4 and len(aq._queue_lines(root)) == 1  # not urgent: queued for later, not dropped


def test_loop_brake_questions_are_deduplicated(root, monkeypatch):
    import ci_triage_gate

    chat = "e26fdb89-6448-4534-b9f5-0ac293c09896"
    queue = root / "logs/ci-coordinator/queue.sqlite3"
    brake = ci_triage_gate.register_brake(queue, chat, {"preview": ["a", "b", "c"]})
    calls = []

    def post(args, folder, chat_id, now):
        calls.append(args.question)
        aq._write_marker(folder, chat_id, args, args.question, aq.ASK, now)
        return "accepted"

    monkeypatch.setattr(aq, "send", post)
    args = argparse.Namespace(command="ask", question="Retry the preview?", dry_run=False)
    assert aq.send_with_loop_brake(args, root, chat) == "accepted"
    assert ci_triage_gate.already_asked(root, chat, brake)
    assert aq.send_with_loop_brake(args, root, chat) is None
    assert calls == ["Retry the preview?"]
