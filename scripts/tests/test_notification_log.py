#!/usr/bin/env python3
# contract-test-file: tooling
"""Every Discord notification type shows up in the private notification log the connector reads (no network)."""

import io
import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent))

import agent_question as aq  # noqa: E402
import discord_webhook  # noqa: E402
import notification_log  # noqa: E402
import chat_usage_watch  # noqa: E402
import ai_test_users_message  # noqa: E402
import pending_work_gate  # noqa: E402
from scripts import prod_email_health, prod_tls_health, stale_code_daily  # noqa: E402

SECRET_URL = "https://discord.com/api/webhooks/123/abcSECRETtoken"


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def fake_open(request, timeout=0):
    return FakeResponse(json.dumps({"id": "9", "attachments": [{"id": "1"}, {"id": "2"}]}).encode())


def via_hook(**kwargs):
    return discord_webhook.post_message(opener=fake_open, **kwargs)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_NOTIFICATION_DIR", str(tmp_path / "notifications"))
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", SECRET_URL)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(pending_work_gate, "canonical_root", lambda: tmp_path)
    monkeypatch.setattr(aq, "shorten_with_model", lambda *_: (_ for _ in ()).throw(aq.discord_summary.ShortenFailed("x")))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/sessions.json").write_text(json.dumps({"sessions": {}}))
    return tmp_path


def listed(capsys, *args):
    notification_log.main(["list", *args])
    return json.loads(capsys.readouterr().out)


