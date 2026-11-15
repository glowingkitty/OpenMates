"""Escalation policy of the external status monitor (deployment/status_server/agent).

Assertions: external-status-monitoring.alerts.confirmed-failures,
external-status-monitoring.alerts.escalation, external-status-monitoring.alerts.resolved,
external-status-monitoring.alerts.restart-safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deployment/status_server/agent"))

from status_agent.alerts import (  # noqa: E402 - path set up above for the standalone agent package
    CheckResult,
    CheckSnapshot,
    OpenAlert,
    evaluate,
    format_duration,
    message_line,
)

MIN = 60.0
T0 = 1_800_000_000.0


def snap(*outcomes: bool, start: float = T0, every: float = MIN, stale_after: float = 5 * MIN) -> CheckSnapshot:
    results = tuple(CheckResult(start + i * every, ok) for i, ok in enumerate(outcomes))
    return CheckSnapshot(key="openmates_api", name="API", results=results, stale_after_s=stale_after)


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_single_failure_stays_silent() -> None:
    result = evaluate([snap(True, True, False)], {}, now=T0 + 2 * MIN)
    assert result.notifications == []
    assert result.state == {}


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_two_failures_in_a_row_alert_once_with_start_of_outage() -> None:
    result = evaluate([snap(True, False, False)], {}, now=T0 + 2 * MIN)
    assert [n.kind for n in result.notifications] == ["down"]
    assert result.notifications[0].down_since == T0 + MIN
    again = evaluate([snap(True, False, False, False)], result.state, now=T0 + 3 * MIN)
    assert again.notifications == []


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.escalation
def test_reminders_follow_15_minutes_1_hour_then_every_3_hours() -> None:
    state = {"openmates_api": OpenAlert(down_since=T0, notified_at=T0 + MIN)}
    failing = snap(*([False] * 5), start=T0)
    sent_at: list[float] = []
    for minute in range(1, 8 * 60):
        now = T0 + minute * MIN
        current = CheckSnapshot(failing.key, failing.name, (CheckResult(now - MIN, False), CheckResult(now, False)), 5 * MIN)
        result = evaluate([current], state, now=now)
        state = result.state
        sent_at += [(now - (T0 + MIN)) / MIN for n in result.notifications if n.kind == "still_down"]
    assert sent_at == [15, 60, 240, 420]


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.escalation
def test_reminder_reports_total_down_time() -> None:
    state = {"openmates_api": OpenAlert(down_since=T0, notified_at=T0 + MIN)}
    now = T0 + 16 * MIN
    current = CheckSnapshot("openmates_api", "API", (CheckResult(now - MIN, False), CheckResult(now, False)), 5 * MIN)
    note = evaluate([current], state, now=now).notifications[0]
    assert message_line(note) == "STILL DOWN: API has been down for 16 minutes."


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.resolved
def test_first_success_resolves_once() -> None:
    state = {"openmates_api": OpenAlert(down_since=T0, notified_at=T0 + MIN, reminders_sent=1)}
    result = evaluate([snap(False, False, True, start=T0 + 60 * MIN)], state, now=T0 + 62 * MIN)
    assert [n.kind for n in result.notifications] == ["resolved"]
    assert message_line(result.notifications[0]) == "RESOLVED: API is working again after 1 hour 2 minutes."
    assert result.state == {}
    assert evaluate([snap(False, False, True, True, start=T0 + 60 * MIN)], result.state, now=T0 + 63 * MIN).notifications == []


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_recovery_before_confirmation_sends_nothing() -> None:
    assert evaluate([snap(False, True)], {}, now=T0 + MIN).notifications == []


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_stale_results_count_as_outage() -> None:
    result = evaluate([snap(True, stale_after=10 * MIN)], {}, now=T0 + 11 * MIN)
    assert [n.kind for n in result.notifications] == ["down"]
    assert result.notifications[0].down_since == T0 + 10 * MIN


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.restart-safe
def test_missing_check_keeps_state_and_does_not_fake_recovery() -> None:
    state = {"openmates_api": OpenAlert(down_since=T0, notified_at=T0 + MIN)}
    result = evaluate([], state, now=T0 + 5 * MIN)
    assert result.notifications == []
    assert result.state == state


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.restart-safe
def test_state_round_trips_through_json() -> None:
    alert = OpenAlert(down_since=T0, notified_at=T0 + MIN, reminders_sent=3)
    assert OpenAlert.from_json(alert.to_json()) == alert


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.escalation
def test_format_duration() -> None:
    assert format_duration(30) == "less than a minute"
    assert format_duration(MIN) == "1 minute"
    assert format_duration(3 * 3600 + 60) == "3 hours 1 minute"
    assert format_duration(2 * 86400 + 3 * 3600) == "2 days 3 hours"
