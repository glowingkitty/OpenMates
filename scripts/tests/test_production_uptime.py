"""Exercise monitoring adapters and durable notification behavior without posting to production."""

# contract-test-file: infrastructure

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts import daily_meeting_health, prod_email_health, production_uptime, run_tests
from status_agent import gatus, integrations, main, notify
from status_agent.alerts import CheckResult
from status_agent.uptime import Observation, Policy, Store

START = 1_795_088_400


def history(store, table):
    with sqlite3.connect(store.path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def send(store, messages, minute, outcome, check="HTTP"):
    at = START + minute * 60
    store.record([Observation("Production API", check, at, outcome, "HTTP 503" if outcome == "down" else "")],
                 at, lambda message: messages.append(message) or True)


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures,external-status-monitoring.alerts.restart-safe
def test_short_blip_is_persistent_and_silent_after_restart(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    messages = []
    send(store, messages, 0, "down")
    send(store, messages, 1, "down")
    send(Store(store.path), messages, 3, "up")
    send(Store(store.path), messages, 6, "up")
    assert messages == []
    assert store.short_blips(START, START + 1000) == (1, 180)
    incident, = history(store, "incidents")
    assert (incident["started_at"], incident["ended_at"], incident["check_name"], incident["error"]) == (
        START, START + 180, "HTTP", "HTTP 503")


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.escalation,external-status-monitoring.alerts.resolved
def test_long_outage_repeats_then_recovers_once_even_after_restart(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    messages = []
    for minute, outcome in [(0, "down"), (5, "down"), (9, "down"), (10, "down"), (15, "down"),
                            (39, "down"), (40, "down"), (50, "down"), (99, "down"), (100, "down"),
                            (103, "up"), (105, "up"), (106, "up"), (110, "up")]:
        send(Store(store.path), messages, minute, outcome)
    assert len(messages) == 4
    assert messages[0] == "🚨 Production API down for 10 minutes."
    assert messages[1] == "🚨 Production API still down for 40 minutes."
    assert messages[2] == "🚨 Production API still down for 1 hour 40 minutes."
    assert messages[3].startswith("✅ Production API recovered after 1 hour 43 minutes (")
    assert "UTC to " in messages[3]
    assert store.active_services() == set()


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.resolved
def test_nearby_failures_of_same_service_merge_and_recovery_waits_for_all_checks(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    messages = []
    for minute, outcome, check in [(0, "down", "A"), (3, "up", "A"), (4, "down", "B"),
                                   (6, "down", "A"), (10, "down", "A"), (15, "up", "A"),
                                   (25, "up", "B"), (28, "up", "B")]:
        send(store, messages, minute, outcome, check)
    assert len(history(store, "incidents")) == 1
    assert len(messages) == 2
    assert "25 minutes" in messages[1]


def test_unknown_and_failed_delivery_do_not_create_recovery(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3", Policy(first_reminder=60, repeat_every=120))
    messages = []
    send(store, messages, 0, "down")
    send(store, messages, 5, "checker")
    send(store, messages, 10, "down")
    at = START + 660
    store.record([Observation("Production API", "HTTP", at, "down")], at, lambda _: False)
    send(store, messages, 12, "up")
    send(Store(store.path), messages, 15, "up")
    assert messages == []
    assert len(history(store, "checker_errors")) == 1


def test_failed_recovery_is_retried_after_restart(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    messages = []
    send(store, messages, 0, "down")
    send(store, messages, 10, "down")
    send(store, messages, 11, "up")
    store.record([], START + 15 * 60, lambda _: False)
    send(Store(store.path), messages, 16, "up")
    send(Store(store.path), messages, 17, "up")
    assert [message[0] for message in messages] == ["🚨", "✅"]


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.checker-errors
def test_prod_runner_setup_failure_is_retried_once_and_never_opens_incident(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMATES_PROD_UPTIME_ENABLED", "1")
    monkeypatch.setattr(run_tests, "CONTROL_PLANE_ROOT", tmp_path)
    retries = []
    error = "Ensure Playwright browser and system dependencies: Installation process exited with code: 100"
    dispatch = (20, None, "failure")
    monkeypatch.setattr(run_tests, "_dispatch_prod_smoke", lambda *args: retries.append(args) or dispatch)
    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _: None)
    monkeypatch.setattr(run_tests.GitHubActionsClient, "download_artifact", lambda *args: None)
    monkeypatch.setattr(run_tests.GitHubActionsClient, "get_failed_job_error", lambda *args: error)
    posts = []
    monkeypatch.setattr(prod_email_health, "post_discord", lambda *args: posts.append(args) or True)
    rc = run_tests._record_prod_smoke(
        SimpleNamespace(discord_webhook_prod_smoke="fake"), "free-hourly", tmp_path / "archive",
        "prod-free-hourly", "2026-11-19T12:10:00Z", "sha", "dev", False, 19, None, "failure",
    )
    assert rc == 1 and retries == [("free-hourly",)] and posts == []
    store = production_uptime.store_for(tmp_path)
    assert history(store, "incidents") == []
    assert {row["error"] for row in history(store, "checker_errors")} == {error}
    assert len(history(store, "checker_errors")) == 6


def test_smoke_zero_duration_is_checker_but_real_nested_failure_is_service(tmp_path):
    report = tmp_path / "reachability.json"
    duration = {"status": "failed", "duration": 0, "error": {"message": "Expected HTTP 200, received 503"}}
    data = {"stats": {"unexpected": 1}, "suites": [{"suites": [{"specs": [
        {"tests": [{"results": [duration]}]}
    ]}]}]}
    spec = [("reachability", "web", "web.spec.ts")]
    for ms, outcome in [(0, "checker"), (1234, "down")]:
        duration["duration"] = ms
        report.write_text(json.dumps(data))
        result = run_tests._parse_prod_smoke_artifact(tmp_path, spec)
        assert production_uptime.smoke_outcome(result[0]) == outcome


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.checker-errors
def test_brevo_statistics_timeout_with_accepted_real_sends_is_checker_only(monkeypatch, tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    messages = []
    rows = [
        {"_timestamp": START * 1_000_000, "message": json.dumps({
            "name": "backend.core.api.app.services.email.brevo_provider",
            "message": "Email accepted by Brevo with a provider message ID",
        })},
        {"_timestamp": START * 1_000_000, "message": json.dumps({
            "name": "backend.core.api.app.tasks.health_check_tasks",
            "message": "Health check: Brevo API is healthy (100.0ms)",
        })},
    ]
    assert len(prod_email_health.send_log_observations(rows, "Production email")) == 2
    monkeypatch.setattr(daily_meeting_health, "_run", lambda *args, **kwargs: json.dumps({"success": True, "rows": rows}))

    def timeout(*args, **kwargs):
        raise TimeoutError

    real_check = prod_email_health.check_error_rate
    monkeypatch.setattr(prod_email_health, "check_error_rate", lambda key, now: real_check(key, now, opener=timeout))
    for minute in [1, 5, 10, 15]:
        now = datetime.fromtimestamp(START + minute * 60, timezone.utc)
        prod_email_health.monitor(store, now, lambda message: messages.append(message) or True, api_key="test")
    assert messages == [] and history(store, "incidents") == []
    assert {row["error"] for row in history(store, "checker_errors")} == {"Brevo events unreachable (TimeoutError)."}


def test_status_agent_posts_one_message_for_multiple_checks_of_same_service(monkeypatch, tmp_path):
    settings = main.Settings("gatus", "", "api", "", "", False, tmp_path / "state", tmp_path / "public",
                             notify.Channels("fake", "", "", "", "", ""))
    monkeypatch.setattr(main.Agent, "run_probes", lambda *args: None)
    monkeypatch.setattr(integrations, "fetch_health", lambda *_: {key: {} for key in integrations.SECTIONS})
    messages = []
    monkeypatch.setattr(notify, "_post_json", lambda url, payload, headers: messages.append(payload["content"]))
    keys = ["openmates_web-app", "openmates_web-app-shell"]
    samples = []
    monkeypatch.setattr(gatus, "fetch_statuses", lambda *_: {key: tuple(samples) for key in keys})
    agent = main.Agent(settings)
    for minute in range(16):
        at = START + minute * 60
        samples.append(CheckResult(at, minute >= 12, "" if minute >= 12 else "503"))
        agent.tick(at)
    assert [message[0] for message in messages] == ["🚨", "✅"]
    assert all("Web app" in message for message in messages)
    assert len(history(agent.uptime, "incidents")) == 1
    page = json.loads((settings.public_dir / "status.json").read_text())
    assert page["short_blips_24h"] == {"count": 0, "seconds": 0}
    assert "503" not in json.dumps(page["incidents"])


def test_real_send_failures_alert_and_later_acceptance_recovers(monkeypatch, tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    rows = []
    posts = []
    monkeypatch.setattr(daily_meeting_health, "_run", lambda *args, **kwargs: json.dumps({"success": True, "rows": rows}))
    for minute, message in [
        (0, "Failed to send email via Brevo. Status: 503"),
        (7, "Error sending email via Brevo: transport closed"),
        (11, "Failed to send email via Brevo. Status: 503"),
        (12, "Email accepted by Brevo with a provider message ID"),
        (16, "Email accepted by Brevo with a provider message ID"),
    ]:
        at = START + minute * 60
        rows.append({"_timestamp": at * 1_000_000, "message": message})
        prod_email_health.monitor(store, datetime.fromtimestamp(at, timezone.utc),
                                  lambda notice: posts.append(notice) or True)
    assert [notice[0] for notice in posts] == ["🚨", "✅"]
    incident, = history(store, "incidents")
    assert incident["duration_seconds"] == 12 * 60
    assert incident["error"] == "Brevo rejected or failed a production send"
    assert all("transactional email" in notice for notice in posts)


def test_a_second_failure_after_a_long_checker_gap_does_not_confirm_outage(tmp_path):
    store = Store(tmp_path / "uptime.sqlite3")
    posts = []
    for minute in (0, 40):
        at = START + minute * 60
        store.record([Observation("API", "Http", at, "down", max_gap=180)], at,
                     lambda message: posts.append(message) or True)
    assert posts == []


def test_missing_github_cli_is_classified_as_checker_error(monkeypatch):
    def missing_cli():
        raise SystemExit(1)

    monkeypatch.setattr(run_tests, "GitHubActionsClient", missing_cli)
    run, result, conclusion = run_tests._dispatch_observed_prod_smoke("free-hourly")
    assert run is None and result.status == "failed" and conclusion == "unknown"


def test_existing_smoke_delivery_keeps_working_before_activation(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENMATES_PROD_UPTIME_ENABLED", raising=False)
    calls = []
    client = SimpleNamespace(download_artifact=lambda *args: calls.append(args[0]))
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda: client)
    monkeypatch.setattr(run_tests, "_dispatch_prod_smoke", lambda suite, used_client: (17, None, "success"))
    notifications = SimpleNamespace(
        discord_webhook_prod_smoke="fake",
        _send_summary_to_discord=lambda *args, **kwargs: calls.append("summary"),
        send_prod_failure_email=lambda *args, **kwargs: None,
        send_per_test_md_messages=lambda *args, **kwargs: None,
    )
    result = run_tests._run_prod_smoke_suite(
        notifications, force=False, suite="free-hourly", archive_dir=tmp_path,
        mode_flag="prod-free-hourly", mode_label="prod free hourly", display_title="Smoke",
    )
    assert result == 0 and calls == [17, "summary"]
