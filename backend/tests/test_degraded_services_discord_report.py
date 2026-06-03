# backend/tests/test_degraded_services_discord_report.py
#
# Unit tests for the weekday Discord degraded-services digest.
# These tests exercise only pure aggregation and formatting helpers so they do
# not need OpenObserve, Redis, Celery workers, or real Discord webhooks.
# The Celery task itself delegates to these helpers at runtime.

import json

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


def test_build_degraded_issue_report_ignores_one_off_warnings():
    rows = [
        _row("api", "WARNING", "Transient startup note"),
        _row("api", "WARNING", "Transient startup note"),
        _row("api", "WARNING", "Health check: App 'code' is degraded. API: healthy, Worker: unhealthy"),
    ]

    issues = report.build_degraded_issue_report(rows, min_occurrences=3)

    assert issues == []


def test_format_degraded_report_includes_exact_messages():
    issues = [
        {
            "service": "api",
            "level": "ERROR",
            "logger": "backend.example",
            "message": "CRITICAL: Order pi_123 not found in cache. Payment was successful but credits cannot be granted.",
            "count": 7,
        }
    ]

    message = report.format_degraded_report_message(environment="production", issues=issues)

    assert "OpenMates production degraded services report" in message
    assert "7x [ERROR] api / backend.example" in message
    assert "Order pi_123 not found in cache" in message


def test_select_degraded_report_webhook_prefers_explicit(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_DEGRADED_SERVICES", "https://example.test/degraded")
    monkeypatch.setenv("DISCORD_WEBHOOK_PROD_SMOKE", "https://example.test/prod")

    assert report.select_degraded_report_webhook_url("production") == "https://example.test/degraded"


def test_select_degraded_report_webhook_falls_back_by_environment(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_DEGRADED_SERVICES", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_PROD_SMOKE", "https://example.test/prod")
    monkeypatch.setenv("DISCORD_WEBHOOK_DEV_SMOKE", "https://example.test/dev")

    assert report.select_degraded_report_webhook_url("production") == "https://example.test/prod"
    assert report.select_degraded_report_webhook_url("development") == "https://example.test/dev"
