"""Focused provider regressions for Events Search reliability."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.apps.events.providers import berlin_philharmonic
from backend.apps.events.providers import google_events
from backend.apps.events.providers import siegessaeule


# contract-test: direct surface=rest_api assertions=events-search.request.validated,events-search.surface-parity
def test_philharmonic_filter_uses_requested_epoch_window() -> None:
    start_epoch = berlin_philharmonic._iso_to_epoch("2026-10-01T00:00:00Z")
    end_epoch = berlin_philharmonic._iso_to_epoch("2026-11-01T00:00:00Z")

    expression = berlin_philharmonic._build_filter_expression(
        include_guest_events=False,
        tags=[],
        include_past=False,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
    )

    assert f"time_start:>={start_epoch}" in expression
    assert f"time_start:<{end_epoch}" in expression
    assert berlin_philharmonic._epoch_to_iso(start_epoch) == "2026-10-01T00:00:00Z"


# contract-test: direct surface=rest_api assertions=events-search.request.validated
def test_google_virtual_event_chip_normalizes_results_as_online() -> None:
    event = google_events._normalize_event(
        {
            "title": "Remote Rust Workshop",
            "link": "https://example.invalid/rust",
            "date": {"when": "Oct 10, 6 PM"},
        },
        requested_event_type="ONLINE",
    )

    assert event["event_type"] == "ONLINE"


# contract-test: direct surface=rest_api assertions=events-search.providers.explicit,events-search.request.validated
@pytest.mark.anyio
async def test_siegessaeule_403_falls_back_to_public_calendar_html(monkeypatch) -> None:
    sample_html = """
    <a href="/termine/kultur/queer-tech/2026-10-10/19:30/">
      <h4>Queer Tech Community Night</h4>
      <span>10. Oktober 2026, 19:30</span>
      <p>Talks and community networking</p>
      <span>Example Venue</span>
    </a>
    """

    class FakeResponse:
        def __init__(self, *, status_code: int, text: str = "") -> None:
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                request = httpx.Request("POST", "https://www.siegessaeule.de/graphql/")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("blocked", request=request, response=response)

        def json(self) -> dict[str, Any]:
            return {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(status_code=403)

        async def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
            assert kwargs["params"] == {"date": "2026-10-10"}
            return FakeResponse(status_code=200, text=sample_html)

    monkeypatch.setattr(siegessaeule.httpx, "AsyncClient", FakeClient)

    events, total = await siegessaeule.search_events_async(
        city="Berlin",
        query="queer tech",
        count=10,
        start_date="2026-10-10T00:00:00+02:00",
        end_date="2026-10-11T00:00:00+02:00",
        proxy_url="http://proxy.invalid",
    )

    assert total == 1
    assert [event["title"] for event in events] == ["Queer Tech Community Night"]
    assert events[0]["date_start"] == "2026-10-10T19:30:00"


# contract-test: direct surface=rest_api assertions=events-search.providers.explicit,events-search.request.validated
@pytest.mark.anyio
async def test_siegessaeule_reconnects_after_blocked_proxy_exit(monkeypatch) -> None:
    sample_html = """
    <a href="/termine/kultur/queer-community/2026-10-10/19:30/">
      <h4>Queer Community Night</h4>
      <span>10. Oktober 2026, 19:30</span>
      <p>Community gathering</p>
      <span>Example Venue</span>
    </a>
    """
    clients_created = 0

    class FakeResponse:
        def __init__(self, *, status_code: int, text: str = "") -> None:
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                request = httpx.Request("GET", "https://www.siegessaeule.de/termine/")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("blocked", request=request, response=response)

        def json(self) -> dict[str, Any]:
            return {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal clients_created
            clients_created += 1
            self.attempt = clients_created

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(status_code=403)

        async def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
            if self.attempt == 1:
                return FakeResponse(status_code=403)
            return FakeResponse(status_code=200, text=sample_html)

    monkeypatch.setattr(siegessaeule.httpx, "AsyncClient", FakeClient)

    events, total = await siegessaeule.search_events_async(
        city="Berlin",
        query="queer community",
        count=10,
        start_date="2026-10-10T00:00:00+02:00",
        end_date="2026-10-11T00:00:00+02:00",
        proxy_url="http://proxy.invalid",
    )

    assert clients_created == 2
    assert total == 1
    assert [event["title"] for event in events] == ["Queer Community Night"]
