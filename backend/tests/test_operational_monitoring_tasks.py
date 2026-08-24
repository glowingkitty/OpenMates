"""
Behavior tests for operational report environment and destination isolation.

These tests exercise pure configuration resolution used by the delivery task,
without importing Celery or reading local secrets. Self-host destinations must
never inherit development or production notification channels.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.api.app.services.operational_monitoring import (
    build_operational_snapshot,
    build_operational_discord_summary,
    resolve_operational_discord_webhook,
    resolve_operations_discord_destination,
    resolve_operational_environment,
)


WINDOW_END = datetime(2026, 8, 15, 21, 37, tzinfo=timezone.utc)
WINDOW_START = WINDOW_END - timedelta(hours=24)


def _test_snapshot():
    return build_operational_snapshot(
        environment="development",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        resource_series={"cpu_percent": [], "memory_percent": [], "disk_used_percent": [], "disk_free_bytes": []},
        activity_counts={"chats": 1, "messages": 2, "embeds": 3, "usage_entries": 4},
        processing_transactions={"created": 5, "completed": 6, "invalidated": 7, "non_terminal_over_15m": 8},
        provider_health={"status": "healthy", "healthy_count": 2, "unavailable_names": [], "skipped_names": [], "stale_names": [], "checked_at": WINDOW_END.isoformat()},
        telemetry_freshness={"resource_metrics": "fresh", "application_metrics": "fresh", "report_scheduler": "fresh"},
        issues=[],
        billing={
            "status": "warming",
            "purchase_count": "withheld",
            "credits_sold": "withheld",
            "usage_committed": 4,
            "usage_failed": 0,
            "bank_review": 0,
            "refund_failed": 0,
            "chargebacks": 0,
            "incomplete_settlements": 0,
            "purchase_window_complete": False,
            "purchase_window_label": "withheld until ledger is complete",
        },
    )


# contract-test: direct surface=cli assertions=operational-monitoring.environments.isolated-labeled
def test_operational_environment_fails_closed_and_labels_official_cloud():
    assert resolve_operational_environment("self_host", "production") == "self_host"
    assert resolve_operational_environment("official_cloud", "production") == "production"
    assert resolve_operational_environment("official_cloud", "development") == "development"
    with pytest.raises(RuntimeError, match="not_configured"):
        resolve_operational_environment("", "development")


# contract-test: direct surface=cli assertions=operational-monitoring.environments.isolated-labeled
def test_operational_discord_destinations_are_environment_isolated():
    environ = {
        "DISCORD_WEBHOOK_PROD_SMOKE": "prod",
        "DISCORD_WEBHOOK_DEV_SMOKE": "dev",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL": "self-host",
    }
    assert resolve_operational_discord_webhook("production", environ) == "prod"
    assert resolve_operational_discord_webhook("development", environ) == "dev"
    assert resolve_operational_discord_webhook("self_host", environ) == "self-host"
    assert resolve_operational_discord_webhook(
        "self_host", {"OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_SELF_HOST": "self-host-specific"},
    ) == "self-host-specific"


# contract-test: direct surface=cli assertions=operational-monitoring.notifications.canonical-operations-channel,operational-monitoring.environments.isolated-labeled
def test_production_operations_destination_prefers_canonical_and_reports_fallback():
    canonical = resolve_operations_discord_destination("production", {
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION": "canonical",
        "DISCORD_WEBHOOK_PROD_SMOKE": "fallback",
    })
    fallback = resolve_operations_discord_destination("production", {
        "DISCORD_WEBHOOK_PROD_SMOKE": "fallback",
    })
    missing = resolve_operations_discord_destination("production", {})

    assert canonical == {"url": "canonical", "source": "canonical", "fallback_used": False}
    assert fallback == {"url": "fallback", "source": "prod_smoke_fallback", "fallback_used": True}
    assert missing == {"url": None, "source": "missing", "fallback_used": False}


# contract-test: direct surface=cli assertions=operational-monitoring.self-host.no-billing,operational-monitoring.environments.isolated-labeled
def test_self_host_does_not_fall_back_to_dev_or_prod_destinations():
    assert resolve_operational_discord_webhook(
        "self_host", {"DISCORD_WEBHOOK_DEV_SMOKE": "dev", "DISCORD_WEBHOOK_PROD_SMOKE": "prod"},
    ) is None


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable,operational-monitoring.environments.isolated-labeled
def test_test_discord_summary_starts_with_unique_report_context():
    summary = build_operational_discord_summary(
        _test_snapshot(),
        test=True,
        report_id="operational-development-20260815T213737Z-2786792c",
    )
    first_line = summary.splitlines()[0]

    assert "TEST" in first_line
    assert "operational-development-20260815T213737Z-2786792c" in first_line
