# backend/tests/test_urban_sports_provider.py
#
# Deterministic parser and filtering tests for the Urban Sports public-web
# provider. The production client uses logged-out Urban Sports Club pages, but
# these tests intentionally use tiny fixtures so CI never depends on provider
# availability or live search ranking changes.

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.shared.providers.urban_sports.client import UrbanSportsClient

from backend.shared.providers.urban_sports.parsers import (
    dedupe_classes,
    filter_by_plan,
    haversine_km,
    matches_query,
    parse_activity_categories,
    parse_activity_cards,
    parse_venue_cards,
    parse_venue_detail,
)


FIXTURES = Path(__file__).parent / "fixtures" / "urban_sports"
SORAUER_STR_12 = (52.4982926, 13.4376695)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_parses_venue_cards_and_detail_json_ld() -> None:
    venues = parse_venue_cards(_fixture("venues.html"))
    assert [venue.name for venue in venues] == ["BEAT81 - Paul-Lincke-Ufer", "Essential Yoga"]
    assert venues[0].plans_required == ["Classic", "Premium", "Max"]
    assert venues[0].url == "https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer"

    detail = parse_venue_detail(_fixture("venue_detail_beat81.html"), url=venues[0].url)
    assert detail.postal_code == "10999"
    assert detail.lat == 52.493788701
    assert detail.lon == 13.430159621
    assert detail.rating == 4.8
    assert detail.rating_count == 123


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_distance_filtering_keeps_nearby_beat81() -> None:
    detail = parse_venue_detail(
        _fixture("venue_detail_beat81.html"),
        url="https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer",
    )
    distance = haversine_km(SORAUER_STR_12[0], SORAUER_STR_12[1], detail.lat, detail.lon)

    assert round(distance, 3) == 0.714
    assert distance <= 1.0


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_parses_activity_cards_and_deduplicates_by_appointment_and_date() -> None:
    classes = parse_activity_cards(_fixture("activities.html"), date="2026-07-07")

    assert len(classes) == 3
    deduped = dedupe_classes(classes)
    assert [item.appointment_id for item in deduped] == ["appt-beat81", "appt-yoga"]
    assert deduped[0].name == "HIIT Strength"
    assert deduped[0].spots_left == 8
    assert deduped[0].attendance_mode == "onsite"


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_plan_filter_includes_beat81_by_default_but_excludes_for_essential() -> None:
    classes = dedupe_classes(parse_activity_cards(_fixture("activities.html"), date="2026-07-07"))

    assert [item.name for item in filter_by_plan(classes, None)] == ["HIIT Strength", "Morning Yoga"]
    assert [item.name for item in filter_by_plan(classes, "essential")] == ["Morning Yoga"]
    assert [item.name for item in filter_by_plan(classes, "classic")] == ["HIIT Strength", "Morning Yoga"]


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_query_matches_alternatives_across_class_name_and_category() -> None:
    item = {"name": "Contemporary Basics", "category": "Dance", "venue_name": "Movement Studio"}
    assert matches_query(item, "Techno Tanz, moderner Tanz, Contemporary Dance")
    assert not matches_query(item, "Yoga, Pilates")
    assert matches_query(item, "Contemporary")
    assert not matches_query(item, "Contemporary Advanced")


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
def test_activity_category_selector_uses_provider_ids() -> None:
    html = '<select id="category"><option value=""></option><option value="40005">Dance</option><option value="40002">Yoga</option></select>'
    assert parse_activity_categories(html) == {"dance": "40005", "yoga": "40002"}


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_named_category_resolves_once_and_preserves_date_and_plan(monkeypatch) -> None:
    client = UrbanSportsClient()
    urls = []

    async def fetch(url):
        urls.append(url)
        return '<select id="category"><option value="40005">Dance</option></select>'

    monkeypatch.setattr(client, "_fetch_url", fetch)
    for date in ("2026-10-06", "2026-10-07"):
        await client._fetch_search_page("activities", city_id="1", date=date, category="dance", plan="classic", attendance_mode="onsite")
    assert len(urls) == 3
    assert "category" not in parse_qs(urlparse(urls[0]).query)
    for url, date in zip(urls[1:], ("2026-10-06", "2026-10-07")):
        params = parse_qs(urlparse(url).query)
        assert params["category"] == ["40005"]
        assert params["date"] == [date]
        assert params["plan_type"] == ["2"]
        assert params["type[]"] == ["onsite"]


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_unknown_category_is_visible_instead_of_empty_results(monkeypatch) -> None:
    client = UrbanSportsClient()

    async def fetch(url):
        return '<select id="category"><option value="40005">Dance</option></select>'

    monkeypatch.setattr(client, "_fetch_url", fetch)
    with pytest.raises(ValueError, match="Unknown Urban Sports activity category"):
        await client._fetch_search_page("activities", category="invented activity")


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
async def test_multiday_search_overlaps_dates_and_venues_without_truncating_before_filter(monkeypatch):
    import asyncio

    client = UrbanSportsClient()
    dates = []
    venues = []
    all_dates = asyncio.Event()
    all_venues = asyncio.Event()

    async def fetch(url):
        if '/activities?' in url:
            dates.append(parse_qs(urlparse(url).query)['date'][0])
            if len(dates) == 3:
                all_dates.set()
            await all_dates.wait()
            return _fixture('activities.html')
        venues.append(url)
        if len(venues) == 2:
            all_venues.set()
        await all_venues.wait()
        return _fixture('venue_detail_beat81.html' if 'beat81' in url else 'venue_detail_yoga.html')

    monkeypatch.setattr(client, '_fetch_url', fetch)
    results = await asyncio.wait_for(client.search_classes(
        start_date='2026-10-20', days=3, lat=SORAUER_STR_12[0], lon=SORAUER_STR_12[1],
        radius_km=.1, attendance_mode='onsite', min_spots=1, limit=3,
    ), timeout=2)
    # Even though fixtures repeat appointment IDs, each date is retained.
    assert [item['date'] for item in results] == ['2026-10-20', '2026-10-21', '2026-10-22']
    assert all(item['id'] == 'appt-yoga' and item['distance_km'] < .1 for item in results)
    assert len(venues) == 2


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
async def test_http_work_is_bounded_and_cancellation_drains_requests(monkeypatch):
    import asyncio
    from backend.shared.providers.urban_sports import client as module

    active = 0
    peak = 0
    saturated = asyncio.Event()

    class FakeHttpClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            if active == module.MAX_CONCURRENT_REQUESTS:
                saturated.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

    monkeypatch.setattr(module.httpx, 'AsyncClient', FakeHttpClient)
    client = UrbanSportsClient()
    work = asyncio.create_task(module._gather_owned(*(client._fetch_url(str(i)) for i in range(20))))
    await asyncio.wait_for(saturated.wait(), 2)
    assert peak == module.MAX_CONCURRENT_REQUESTS
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert active == 0


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['venue', 'category'])
async def test_shared_load_survives_one_cancel_and_is_retryable_after_failure(monkeypatch, kind):
    import asyncio

    client = UrbanSportsClient()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    fail = True

    async def fetch(url):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        if fail:
            raise RuntimeError('temporary provider failure')
        return (_fixture('venue_detail_beat81.html') if kind == 'venue' else
                '<select id="category"><option value="40005">Dance</option></select>')

    monkeypatch.setattr(client, '_fetch_url', fetch)

    async def load():
        if kind == 'venue':
            return await client._get_venue_detail('https://urbansportsclub.com/en/venues/beat81')
        return await client._fetch_search_page('activities', category='dance')

    first = asyncio.create_task(load())
    second = asyncio.create_task(load())
    await asyncio.wait_for(started.wait(), 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    release.set()
    with pytest.raises(RuntimeError, match='temporary'):
        await second
    assert calls == 1
    assert not client._venue_loads and not client._category_loads
    fail = False
    await load()
    assert calls == (2 if kind == 'venue' else 3)


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['venue', 'category'])
async def test_last_consumer_cancels_shared_load_and_can_retry(monkeypatch, kind):
    import asyncio

    client = UrbanSportsClient()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch(url):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(client, '_fetch_url', fetch)

    async def load():
        if kind == 'venue':
            return await client._get_venue_detail('https://urbansportsclub.com/en/venues/beat81')
        return await client._fetch_search_page('activities', category='dance')

    work = asyncio.create_task(load())
    await asyncio.wait_for(started.wait(), 2)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert cancelled.is_set()
    assert not client._venue_loads and not client._category_loads
    assert not client._venue_detail_cache and not client._category_id_cache

    async def success(url):
        return (_fixture('venue_detail_beat81.html') if kind == 'venue' else
                '<select id="category"><option value="40005">Dance</option></select>')

    monkeypatch.setattr(client, '_fetch_url', success)
    assert await load()


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
async def test_concurrent_dates_share_named_category_discovery(monkeypatch):
    import asyncio

    client = UrbanSportsClient()
    discovery_calls = 0
    category_calls = []

    async def fetch(url):
        nonlocal discovery_calls
        params = parse_qs(urlparse(url).query)
        if 'category' not in params:
            discovery_calls += 1
            await asyncio.sleep(0)
        else:
            category_calls.append(params)
        return '<select id="category"><option value="40005">Dance</option></select>'

    monkeypatch.setattr(client, '_fetch_url', fetch)
    await asyncio.gather(*(client._fetch_search_page('activities', date=date, category='dance')
                           for date in ['2026-10-20', '2026-10-21', '2026-10-22']))
    assert discovery_calls == 1
    assert [params['date'][0] for params in category_calls] == ['2026-10-20', '2026-10-21', '2026-10-22']


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['dates', 'venues'])
async def test_search_cancellation_drains_date_and_shared_venue_work(monkeypatch, phase):
    import asyncio

    client = UrbanSportsClient()
    active = 0
    started = asyncio.Event()

    async def fetch(url):
        nonlocal active
        if phase == 'venues' and '/activities?' in url:
            return _fixture('activities.html')
        active += 1
        if active == (3 if phase == 'dates' else 2):
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    monkeypatch.setattr(client, '_fetch_url', fetch)
    search = asyncio.create_task(client.search_classes(start_date='2026-10-20', days=3))
    await asyncio.wait_for(started.wait(), 2)
    search.cancel()
    with pytest.raises(asyncio.CancelledError):
        await search
    assert active == 0
    assert not client._venue_loads
