# contract-test-file: infrastructure
"""
Contract tests for privacy-safe operational monitoring snapshots.

These tests define the aggregate report, rendering, delivery receipt, and
self-host omission boundaries without reaching live monitoring services.
Live dev delivery is verified separately by the spec's manual gate.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.api.app.services import operational_monitoring as monitoring


WINDOW_END = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
WINDOW_START = WINDOW_END - timedelta(hours=24)


def _snapshot(environment: str = "development", **overrides):
    values = {
        "environment": environment,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "resource_series": {
            "cpu_percent": [[WINDOW_START.timestamp(), 12.5], [WINDOW_END.timestamp(), 22.0]],
            "memory_percent": [[WINDOW_START.timestamp(), 41.0], [WINDOW_END.timestamp(), 48.0]],
            "disk_used_percent": [[WINDOW_START.timestamp(), 52.0], [WINDOW_END.timestamp(), 53.0]],
            "disk_free_bytes": [[WINDOW_START.timestamp(), 100_000_000], [WINDOW_END.timestamp(), 90_000_000]],
        },
        "activity_counts": {"chats": 7, "messages": 42, "embeds": 5, "usage_entries": 38},
        "processing_transactions": {"started": 42, "completed": 39, "failed": 2, "stuck": 1},
        "billing": {"status": "healthy", "started": 3, "completed": 2, "failed": 1},
        "telemetry_freshness": {
            "resource_metrics": "fresh",
            "application_metrics": "fresh",
            "report_scheduler": "fresh",
        },
        "issues": [],
    }
    values.update(overrides)
    return monitoring.build_operational_snapshot(**values)


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot
def test_snapshot_requires_exact_preceding_24_hour_window():
    snapshot = _snapshot()
    assert snapshot["window_hours"] == 24
    assert snapshot["window_start"] == WINDOW_START.isoformat()
    assert snapshot["window_end"] == WINDOW_END.isoformat()

    with pytest.raises(ValueError, match="24-hour"):
        _snapshot(window_start=WINDOW_START + timedelta(minutes=1))


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot,operational-monitoring.alerts.actionable-low-noise
def test_prioritized_issues_are_ranked_and_limited_to_three():
    issues = [
        {"fingerprint": "old-warning", "severity": "warning", "active": False, "count": 50, "last_seen": "2026-08-13T12:00:00Z"},
        {"fingerprint": "active-critical", "severity": "critical", "active": True, "count": 2, "last_seen": "2026-08-14T11:59:00Z"},
        {"fingerprint": "active-warning", "severity": "warning", "active": True, "count": 20, "last_seen": "2026-08-14T11:00:00Z"},
        {"fingerprint": "digest-noise", "severity": "digest", "active": True, "count": 100, "last_seen": "2026-08-14T11:58:00Z"},
    ]
    snapshot = _snapshot(issues=issues)
    assert len(snapshot["prioritized_issues"]) == 3
    assert snapshot["prioritized_issues"][0]["fingerprint"] == "active-critical"


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot,operational-monitoring.content.privacy-boundary
def test_compact_svg_and_png_render_deterministically():
    snapshot = _snapshot()
    first_svg = monitoring.render_operational_report_svg(snapshot)
    second_svg = monitoring.render_operational_report_svg(snapshot)
    png = monitoring.render_operational_report_png(snapshot)

    assert first_svg == second_svg
    assert first_svg.startswith("<svg")
    assert "CPU" in first_svg and "Memory" in first_svg and "Disk" in first_svg
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) < 2_000_000


# contract-test: direct surface=cli assertions=operational-monitoring.self-host.no-billing,operational-monitoring.content.privacy-boundary
def test_self_host_snapshot_omits_billing_entirely():
    snapshot = _snapshot(environment="self_host", billing=None)
    serialized = monitoring.serialize_operational_snapshot(snapshot)

    assert "billing" not in snapshot
    for forbidden in ("billing", "payment", "stripe", "invoice", "subscription", "purchase"):
        assert forbidden not in serialized.lower()

    with pytest.raises(ValueError, match="self-host"):
        _snapshot(environment="self_host", billing={"status": "not_applicable"})


# contract-test: direct surface=cli assertions=operational-monitoring.content.privacy-boundary
@pytest.mark.parametrize(
    "private_field",
    [
        "user_id", "encrypted_message", "encrypted_title", "payment_id", "webhook_url",
        "email_address", "raw_content", "stack_trace", "destination", "access_token",
    ],
)
def test_private_fields_are_rejected_recursively(private_field: str):
    with pytest.raises(ValueError, match="forbidden private field"):
        _snapshot(issues=[{"fingerprint": "unsafe", "severity": "warning", "details": {private_field: "secret"}}])


def test_snapshot_rejects_unknown_aggregate_and_issue_fields():
    with pytest.raises(ValueError, match="unsupported activity_counts"):
        _snapshot(activity_counts={"chats": 1, "messages": 1, "embeds": 1, "usage_entries": 1, "accounts": 1})
    with pytest.raises(ValueError, match="unsupported operational issue"):
        _snapshot(issues=[{"fingerprint": "unsafe", "severity": "warning", "debug": "not allowed"}])


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable,operational-monitoring.environments.isolated-labeled
def test_delivery_receipts_are_channel_specific_and_redacted():
    email = monitoring.create_delivery_receipt(
        environment="development",
        report_id="report-1",
        report_sha256="abc123",
        channel="email",
        state="accepted",
        attempt_count=1,
        occurred_at=WINDOW_END,
    )
    discord = monitoring.create_delivery_receipt(
        environment="development",
        report_id="report-1",
        report_sha256="abc123",
        channel="discord",
        state="failed",
        attempt_count=3,
        occurred_at=WINDOW_END,
        sanitized_failure_class="delivery_timeout",
    )

    assert email["state"] == "accepted"
    assert discord["state"] == "failed"
    assert monitoring.summarize_delivery_state([email, discord]) == "partial_failure"
    assert set(email) == {
        "environment", "report_id", "report_sha256", "channel", "state",
        "attempt_count", "occurred_at", "sanitized_failure_class",
    }


# contract-test: direct surface=cli assertions=operational-monitoring.environments.isolated-labeled
def test_environment_subjects_are_explicit_and_isolated():
    assert monitoring.report_subject("development").startswith("[OpenMates DEV]")
    assert monitoring.report_subject("production").startswith("[OpenMates PROD]")
    assert monitoring.report_subject("self_host").startswith("[OpenMates SELF-HOST]")


@pytest.mark.asyncio
async def test_collection_counts_processing_jobs_without_exposing_billing_to_self_host(monkeypatch):
    calls = []

    async def fake_count(_service, collection, **kwargs):
        calls.append((collection, kwargs["timestamp_field"], kwargs.get("timestamp_format"), kwargs.get("extra_filter")))
        return len(calls)

    monkeypatch.setattr(monitoring, "_directus_count", fake_count)
    activity, processing, billing = await monitoring.collect_activity_and_transactions(
        object(), environment="self_host", start=WINDOW_START, end=WINDOW_END,
    )

    assert activity == {"chats": 1, "messages": 2, "embeds": 3, "usage_entries": 4}
    assert processing == {"started": 5, "completed": 6, "failed": 7, "stuck": 8}
    assert billing is None
    assert all(collection != "billing_charge_identities" for collection, _, _, _ in calls)
    assert [call[:3] for call in calls[:4]] == [
        (collection, "created_at", "unix_seconds")
        for collection in ("chats", "messages", "embeds", "usage")
    ]
    assert calls[4][1] == "created_at"
    assert calls[5][1] == "completed_at"
    assert calls[6][1] == "invalidated_at"


@pytest.mark.asyncio
async def test_usage_count_filters_integer_created_at_timestamps():
    class FakeDirectus:
        base_url = "http://cms:8055"

        async def ensure_auth_token(self, *, admin_required):
            assert admin_required is True
            return "token"

        async def _make_api_request(self, _method, _url, *, params, headers):
            assert headers == {"Authorization": "Bearer token"}
            filters = monitoring.json.loads(params["filter"])["_and"]
            assert filters == [
                {"created_at": {"_gte": int(WINDOW_START.timestamp())}},
                {"created_at": {"_lt": int(WINDOW_END.timestamp())}},
            ]

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"meta": {"filter_count": 12}}

            return Response()

    count = await monitoring._directus_count(
        FakeDirectus(),
        "usage",
        timestamp_field="created_at",
        timestamp_format="unix_seconds",
        start=WINDOW_START,
        end=WINDOW_END,
    )
    assert count == 12


@pytest.mark.asyncio
async def test_official_cloud_collection_includes_aggregate_billing_outcomes(monkeypatch):
    calls = []

    async def fake_count(_service, collection, **kwargs):
        calls.append(collection)
        return 0 if collection == "billing_charge_identities" else 1

    monkeypatch.setattr(monitoring, "_directus_count", fake_count)
    _, _, billing = await monitoring.collect_activity_and_transactions(
        object(), environment="development", start=WINDOW_START, end=WINDOW_END,
    )

    assert billing == {"status": "healthy", "started": 0, "completed": 0, "failed": 0}
    assert calls.count("billing_charge_identities") == 3


@pytest.mark.asyncio
async def test_delivery_retries_are_bounded_and_report_attempts(monkeypatch):
    attempts = 0

    async def eventually_succeeds():
        nonlocal attempts
        attempts += 1
        return attempts == 3

    monkeypatch.setattr(monitoring.asyncio, "sleep", lambda _delay: _completed_sleep())
    accepted, attempt_count, failure = await monitoring.deliver_with_retries(
        eventually_succeeds, failure_class="delivery_failed",
    )
    assert (accepted, attempt_count, failure) == (True, 3, None)


async def _completed_sleep():
    return None