def test_one_of_each_notification_type_is_readable_through_the_connector_cli(store, capsys, monkeypatch):
    import argparse

    # agent pushes: ask and done (with an attachment)
    ask = argparse.Namespace(command="ask", question="Quietly ignore resent messages?", recommendation="yes",
                             option=[], task="", dry_run=False, force=False)
    aq.send(ask, store, "4b5c74d7-0000-0000-0000-000000000000", 1000.0, post=via_hook)
    done = argparse.Namespace(command="done", summary="Finished the preview.",
                              task="", dry_run=False, force=False)
    aq.send(done, store, "4b5c74d7-0000-0000-0000-000000000000", 1001.0, post=via_hook)
    # usage and token warning
    usage = [(c, t) for c, t in chat_usage_watch.notices(
        {"4b5c74d7aaaa": {"units": 572e6, "agents": 174}}, {}, 1000.0)]
    monkeypatch.setenv("DISCORD_WEBHOOK_DEV_NIGHTLY", SECRET_URL)
    with monkeypatch.context() as patch:
        post = discord_webhook.post_message
        patch.setattr(discord_webhook, "post_message", lambda **kwargs: post(opener=fake_open, **kwargs))
        assert chat_usage_watch.send(usage[0][1], chats=[usage[0][0]])
    # AI test user summary
    ai_test_users_message.push("AI test users: 3 of 4 flows passed", post=via_hook, sleep=lambda _: None)
    # production health alerts (own Discord posters)
    assert prod_tls_health.post_discord(SECRET_URL, "TLS certificate expires in 5 days", opener=fake_open)
    assert prod_email_health.post_discord(SECRET_URL, "Email alert: Brevo error rate high", opener=fake_open)
    # stale code report (embed payload)
    report = {"summary": {}, "findings": []}
    monkeypatch.setattr(stale_code_daily, "build_discord_payload", lambda *_: {"embeds": [{"title": "Stale code", "description": "3 unused files"}]})
    assert stale_code_daily.notify_discord(report, "abc", store / "r.md", SECRET_URL, opener=fake_open) == "sent"
    # multipart upload with attachment
    discord_webhook.post_files(webhook_url=SECRET_URL, payload={"content": "Deploy failed: log attached"},
                               files=[("deploy.log", b"error token=hunter2hunter2"), ("deploy.log", b"second file")], opener=fake_open)
    # direct urllib post (daily CI notification style)
    request = urllib.request.Request(SECRET_URL, data=json.dumps({"embeds": [{"title": "CI summary", "description": "PASSED"}]}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    notification_log.record_request(request, "daily_ci_notification")
    # backend container spool
    spool = store / "notifications" / "spool"
    monkeypatch.setenv("NOTIFICATION_SPOOL_DIR", str(spool))
    from backend.shared.python_utils.notification_spool import spool_notification
    spool_notification("operational_report", "Operational report: all green", files=[("report.png", b"\x89PNG")])

    entries = listed(capsys)
    text = " | ".join(e["preview"] for e in entries)
    for expected in ("Quietly ignore", "572M weighted tokens", "AI test users", "TLS certificate", "Brevo error rate",
                     "Stale code", "Deploy failed", "CI summary", "Operational report"):
        assert expected in text, expected
    assert {e["kind"] for e in entries} >= {"ask", "done", "usage", "alert", "report", "test"}
    assert len(entries) == 10

    # filter by chat: the usage warning and the ask push mention / run for chat 4b5c74d7
    by_chat = listed(capsys, "--chat", "4b5c74d7")
    assert {e["kind"] for e in by_chat} >= {"ask", "usage"}
    assert listed(capsys, "--kind", "ask")[0]["preview"].startswith("❓")
    assert len(listed(capsys, "--since", "1h")) == 10
    assert listed(capsys, "--since", "0m") == []

    # full content, redaction and attachment copy
    deploy = next(e for e in entries if "Deploy failed" in e["preview"])
    notification_log.main(["read", deploy["id"]])
    full = json.loads(capsys.readouterr().out)
    assert full["text"] == "Deploy failed: log attached"
    attachment = Path(full["attachments"][0]["path"])
    assert attachment.read_text() == "error token=[redacted]"
    assert Path(full["attachments"][1]["path"]).read_text() == "second file"
    assert attachment.stat().st_mode & 0o077 == 0
    assert "abcSECRETtoken" not in (store / "notifications" / "notifications.jsonl").read_text()
    png = next(e for e in entries if "Operational report" in e["preview"])
    assert png["attachments"] == ["report.png"]


def test_entries_and_attachments_expire_after_14_days(store):
    old = time.time() - 15 * 86400
    old_id = notification_log.record("agent_question", "old news", attachments=[("a.txt", b"x")], now=old)
    fresh_id = notification_log.record("agent_question", "fresh news", attachments=[("b.txt", b"y")])
    notification_log.prune()
    assert notification_log.read_notification(old_id) is None
    assert notification_log.read_notification(fresh_id) is not None
    assert not (store / "notifications" / "attachments" / old_id).exists()


def test_identical_confirmed_messages_are_recorded_and_secrets_are_redacted(store):
    first = notification_log.record("x", f"alert {SECRET_URL} Bearer abcdefghijklmnop")
    assert notification_log.record("x", f"alert {SECRET_URL} Bearer abcdefghijklmnop") != first
    entry = notification_log.read_notification(first)
    assert "SECRET" not in entry["text"] and "abcdefghijklmnop" not in entry["text"]


def test_failed_webhook_does_not_create_a_delivered_question(store):
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("offline")

    payload = {"content": "❓ Pick a phone size?"}
    assert discord_webhook.post_message(webhook_url=SECRET_URL, payload=payload, opener=unavailable) is None
    assert not notification_log.list_notifications()
    assert discord_webhook.post_message(webhook_url=SECRET_URL, payload=payload, opener=fake_open)
    assert len(notification_log.list_notifications()) == 1


def test_queue_flush_keeps_original_chat_and_does_not_record_an_unsent_push(store):
    now = time.time()
    aq.enqueue(store, {"message": "❓ Queued phone preview?", "chat_id": "abc12345",
                       "title": "Phone preview", "kind": "ask", "due": now + 2})
    assert aq.flush(store, now, post=via_hook) == []
    assert notification_log.list_notifications() == []
    assert aq.flush(store, now + 2, post=via_hook)
    [entry] = notification_log.list_notifications()
    assert (entry["chat_id"], entry["title"]) == ("abc12345", "Phone preview")


def test_backfill_is_idempotent_and_open_questions_use_the_asking_chat(store):
    path = store / "pushes.jsonl"
    now = time.time()
    entries = [
        {"ts": now - 10, "text": "❓ Full question", "chat_id": "abc12345", "title": "Phone preview", "kind": "ask"},
        {"ts": now - 20, "text": "❓ Same question in a different chat", "chat_id": "def12345", "kind": "ask"},
        {"ts": now - 30, "text": "✅ Done", "chat_id": "abc12345", "kind": "done"},
    ]
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    ids = notification_log.backfill_pushes(path, now - 60)
    assert notification_log.backfill_pushes(path, now - 60) == ids
    assert len(notification_log.list_notifications()) == 3
    open_questions = notification_log.list_notifications(
        unanswered=True, owner_replied_at={"abc12345": 0, "def12345": now}.get,
    )
    assert [(entry["chat_id"], entry["title"]) for entry in open_questions] == [("abc12345", "Phone preview")]
    assert notification_log.read_notification(open_questions[0]["id"])["text"] == "❓ Full question"


def test_every_script_that_posts_to_discord_records_it():
    """A new Discord poster must call notification_log (or go through discord_webhook / agent_question)."""
    covered = ("notification_log", "discord_webhook", "agent_question")
    allowed_elsewhere = {"notification_log.py", "discord_webhook.py", "run_tests.py",
                         "daily_meeting_context.py"}  # run_tests records per call site; context only scrubs webhook URLs
    offenders = []
    for path in SCRIPTS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        posts = "urlopen" in source and any(k in source for k in ("DISCORD_WEBHOOK", "api/webhooks"))
        if posts and not any(name in source for name in covered) and path.name not in allowed_elsewhere:
            offenders.append(path.name)
    assert not offenders, f"Discord posters without notification_log: {offenders}"
