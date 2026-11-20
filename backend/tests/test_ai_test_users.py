# contract-test-file: tooling
"""Offline tests for the AI test user helpers: mailbox code extraction, report selection, transcript.md."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ai_test_users"))

from inbox import extract_code, mask_address, storage_ref  # noqa: E402
from reports import report_text, screenshot_steps, select_reports  # noqa: E402
from transcript import render  # noqa: E402


def test_extract_code_prefers_subject_then_bodies():
    assert extract_code({"subject": "Your code 123456", "body-plain": "654321"}) == "123456"
    assert extract_code({"subject": "Hello", "body-plain": "code: 654321 ok"}) == "654321"
    assert extract_code({"body-html": "<p>Code <b>111222</b></p>"}) == "111222"
    assert extract_code({"body-plain": "order 1234567 no code"}) is None


def test_storage_ref_and_masking():
    assert storage_ref({"storage": {"region": "us-east4", "key": "abc"}}) == ("us-east4", "abc")
    url = "https://storage-eu-west1.api.mailgun.net/v3/domains/d/messages/XYZ"
    assert storage_ref({"storage": {"url": url}}) == ("eu-west1", "XYZ")
    assert mask_address("omtest-1a2b3c@inboxkitten.com") == "omt***@inboxkitten.com"


def finding(index, title, severity="medium", step=3, kept=True, jev=0.8):
    return {"id": index, "title": title, "severity": severity, "step": step, "kept": kept, "jev_score": jev,
            "evidence": "e", "expected": "x"}


def test_select_reports_groups_skips_and_limits():
    findings = [
        finding(0, "Bus booking button points to wrong operator", "high"),
        finding(1, "Booking button for bus result points to the wrong operator", "medium"),
        finding(2, "Raw ISO date shown in flight card", "low"),
        finding(3, "Dropped finding", kept=False),
        finding(4, "Spinner never ends after upload"),
    ]
    groups = select_reports(findings, ["Raw ISO date shown in flight card"], 3)
    assert [[f["id"] for f in g] for g in groups] == [[0, 1], [4]]
    assert len(select_reports(findings, [], 1)) == 1
    title, text = report_text(groups[0], {"id": "p"}, "dev")
    assert title.startswith("Bus booking") and "Step 3" in text


def test_screenshot_steps_picks_lead_and_neighbours():
    assert screenshot_steps(5, list(range(1, 10)), 5) == [3, 4, 5, 6, 7]
    assert screenshot_steps(1, [1, 2, 3], 2) == [1, 2]
    assert screenshot_steps(None, [1, 2, 3], 2) == [2, 3]


def test_transcript_markdown_has_all_sections():
    persona = {"id": "p1", "name": "Mia", "description": "student", "device_label": "phone", "language": "en"}
    steps = [{"step": 1, "at_seconds": 2.0, "title": "Chat", "thought": "ask", "refused": [], "outcome": "ok",
              "actions": [{"kind": "type", "target": "c1", "text": "Hi there", "submit": True}],
              "reply_timing": {"seconds": 5, "first_change_seconds": 2, "settled": True}, "page_text": "Answer text",
              "notes": [{"category": "slow", "what": "slow"}]}]
    result = {"status": "persona_finished", "steps": 1, "credits_start": 100, "credits_end": 90,
              "signup": {"status": "ok", "seconds": 40}, "deletion": {"status": "deleted", "seconds": 20},
              "findings": [finding(0, "Odd layout")], "reports": [{"finding_ids": [0], "short_issue_id": "AB12", "status": "submitted"}],
              "answer_quality": [{"step": 1, "question": "Hi", "score": 4, "why": "good"}],
              "demo_candidate": {"is_candidate": True, "why": "nice", "steps": [1]}}
    md = render(result, persona, steps, "dev")
    for needle in ("# Mia", "User message: Hi there", "Assistant answer", "report AB12", "| 1 | Hi | 4 | good |", "Yes: nice"):
        assert needle in md


def test_validate_job_modes():
    from flows import validate_job

    assert validate_job({"persona": {"id": "a"}}) == "run"
    delete = {"mode": "delete_only", "persona": None, "signup": {"email": "a@example.org", "password": "pw"}}
    assert validate_job(delete) == "delete_only"
    with pytest.raises(ValueError):
        validate_job({**delete, "signup": {"email": "a@example.org"}})
    with pytest.raises(ValueError):
        validate_job({**delete, "persona": {"id": "a"}})
    with pytest.raises(ValueError):
        validate_job({"persona": None})
    with pytest.raises(ValueError):
        validate_job({**delete, "mode": "other"})


def test_absent_login_text():
    from flows import ABSENT_LOGIN_TEXT

    assert ABSENT_LOGIN_TEXT.search("This account does not exist")
    assert not ABSENT_LOGIN_TEXT.search("Too many attempts")


def test_make_inbox_picks_the_job_code_source(monkeypatch):
    import inbox

    assert isinstance(inbox.make_inbox({"email": "a@inboxkitten.com"}), inbox.InboxKitten)
    with pytest.raises(inbox.InboxError):
        inbox.make_inbox({"email": "a@example.org", "inbox": "elsewhere"})
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    with pytest.raises(inbox.InboxError):
        inbox.make_inbox({"email": "a@example.org", "inbox": "dev_cache"})
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert isinstance(inbox.make_inbox({"email": "A@Example.org", "inbox": "dev_cache"}), inbox.DevCacheInbox)


def test_dev_cache_inbox_reads_only_the_signup_code():
    import asyncio

    import inbox

    class Cache:
        async def get(self, key):
            return {"email_verification:a@example.org": '"123456"'}.get(key)

    box = inbox.DevCacheInbox.__new__(inbox.DevCacheInbox)
    box.address, box.poll_seconds, box._services = "a@example.org", 0.01, Cache()
    assert asyncio.run(box.wait_for_code(0)) == "123456"
    assert box.reads_deletion_code is False and inbox.InboxKitten("a@inboxkitten.com").address
    with pytest.raises(inbox.InboxError):
        asyncio.run(box.wait_for_code(0, timeout=0.05, purpose="delete_account"))


def test_ensure_signed_in_counts_relogins_and_fails_closed():
    import asyncio

    from flows import ensure_signed_in
    from backend.shared.providers.e2b_browser import BrowserUnavailable

    class FakeSession:
        def __init__(self, answer):
            self.answer, self.sent, self.result = answer, [], {}
            self.job = {"app_url": "https://app.example.org", "signup": {"email": "a@example.org", "password": "pw"}}

        async def rpc(self, body, timeout):
            self.sent.append(body)
            return self.answer

    signed_in = FakeSession({"state": "auth", "relogin": False})
    asyncio.run(ensure_signed_in(signed_in))
    assert signed_in.sent[0]["operation"] == "ensure_signed_in" and "relogins" not in signed_in.result

    relogged = FakeSession({"state": "auth", "relogin": True})
    asyncio.run(ensure_signed_in(relogged))
    assert relogged.result["relogins"] == 1

    with pytest.raises(BrowserUnavailable):
        asyncio.run(ensure_signed_in(FakeSession({"state": "error", "relogin": True})))
