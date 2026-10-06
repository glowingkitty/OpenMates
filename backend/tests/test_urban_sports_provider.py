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
