# contract-test-file: infrastructure
"""
Contract tests for privacy-safe operational monitoring snapshots.

These tests define the aggregate report, rendering, delivery receipt, and
self-host omission boundaries without reaching live monitoring services.
Live dev delivery is verified separately by the spec's manual gate.
"""

from datetime import datetime, timedelta, timezone
import logging

import httpx
import pytest

from backend.core.api.app.services import operational_monitoring as monitoring
from backend.core.api.app.services.cache_stats_mixin import CacheStatsMixin
from backend.core.api.app.utils.log_filters import SensitiveDataFilter


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
        "processing_transactions": {"created": 42, "completed": 39, "invalidated": 2, "non_terminal_over_15m": 1},
        "provider_health": {
            "status": "degraded",
            "healthy_count": 2,
            "unavailable_names": ["example_provider"],
            "skipped_names": ["vercel"],
            "stale_names": [],
            "checked_at": WINDOW_END.isoformat(),
        },
        "billing": {
            "status": "degraded",
            "purchase_count": 3,
            "credits_sold": 300,
            "usage_committed": 38,
            "usage_failed": 1,
            "bank_review": 1,
            "refund_failed": 0,
            "chargebacks": 0,
            "incomplete_settlements": 0,
            "purchase_window_complete": True,
            "purchase_window_label": "exact rolling 24h",
        },
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
    assert "Providers:" in first_svg and "Payment readiness:" in first_svg
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) < 2_000_000


def test_rendered_report_labels_withheld_purchase_totals_without_exact_claim():
    snapshot = _snapshot(billing={
        "status": "warming",
        "purchase_count": "withheld",
        "credits_sold": "withheld",
        "usage_committed": 0,
        "usage_failed": 0,
        "bank_review": 0,
        "refund_failed": 0,
        "chargebacks": 0,
        "incomplete_settlements": 0,
        "purchase_window_complete": False,
        "purchase_window_label": "withheld until ledger is complete",
    })

    svg = monitoring.render_operational_report_svg(snapshot)

    assert "Cloud credit purchases · withheld until ledger is complete" in svg
    assert "Cloud credit purchases · exact rolling 24h" not in svg


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
        "attempt_count", "occurred_at", "sanitized_failure_class", "destination_source", "fallback_used",
    }


# contract-test: direct surface=cli assertions=operational-monitoring.environments.isolated-labeled
def test_environment_subjects_are_explicit_and_isolated():
    assert monitoring.report_subject("development").startswith("[OpenMates DEV]")
    assert monitoring.report_subject("production").startswith("[OpenMates PROD]")
    assert monitoring.report_subject("self_host").startswith("[OpenMates SELF-HOST]")


# contract-test: direct surface=cli assertions=operational-monitoring.providers.current-availability,operational-monitoring.content.privacy-boundary
def test_provider_health_groups_nonhealthy_names_and_rejects_stale_as_healthy():
    records = {
        "openai": {"status": "healthy", "last_check": WINDOW_END.timestamp()},
        "stripe": {"status": "healthy", "last_check": WINDOW_END.timestamp()},
        "example_provider": {"status": "unhealthy", "last_check": WINDOW_END.timestamp()},
        "vercel": {"status": "skipped", "last_check": WINDOW_END.timestamp()},
        "stale_provider": {"status": "healthy", "last_check": (WINDOW_END - timedelta(hours=1)).timestamp()},
    }

    summary = monitoring.summarize_provider_health(
        records,
        now=WINDOW_END,
        stale_after=timedelta(minutes=15),
    )

    assert summary == {
        "status": "degraded",
        "healthy_count": 2,
        "unavailable_names": ["example_provider"],
        "skipped_names": ["vercel"],
        "stale_names": ["stale_provider"],
        "checked_at": WINDOW_END.isoformat(),
    }
    assert "last_error" not in str(summary)


