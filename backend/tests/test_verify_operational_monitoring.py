"""
Behavior tests for the operational monitoring delivery verifier.

The verifier must parse only its structured CLI result and require an exact
environment/channel match with accepted per-channel receipts. Process success
alone must never count as delivery evidence.
"""

import json

from scripts.verify_operational_monitoring import (
    _active_drill_count,
    _build_drill_alert,
    _delivery_delta_accepted,
    _delivery_samples_accepted,
    _drill_receivers,
    _is_development_environment,
    _metric_value,
    _parse_output,
    _receipts_accepted,
    _webhook_log_has_receipt,
)


def _result(*, discord_state: str = "accepted") -> dict:
    return {
        "command": "monitoring digest",
        "deliveryState": "accepted" if discord_state == "accepted" else "partial_failure",
        "reportId": "report-1",
        "reportSha256": "abc123",
        "receipts": [
            {"environment": "development", "channel": "email", "state": "accepted"},
            {"environment": "development", "channel": "discord", "state": discord_state},
        ],
    }


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable
def test_verifier_parses_structured_cli_output_after_non_json_lines():
    result = _result()
    assert _parse_output(f"building CLI\n{json.dumps(result)}\n") == result


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.real-data-test,operational-monitoring.environments.isolated-labeled
def test_verifier_requires_exact_accepted_environment_and_channels():
    result = _result()
    assert _receipts_accepted(result, channels={"email", "discord"}, environment="development", returncode=0)
    assert not _receipts_accepted(result, channels={"email"}, environment="development", returncode=0)
    assert not _receipts_accepted(result, channels={"email", "discord"}, environment="production", returncode=0)
    assert not _receipts_accepted(result, channels={"email", "discord"}, environment="development", returncode=1)
    assert not _receipts_accepted(_result(discord_state="failed"), channels={"email", "discord"}, environment="development", returncode=0)


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable
def test_drill_alert_is_explicitly_labeled_and_bounded():
    alert = _build_drill_alert("api-down", "drill-123", resolved=False)
    resolved = _build_drill_alert("api-down", "drill-123", resolved=True)

    assert alert["labels"] == {
        "alertname": "APIDown",
        "severity": "critical",
        "environment": "development",
        "drill": "true",
        "drill_id": "drill-123",
    }
    assert alert["annotations"]["summary"].startswith("[DEV DRILL]")
    assert alert["startsAt"] < alert["endsAt"]
    assert resolved["startsAt"] < resolved["endsAt"]
    assert resolved["endsAt"] <= alert["endsAt"]


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable
def test_active_drill_count_requires_exact_run_identity():
    alerts = [
        {"labels": {"drill": "true", "drill_id": "drill-123"}, "status": {"state": "active"}},
        {"labels": {"drill": "true", "drill_id": "other"}, "status": {"state": "active"}},
        {"labels": {"drill": "true", "drill_id": "drill-123"}, "status": {"state": "suppressed"}},
    ]

    assert _active_drill_count(alerts, "drill-123") == 1


# contract-test: supporting surface=cli assertions=operational-monitoring.delivery.observable
def test_metric_value_reads_only_the_requested_integration():
    metrics = """
alertmanager_notification_requests_total{integration="discord"} 4
alertmanager_notification_requests_total{integration="webhook"} 7
"""

    assert _metric_value(metrics, "alertmanager_notification_requests_total", "discord") == 4
    assert _metric_value(metrics, "alertmanager_notification_requests_total", "webhook") == 7
    assert _metric_value(metrics, "alertmanager_notification_requests_total", "email") == 0


# contract-test: supporting surface=cli assertions=operational-monitoring.delivery.observable
def test_delivery_delta_rejects_unrelated_or_failed_requests():
    before = {"discord": {"requests": 4, "completed": 4, "failed": 1}}

    assert _delivery_delta_accepted(before, {"discord": {"requests": 5, "completed": 5, "failed": 1}})
    assert not _delivery_delta_accepted(before, {"discord": {"requests": 5, "completed": 4, "failed": 1}})
    assert not _delivery_delta_accepted(before, {"discord": {"requests": 6, "completed": 5, "failed": 1}})
    assert not _delivery_delta_accepted(before, {"discord": {"requests": 5, "completed": 5, "failed": 2}})


# contract-test: supporting surface=cli assertions=operational-monitoring.delivery.observable
def test_delivery_requires_two_stable_completed_samples():
    before = {"discord": {"requests": 4, "completed": 4, "failed": 1}}
    accepted = {"discord": {"requests": 5, "completed": 5, "failed": 1}}
    failed_after_settle = {"discord": {"requests": 5, "completed": 5, "failed": 2}}

    assert _delivery_samples_accepted(before, [accepted, accepted])
    assert not _delivery_samples_accepted(before, [accepted, failed_after_settle])


# contract-test: supporting surface=cli assertions=operational-monitoring.delivery.observable
def test_drill_receivers_are_correlated_by_run_identity():
    groups = [
        {
            "receiver": {"name": "urgent-discord"},
            "alerts": [{"labels": {"drill": "true", "drill_id": "drill-123"}}],
        },
        {
            "receiver": {"name": "api-webhook"},
            "alerts": [{"labels": {"drill": "true", "drill_id": "other"}}],
        },
    ]

    assert _drill_receivers(groups, "drill-123") == {"urgent-discord"}


# contract-test: direct surface=cli assertions=operational-monitoring.environments.isolated-labeled
def test_drills_accept_only_explicit_development_runtime_values():
    assert _is_development_environment("development")
    assert _is_development_environment("dev")
    assert not _is_development_environment("production")
    assert not _is_development_environment("")


# contract-test: supporting surface=cli assertions=operational-monitoring.delivery.observable
def test_webhook_receipt_requires_matching_drill_and_lifecycle_status():
    log = "Alertmanager webhook received: status=firing, alert_count=1, group_labels={'drill_id': 'drill-123'}"

    assert _webhook_log_has_receipt(log, "drill-123", "firing")
    assert not _webhook_log_has_receipt(log, "other", "firing")
    assert not _webhook_log_has_receipt(log, "drill-123", "resolved")
    mismatched_lines = "\n".join([
        "Alertmanager webhook received: status=firing, group_labels={'drill_id': 'other'}",
        "Alertmanager webhook received: status=resolved, group_labels={'drill_id': 'drill-123'}",
    ])
    assert not _webhook_log_has_receipt(mismatched_lines, "drill-123", "firing")
