"""Verify Google search supplies the local-time evidence consumed by maps."""

from datetime import datetime, timezone

import httpx
import pytest

from backend.apps.maps.opening_hours import ClosingTimeConstraint, matches_closing_time
from backend.shared.providers.google_maps import google_places


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("closing_hour,expected", [(17, False), (22, True)])
# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
async def test_google_places_retains_structured_local_hours_for_filtering(monkeypatch, closing_hour, expected, anyio_backend):
    raw = {
        "id": "synthetic-cafe", "displayName": {"text": "Evening Coffee"}, "types": ["cafe"],
        "utcOffsetMinutes": 120,
        "currentOpeningHours": {"periods": [{
            "open": {"day": 5, "hour": 8, "minute": 0},
            "close": {"day": 5, "hour": closing_hour, "minute": 0},
        }]},
    }

    async def api_key(_):
        return "synthetic-provider-key"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, json, headers):
            fields = headers["X-Goog-FieldMask"].split(',')
            assert "places.utcOffsetMinutes" in fields
            assert "places.currentOpeningHours" in fields
            assert "places.regularOpeningHours" in fields
            return httpx.Response(200, json={"places": [raw]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(google_places, "_get_google_maps_api_key", api_key)
    monkeypatch.setattr(google_places.httpx, "AsyncClient", Client)
    result = await google_places.search_places(text_query="cafes", secrets_manager=object())
    assert result["error"] is None
    constraint = ClosingTimeConstraint.from_request({"openUntil": "21:00"})
    assert matches_closing_time(result["results"][0], constraint, now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc)) is expected