def test_provider_health_never_treats_empty_or_missing_inventory_as_healthy():
    assert monitoring.summarize_provider_health({}, now=WINDOW_END)["status"] == "unavailable"

    summary = monitoring.summarize_provider_health(
        {"openai": {"status": "healthy", "last_check": WINDOW_END.timestamp()}},
        now=WINDOW_END,
        expected_names=["openai", "missing_provider"],
    )

    assert summary["status"] == "degraded"
    assert summary["unavailable_names"] == ["missing_provider"]


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness,operational-monitoring.content.privacy-boundary
@pytest.mark.asyncio
async def test_billing_readiness_omits_internal_destination_checks_from_snapshot():
    class FakeClient:
        async def get(self, _key):
            return monitoring.json.dumps({
                "readiness": {
                    "status": "degraded",
                    "eu_card": "healthy",
                    "managed_payments": "unavailable",
                    "missing_products": [],
                    "missing_events": ["checkout.session.completed"],
                    "checked_at": WINDOW_END.isoformat(),
                    "checks": {"destination_enabled": True},
                },
            })

    class FakeCache:
        client = _completed_value(FakeClient())

    readiness = await monitoring.collect_billing_readiness(FakeCache(), now=WINDOW_END)
    snapshot = _snapshot(billing_readiness=readiness)

    assert readiness["eu_card"] == "healthy"
    assert "checks" not in snapshot["billing_readiness"]
    assert "destination" not in monitoring.serialize_operational_snapshot(snapshot)


def test_provider_health_is_visible_in_discord_summary():
    summary = monitoring.build_operational_discord_summary(
        _snapshot(),
        test=False,
        report_id="operational-production-provider-health",
    )

    assert "Providers: 2 healthy" in summary
    assert "unavailable example_provider" in summary
    assert "skipped vercel" in summary
    assert len(summary.splitlines()) <= 5


def test_discord_summary_bounds_large_provider_inventory_without_silent_slicing():
    provider_health = {
        "status": "degraded",
        "healthy_count": 0,
        "unavailable_names": [f"provider_{index:03d}_with_a_long_but_safe_name" for index in range(100)],
        "skipped_names": [],
        "stale_names": [],
        "checked_at": WINDOW_END.isoformat(),
    }

    summary = monitoring.build_operational_discord_summary(
        _snapshot(provider_health=provider_health),
        test=False,
        report_id="bounded-provider-summary",
    )

    assert len(summary) <= 2000
    assert "+95 more" in summary


@pytest.mark.asyncio
async def test_collection_counts_processing_jobs_without_exposing_billing_to_self_host(monkeypatch):
    calls = []

    async def fake_count(_service, collection, **kwargs):
        calls.append((collection, kwargs["timestamp_field"], kwargs.get("timestamp_format"), kwargs.get("extra_filter")))
        return len(calls)

    async def fake_current_count(_service, collection, **kwargs):
        calls.append((collection, None, None, kwargs["filters"]))
        return len(calls)

    async def fake_sum(_service, collection, **kwargs):
        calls.append((collection, kwargs["field"], None, kwargs["filters"]))
        return len(calls)

    monkeypatch.setattr(monitoring, "_directus_count", fake_count)
    monkeypatch.setattr(monitoring, "_directus_current_count", fake_current_count)
    monkeypatch.setattr(monitoring, "_directus_sum", fake_sum)
    activity, processing, billing = await monitoring.collect_activity_and_transactions(
        object(), environment="self_host", start=WINDOW_START, end=WINDOW_END,
    )

    assert activity == {"chats": 1, "messages": 2, "embeds": 3, "usage_entries": 4}
    assert processing == {"created": 5, "completed": 6, "invalidated": 7, "non_terminal_over_15m": 8}
    assert billing is None
    assert all(collection != "billing_charge_identities" for collection, _, _, _ in calls)
    assert [call[:3] for call in calls[:4]] == [
        (collection, "created_at", "unix_seconds")
        for collection in ("chats", "messages", "embeds", "usage")
    ]
    assert calls[4][1] == "created_at"
    assert calls[5][1] == "completed_at"
    assert calls[6][0] == "operational_monitoring_events"
    assert calls[6][1] == "count"
    assert calls[7][0] == "chat_completion_recovery_jobs"
    assert calls[7][3] == {"_and": [
        {"completed_at": {"_null": True}},
        {"invalidated_at": {"_null": True}},
        {"created_at": {"_lt": (WINDOW_END - timedelta(minutes=15)).isoformat()}},
    ]}


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


