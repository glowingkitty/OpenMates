# backend/tests/test_pretalx_events_provider.py
#
# Tests for the pretalx/C3VOC conference schedule events provider.
#
# The provider fetches public conference schedule JSON and searches it locally.
# These tests use synthetic cached schedules so they are deterministic and do
# not depend on GPN or CCC endpoints being reachable during unit test runs.

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.apps.events.providers import pretalx

pytestmark = pytest.mark.anyio


BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
def clear_pretalx_cache() -> None:
    pretalx._SCHEDULE_CACHE.clear()


def _cache_schedule(conference: str) -> None:
    pretalx._SCHEDULE_CACHE[conference] = (
        999999999.0,
        [
            {
                "guid": "past-guid",
                "code": "PAST01",
                "date": "2026-06-04T10:00:00+02:00",
                "duration": "01:00",
                "room": "ZKM Kubus",
                "url": "https://example.test/past",
                "title": "Past privacy session",
                "track": "Politics, Society and Ethics",
                "type": "Talk",
                "language": "en",
                "abstract": "A privacy talk that already ended.",
                "description": "",
                "persons": [{"public_name": "Past Speaker"}],
            },
            {
                "guid": "future-guid",
                "code": "FUTURE01",
                "date": "2026-06-04T18:45:00+02:00",
                "duration": "01:00",
                "room": "ZKM Medientheater",
                "url": "https://example.test/future",
                "title": "Evaluating machine learning models",
                "track": "Science",
                "type": "Talk",
                "language": "en",
                "abstract": "An introduction to machine learning model evaluation.",
                "description": "",
                "persons": [{"public_name": "äN"}],
            },
        ],
    )


async def test_search_gpn_current_and_upcoming_excludes_past_by_default() -> None:
    _cache_schedule("gpn24")

    events, total = await pretalx.search_events_async(
        query="GPN24 machine learning privacy",
        conference="GPN24",
        now=datetime(2026, 6, 4, 12, 0, tzinfo=BERLIN),
    )

    assert total == 1
    assert events[0]["title"] == "Evaluating machine learning models"
    assert events[0]["conference"] == "gpn24"
    assert events[0]["provider"] == "gpn24"


async def test_search_gpn_past_events_includes_completed_sessions() -> None:
    _cache_schedule("gpn24")

    events, total = await pretalx.search_events_async(
        query="GPN24 privacy",
        conference="GPN24",
        past_events=True,
        now=datetime(2026, 6, 4, 12, 0, tzinfo=BERLIN),
    )

    assert total == 1
    assert events[0]["title"] == "Past privacy session"


async def test_search_chaos_congress_alias_resolves_to_39c3() -> None:
    _cache_schedule("39c3")

    events, total = await pretalx.search_events_async(
        query="Chaos Communication Congress machine learning",
        now=datetime(2025, 12, 27, 9, 0, tzinfo=BERLIN),
    )

    assert total == 1
    assert events[0]["conference"] == "39c3"
    assert events[0]["provider"] == "39c3"
    assert events[0]["location"].endswith("39C3, Hamburg, Germany")
