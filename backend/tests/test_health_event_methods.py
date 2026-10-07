"""Health history failures must not be mistaken for an initial status."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.api.app.services.directus.health_event_methods import (
    HealthEventMethods, HealthStatusUnavailable,
)

# contract-test-file: infrastructure


@pytest.mark.anyio
@pytest.mark.parametrize("status,payload", [
    (503, {"errors": [{"message": "Under pressure"}]}),
    (403, {"errors": [{"message": "Forbidden"}]}),
    (200, {}), (200, {"data": {}}), (200, {"data": [{}]}),
])
async def test_unavailable_history_is_not_empty_history(status, payload):
    service = SimpleNamespace(base_url="http://cms:8055", _make_api_request=AsyncMock(
        return_value=httpx.Response(status, json=payload),
    ))
    with pytest.raises(HealthStatusUnavailable):
        await HealthEventMethods(service).get_last_status("app", "workflows")


@pytest.mark.anyio
@pytest.mark.parametrize("rows,expected", [
    ([], None),
    ([{"new_status": "healthy", "created_at": "2026-10-07T00:00:00Z"}],
     {"new_status": "healthy", "created_at": "2026-10-07T00:00:00Z"}),
])
async def test_successful_history_distinguishes_absence_from_previous_status(rows, expected):
    service = SimpleNamespace(base_url="http://cms:8055", _make_api_request=AsyncMock(
        return_value=httpx.Response(200, json={"data": rows}),
    ))
    assert await HealthEventMethods(service).get_last_status("app", "workflows") == expected


@pytest.mark.anyio
async def test_network_failure_is_not_empty_history():
    service = SimpleNamespace(base_url="http://cms:8055", _make_api_request=AsyncMock(
        side_effect=httpx.ConnectError("connection unavailable"),
    ))
    with pytest.raises(HealthStatusUnavailable):
        await HealthEventMethods(service).get_last_status("app", "workflows")
