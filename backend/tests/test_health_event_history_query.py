"""Regression: health_events.created_at is a Directus string field, so range
operators (_gte/_lt) return HTTP 400. Time bounds are applied after the read."""
# contract-test-file: infrastructure
import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.core.api.app.services.directus.health_event_methods import HealthEventMethods

NEW = {"id": "new", "service_type": "app", "service_id": "ai", "new_status": "healthy", "created_at": "2023-11-15T10:00:00.123456+00:00"}
EDGE = {"id": "edge", "service_type": "app", "service_id": "ai", "new_status": "unhealthy", "created_at": "2023-11-14T22:13:20+00:00"}
OLD = {"id": "old", "service_type": "app", "service_id": "ai", "new_status": "unhealthy", "created_at": "2023-11-01T00:00:00+00:00"}


def _methods(rows):
    ds = MagicMock(base_url="http://cms")
    ds._make_api_request = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"data": rows}))
    ds.delete_items = AsyncMock(return_value=(True, None))
    return ds, HealthEventMethods(ds)


def test_history_never_sends_a_range_filter_and_bounds_after_read():
    ds, m = _methods([NEW, EDGE, OLD])
    events = asyncio.run(m.get_health_history(since_timestamp=1_700_000_000))
    url = ds._make_api_request.await_args.args[1]
    assert "_gte" not in url and "_lt" not in url and "+" not in url
    assert "sort=-created_at" in url
    assert [e["id"] for e in events] == ["new", "edge"]


def test_incident_summary_counts_only_events_in_window():
    ds, m = _methods([EDGE, OLD])
    summary = asyncio.run(m.get_incident_summary(since_timestamp=1_700_000_000))
    url = ds._make_api_request.await_args.args[1]
    assert "filter[created_at]" not in url
    assert summary["total_incidents"] == 1


def test_cleanup_deletes_only_events_past_retention():
    ds, m = _methods([OLD, EDGE, NEW])
    deleted = asyncio.run(m.cleanup_old_events(retention_days=1))
    url = ds._make_api_request.await_args.args[1]
    assert "filter[created_at]" not in url and "sort=created_at" in url
    assert deleted == 3
    ds2, m2 = _methods([OLD])
    from datetime import datetime, timezone
    days = (datetime.now(timezone.utc) - datetime(2023, 11, 8, tzinfo=timezone.utc)).days
    assert asyncio.run(m2.cleanup_old_events(retention_days=days)) == 1
    assert ds2.delete_items.await_args.args[1] == ["old"]