# contract-test: direct surface=cli assertions=operational-monitoring.content.privacy-boundary
def test_sensitive_log_filter_redacts_discord_webhook_destinations():
    webhook_id = "123456789012345678"
    webhook_token = "secret_webhook_token"
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        'HTTP Request: %s %s "%s %d %s"',
        ("POST", httpx.URL(f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"), "HTTP/1.1", 200, "OK"),
        None,
    )
    SensitiveDataFilter().filter(record)
    filtered = record.getMessage()

    assert webhook_id not in filtered
    assert webhook_token not in filtered
    assert "https://discord.com/api/webhooks/[REDACTED]" in filtered


@pytest.mark.asyncio
async def test_official_cloud_collection_includes_aggregate_billing_outcomes(monkeypatch):
    calls = []

    async def fake_count(_service, collection, **kwargs):
        calls.append(collection)
        return 0 if collection == "billing_charge_identities" else 1

    monkeypatch.setattr(monitoring, "_directus_count", fake_count)
    monkeypatch.setattr(monitoring, "_directus_sum", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_purchase_ledger_totals", lambda *_args, **_kwargs: _completed_value((2, 250, True, 0)))
    monkeypatch.setattr(monitoring, "_directus_current_count", lambda *_args, **kwargs: _completed_value(
        1 if kwargs["filters"] == {"status": {"_eq": "admin_review"}} else 0
    ))
    _, _, billing = await monitoring.collect_activity_and_transactions(
        object(), cache_service=object(), environment="development", start=WINDOW_START, end=WINDOW_END,
    )

    assert billing == {
        "status": "degraded",
        "purchase_count": 2,
        "credits_sold": 250,
        "usage_committed": 0,
        "usage_failed": 0,
        "bank_review": 1,
        "refund_failed": 0,
        "chargebacks": 0,
        "incomplete_settlements": 0,
        "purchase_window_complete": True,
        "purchase_window_label": "exact rolling 24h",
    }
    assert calls.count("billing_charge_identities") == 2


@pytest.mark.asyncio
async def test_purchase_totals_sum_only_events_inside_exact_window(monkeypatch):
    class FakeDirectus:
        async def get_items(self, collection, params, **_kwargs):
            assert collection == monitoring.PURCHASE_SETTLEMENT_COLLECTION
            filters = params["filter"]["_and"]
            assert {"completed_at": {"_gte": WINDOW_START.isoformat()}} in filters
            assert {"completed_at": {"_lt": WINDOW_END.isoformat()}} in filters
            return [{"credits_sold": 200}, {"credits_sold": 50}]

    async def fake_watermark(_service, *, started_at):
        assert started_at == WINDOW_END
        return {"started_at": (WINDOW_START - timedelta(minutes=1)).isoformat()}

    monkeypatch.setattr(monitoring, "ensure_purchase_ledger_watermark", fake_watermark)
    monkeypatch.setattr(monitoring, "_directus_current_count", lambda *_args, **_kwargs: _completed_value(0))
    result = await monitoring._purchase_ledger_totals(
        FakeDirectus(), start=WINDOW_START, end=WINDOW_END,
    )
    assert result == (2, 250, True, 0)


@pytest.mark.asyncio
async def test_purchase_ledger_watermark_accepts_directus_naive_timestamp(monkeypatch):
    class FakeDirectus:
        async def get_items(self, collection, params, **_kwargs):
            assert collection == monitoring.PURCHASE_SETTLEMENT_COLLECTION
            return []

    async def fake_watermark(_service, *, started_at):
        assert started_at == WINDOW_END
        return {"started_at": WINDOW_START.replace(tzinfo=None).isoformat()}

    monkeypatch.setattr(monitoring, "ensure_purchase_ledger_watermark", fake_watermark)
    monkeypatch.setattr(monitoring, "_directus_current_count", lambda *_args, **_kwargs: _completed_value(0))

    result = await monitoring._purchase_ledger_totals(
        FakeDirectus(), start=WINDOW_START, end=WINDOW_END,
    )
    assert result == (0, 0, True, 0)


@pytest.mark.asyncio
async def test_purchase_stats_atomically_update_daily_analytics():
    calls = []

    class FakePipeline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def hincrby(self, *args):
            calls.append(("hincrby", *args))
            return self

        def expire(self, *args):
            calls.append(("expire", *args))
            return self

        async def execute(self):
            calls.append(("execute",))

    class FakeClient:
        def pipeline(self, *, transaction):
            assert transaction is True
            return FakePipeline()

    client = FakeClient()

    class FakeCache(CacheStatsMixin):
        @property
        def client(self):
            return _completed_value(client)

    cache = FakeCache()
    await cache.record_credit_purchase(250, "2026-08-15")

    assert [call[2:] for call in calls if call[0] == "hincrby"] == [
        ("purchase_count", 1),
        ("credits_sold", 250),
    ]
    assert calls[-1] == ("execute",)


@pytest.mark.asyncio
async def test_atomic_daily_purchase_analytics_failure_is_visible(caplog):
    class FailingPipeline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self

        async def execute(self):
            raise RuntimeError("transaction failed")

    class FakeClient:
        def pipeline(self, *, transaction):
            assert transaction is True
            return FailingPipeline()

    class FakeCache(CacheStatsMixin):
        @property
        def client(self):
            return _completed_value(FakeClient())

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="transaction failed"):
        await FakeCache().record_credit_purchase(250)

    assert "Daily purchase analytics transaction failed" in caplog.text


@pytest.mark.asyncio
async def test_billing_ledger_failure_keeps_digest_available(monkeypatch):
    async def fake_count(_service, _collection, **_kwargs):
        return 0

    async def unavailable_totals(*_args, **_kwargs):
        raise RuntimeError("ledger unavailable")

    async def no_open_issues(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(monitoring, "_directus_count", fake_count)
    monkeypatch.setattr(monitoring, "_directus_sum", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_directus_current_count", no_open_issues)
    monkeypatch.setattr(monitoring, "_purchase_ledger_totals", unavailable_totals)

    _, _, billing = await monitoring.collect_activity_and_transactions(
        object(), cache_service=object(), environment="development", start=WINDOW_START, end=WINDOW_END,
    )

    assert billing["status"] == "unavailable"
    assert billing["purchase_window_complete"] is False


@pytest.mark.asyncio
async def test_incomplete_settlement_withholds_partial_purchase_totals(monkeypatch):
    monkeypatch.setattr(monitoring, "_directus_count", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_directus_sum", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_directus_current_count", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(
        monitoring,
        "_purchase_ledger_totals",
        lambda *_args, **_kwargs: _completed_value((2, 250, True, 1)),
    )

    _, _, billing = await monitoring.collect_activity_and_transactions(
        object(), environment="development", start=WINDOW_START, end=WINDOW_END,
    )

    assert billing["status"] == "unavailable"
    assert billing["purchase_count"] == "withheld"
    assert billing["credits_sold"] == "withheld"


@pytest.mark.asyncio
async def test_warming_ledger_withholds_partial_purchase_totals(monkeypatch):
    monkeypatch.setattr(monitoring, "_directus_count", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_directus_sum", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(monitoring, "_directus_current_count", lambda *_args, **_kwargs: _completed_value(0))
    monkeypatch.setattr(
        monitoring,
        "_purchase_ledger_totals",
        lambda *_args, **_kwargs: _completed_value((2, 250, False, 0)),
    )

    _, _, billing = await monitoring.collect_activity_and_transactions(
        object(), environment="development", start=WINDOW_START, end=WINDOW_END,
    )

    assert billing["status"] == "warming"
    assert billing["purchase_count"] == "withheld"
    assert billing["credits_sold"] == "withheld"
    assert billing["purchase_window_label"] == "withheld until ledger is complete"


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


async def _completed_value(value):
    return value
