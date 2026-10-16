# backend/tests/test_degraded_services_discord_report.py
#
# Unit tests for the weekday Discord degraded-services digest.
# These tests exercise only pure aggregation and formatting helpers so they do
# not need OpenObserve, Redis, Celery workers, or real Discord webhooks.
# The Celery task itself delegates to these helpers at runtime.

import json
import asyncio
import sys
from types import SimpleNamespace

import pytest

from backend.core.api.app.services import degraded_services_report as report


def _row(service: str, level: str, message: str) -> dict[str, str]:
    return {
        "service": service,
        "level": level,
        "message": json.dumps(
            {
                "timestamp": "2026-06-03 10:00:00,000",
                "name": "backend.example",
                "level": level,
                "message": message,
            }
        ),
    }


# contract-test: direct surface=cli assertions=operational-monitoring.alerts.actionable-low-noise,operational-monitoring.content.privacy-boundary
def test_build_degraded_issue_report_groups_exact_inner_messages():
    rows = [
        _row("api", "ERROR", "Failed to connect to cache at cache:6379: Timeout connecting to server"),
        _row("api", "ERROR", "Failed to connect to cache at cache:6379: Timeout connecting to server"),
        _row("api", "ERROR", "Failed to connect to cache at cache:6379: Timeout connecting to server"),
        _row("task-worker", "WARNING", "Health check: App 'ai' is degraded. API: healthy, Worker: unhealthy"),
        _row("task-worker", "WARNING", "Health check: App 'ai' is degraded. API: healthy, Worker: unhealthy"),
        _row("task-worker", "WARNING", "Health check: App 'ai' is degraded. API: healthy, Worker: unhealthy"),
        _row("api", "WARNING", "[ADMIN_LOG_QUERY] user=abc stream=default"),
    ]

    issues = report.build_degraded_issue_report(rows, min_occurrences=3, top_messages=10)

    assert len(issues) == 2
    assert issues[0]["count"] == 3
    assert issues[0]["service"] == "api"
    assert issues[0]["message"] == "Failed to connect to cache at cache:6379: Timeout connecting to server"
    assert issues[1]["service"] == "task-worker"
    assert "is degraded" in issues[1]["message"]


# contract-test: direct surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_report_counts_mirrored_api_events_once_in_either_order():
    container_rows = [_row("api", "WARNING", "Request failed: diagnostic upload")] * 3
    file_rows = [dict(row, service="", job="api-logs") for row in container_rows]
    for rows in (container_rows + file_rows, file_rows + container_rows):
        issues = report.build_degraded_issue_report(rows)
        assert len(issues) == 1
        assert issues[0]["service"] == "api"
        assert issues[0]["count"] == 3
    # File ingestion still carries real evidence if stdout ingestion is absent.
    assert report.build_degraded_issue_report(file_rows)[0]["count"] == 3


# contract-test: direct surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_report_preserves_distinct_events_and_same_source_repeats():
    first = _row("api", "WARNING", "Request failed: diagnostic upload")
    second = dict(first, job="api-logs", service="")
    payload = json.loads(second["message"])
    payload["timestamp"] = "2026-06-03 10:00:00,001"
    second["message"] = json.dumps(payload)
    assert report.build_degraded_issue_report([first, first, second])[0]["count"] == 3


# contract-test: supporting surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_collect_degraded_rows_pages_the_entire_fixed_window(monkeypatch):
    calls = []
    pages = [[_row("api", "ERROR", "failed")] * 2, [_row("core-worker", "ERROR", "failed")]]

    class Collector:
        async def _search(self, stream, sql, **kwargs):
            calls.append((stream, sql, kwargs))
            return pages.pop(0)

    monkeypatch.setattr(report, "DEGRADED_SERVICES_REPORT_QUERY_LIMIT", 2)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.openobserve_log_collector",
                        SimpleNamespace(OpenObserveLogCollectorService=Collector))
    rows = asyncio.run(report.collect_recent_degraded_log_rows())
    assert len(rows) == 3
    assert "OFFSET 0" in calls[0][1]
    assert "OFFSET 2" in calls[1][1]
    assert "job" in calls[0][1]
    assert calls[0][2] == calls[1][2]


# contract-test: supporting surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_collect_degraded_rows_does_not_publish_partial_query_results(monkeypatch):
    class Collector:
        async def _search(self, *args, **kwargs):
            return None

    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.openobserve_log_collector",
                        SimpleNamespace(OpenObserveLogCollectorService=Collector))
    with pytest.raises(RuntimeError, match="complete degraded-services"):
        asyncio.run(report.collect_recent_degraded_log_rows())


# contract-test: direct surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_build_degraded_issue_report_ignores_one_off_warnings():
    rows = [
        _row("api", "WARNING", "Transient startup note"),
        _row("api", "WARNING", "Transient startup note"),
        _row("api", "WARNING", "Health check: App 'code' is degraded. API: healthy, Worker: unhealthy"),
    ]

    issues = report.build_degraded_issue_report(rows, min_occurrences=3)

    assert issues == []


# contract-test: direct surface=cli assertions=operational-monitoring.content.privacy-boundary,operational-monitoring.notifications.canonical-operations-channel
def test_degraded_report_redacts_sensitive_identifiers_before_rendering():
    issues = report.build_degraded_issue_report([
        _row("api", "ERROR", "Order pi_123 failed for person@example.org at https://private.example/path password=hunter2 sk_live_abc"),
    ] * 3)

    message = report.format_degraded_report_message(environment="production", issues=issues)

    assert "OpenMates production degraded services report" in message
    assert "3x [ERROR] api / backend.example" in message
    assert "pi_123" not in message
    assert "person@example.org" not in message
    assert "private.example" not in message
    assert "hunter2" not in message
    assert "sk_live_abc" not in message
    assert "[REDACTED_ID]" in message


# contract-test: direct surface=cli assertions=operational-monitoring.notifications.canonical-operations-channel,operational-monitoring.environments.isolated-labeled
def test_select_degraded_report_webhook_prefers_explicit(monkeypatch):
    monkeypatch.setenv("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION", "https://example.test/operations")
    monkeypatch.setenv("DISCORD_WEBHOOK_PROD_SMOKE", "https://example.test/prod")

    assert report.select_degraded_report_webhook_url("production") == "https://example.test/operations"


# contract-test: direct surface=cli assertions=operational-monitoring.notifications.canonical-operations-channel,operational-monitoring.environments.isolated-labeled
def test_select_degraded_report_webhook_falls_back_by_environment(monkeypatch):
    for variable in (
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION",
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_PRODUCTION",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_DEVELOPMENT",
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_DEVELOPMENT",
        "DISCORD_WEBHOOK_DEV_NIGHTLY",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_PROD_SMOKE", "https://example.test/prod")
    monkeypatch.setenv("DISCORD_WEBHOOK_DEV_SMOKE", "https://example.test/dev")

    assert report.select_degraded_report_webhook_url("production") == "https://example.test/prod"
    assert report.select_degraded_report_webhook_url("development") == "https://example.test/dev"
