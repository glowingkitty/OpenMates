"""
Behavior tests for operational report environment and destination isolation.

These tests exercise pure configuration resolution used by the delivery task,
without importing Celery or reading local secrets. Self-host destinations must
never inherit development or production notification channels.
"""

import pytest

from backend.core.api.app.services.operational_monitoring import (
    resolve_operational_discord_webhook,
    resolve_operational_environment,
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


# contract-test: direct surface=cli assertions=operational-monitoring.self-host.no-billing,operational-monitoring.environments.isolated-labeled
def test_self_host_does_not_fall_back_to_dev_or_prod_destinations():
    assert resolve_operational_discord_webhook(
        "self_host", {"DISCORD_WEBHOOK_DEV_SMOKE": "dev", "DISCORD_WEBHOOK_PROD_SMOKE": "prod"},
    ) is None
