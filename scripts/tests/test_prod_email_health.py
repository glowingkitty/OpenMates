"""Prod transactional email health check and Brevo IPv4 transport (TASK-427)."""

# contract-test-file: infrastructure

from __future__ import annotations

import io
import json
import socket
import urllib.error
from datetime import datetime, timedelta, timezone

from scripts import brevo_ipv4, prod_email_health as health

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
PROD_TAG = "environment:production,email-type:confirm-email,audience:user"


class _Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload, status=200):
    def open_(request, timeout=None):
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(json.dumps(payload).encode()))
        return _Response(payload, status)
    return open_


def _event(kind, minutes_ago, tag=PROD_TAG):
    return {"event": kind, "date": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "tags": [tag]}


def test_brevo_connection_never_resolves_ipv6(monkeypatch):
    families = []

    def fake_getaddrinfo(host, port, family=0, *args, **kwargs):
        families.append(family)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=None, source=None: ("sock", addr))
    assert brevo_ipv4._create_ipv4_connection(("api.brevo.com", 443), 5) == ("sock", ("192.0.2.10", 443))
    assert families == [socket.AF_INET]


def test_unauthorised_ip_401_is_reported_in_plain_words():
    body = {"code": "unauthorized", "message": "We have detected you are using an unrecognised IP address 2001:db8::1."}
    result = health.check_account("placeholder", opener=_opener(body, status=401))
    assert result["ok"] is False
    assert "HTTP 401" in result["reason"] and "unrecognised IP" in result["reason"]


def test_account_fails_when_send_credits_run_out():
    body = {"plan": [{"type": "subscription", "credits": 12, "creditsType": "sendLimit"}]}
    result = health.check_account("placeholder", opener=_opener(body))
    assert result == {"ok": False, "credits": 12, "reason": "Only 12 Brevo send credits left."}


def test_missing_key_fails_instead_of_skipping():
    assert health.check_account("")["ok"] is False


def test_prod_status_reads_prods_own_brevo_check():
    page = {"groups": [{"services": [{"id": "brevo", "status": "degraded"}]}]}
    result = health.check_prod_status(opener=_opener(page))
    assert result["ok"] is False and "degraded" in result["reason"]
    page["groups"][0]["services"][0]["status"] = "operational"
    assert health.check_prod_status(opener=_opener(page))["ok"] is True


def test_error_rate_counts_only_recent_production_provider_failures():
    events = (
        [_event("requests", 10) for _ in range(4)]
        + [_event("error", 5), _event("blocked", 6), _event("error", 7)]
        + [_event("hardBounces", 5)]  # recipient problem, not ours
        + [_event("error", 300)]  # outside the window
        + [_event("error", 5, tag="environment:development,email-type:x")]
    )
    result = health.summarize_events(events, NOW)
    assert (result["ok"], result["requests"], result["failed"]) == (False, 4, 3)
    assert "3 of 4 production emails" in result["reason"]


def test_a_single_failure_or_quiet_night_is_healthy():
    assert health.summarize_events([_event("requests", 5), _event("error", 5)], NOW)["ok"] is True
    assert health.summarize_events([], NOW)["ok"] is True


def test_alerts_on_change_repeat_every_six_hours_and_report_recovery():
    failing, healthy = {"ok": False}, {"ok": True}
    assert health.alert_decision(failing, {}, 1000.0) == "failure"
    assert health.alert_decision(failing, {"ok": False, "last_alert_ts": 1000.0}, 2000.0) is None
    assert health.alert_decision(failing, {"ok": False, "last_alert_ts": 0.0}, 6 * 3600.0) == "failure"
    assert health.alert_decision(healthy, {"ok": False}, 1000.0) == "recovery"
    assert health.alert_decision(healthy, {"ok": True}, 1000.0) is None


def test_failure_message_names_each_reason_without_secrets():
    result = {"ok": False, "checks": {
        "prod_status": {"ok": True},
        "brevo_account": {"ok": False, "reason": "Brevo account check HTTP 401: unrecognised IP address"},
    }}
    message = health.format_message(result, "failure")
    assert message.startswith("🚨 ") and "Prod email failing" in message
    assert "Brevo account check HTTP 401" in message and len(message) <= 140 and "\n" not in message
    assert "api-key" not in message


def test_run_posts_failure_once_and_saves_state(monkeypatch, tmp_path):
    posts = []
    monkeypatch.setenv("DISCORD_WEBHOOK_PROD_SMOKE", "https://discord.example.org/hook")
    monkeypatch.setattr(health, "evaluate", lambda key, now: {
        "ok": False, "checked_at": NOW.isoformat(),
        "checks": {"brevo_account": {"ok": False, "reason": "Brevo account check HTTP 401"}},
    })
    monkeypatch.setattr(health, "post_discord", lambda url, content: posts.append(content) or True)
    state = tmp_path / "state.json"
    assert health.run(state_path=state) == 1
    assert health.run(state_path=state) == 1
    assert len(posts) == 1
    assert json.loads(state.read_text())["ok"] is False


def test_test_run_alert_email_uses_the_ipv4_brevo_transport(monkeypatch):
    """The dev-host alert email that failed with 401 now connects over IPv4."""
    from scripts import run_tests

    notifier = run_tests.NotificationService.__new__(run_tests.NotificationService)
    notifier.dot_env = {}
    notifier.admin_email = "admin@example.org"
    notifier.brevo_api_key = "placeholder"
    seen, plain = [], []
    monkeypatch.setattr(run_tests, "require_live_email", lambda *args, **kwargs: ["environment:development"])
    monkeypatch.setattr(run_tests, "brevo_urlopen", lambda request, timeout=None: seen.append(request.full_url) or _Response({}))
    monkeypatch.setattr(run_tests.urllib.request, "urlopen", lambda *args, **kwargs: plain.append(True))
    assert notifier._send_via_brevo("Subject", "Body") is True
    assert seen == [run_tests.BREVO_API_URL]
    assert plain == []
