# backend/tests/test_urban_sports_provider.py
#
# Deterministic parser and filtering tests for the Urban Sports public-web
# provider. The production client uses logged-out Urban Sports Club pages, but
# these tests intentionally use tiny fixtures so CI never depends on provider
# availability or live search ranking changes.

from __future__ import annotations

from pathlib import Path

from backend.shared.providers.urban_sports.parsers import (
    dedupe_classes,
    filter_by_plan,
    haversine_km,
    parse_activity_cards,
    parse_venue_cards,
    parse_venue_detail,
)


FIXTURES = Path(__file__).parent / "fixtures" / "urban_sports"
SORAUER_STR_12 = (52.4982926, 13.4376695)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


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


def test_distance_filtering_keeps_nearby_beat81() -> None:
    detail = parse_venue_detail(
        _fixture("venue_detail_beat81.html"),
        url="https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer",
    )
    distance = haversine_km(SORAUER_STR_12[0], SORAUER_STR_12[1], detail.lat, detail.lon)

    assert round(distance, 3) == 0.714
    assert distance <= 1.0


def test_parses_activity_cards_and_deduplicates_by_appointment_and_date() -> None:
    classes = parse_activity_cards(_fixture("activities.html"), date="2026-07-07")

    assert len(classes) == 3
    deduped = dedupe_classes(classes)
    assert [item.appointment_id for item in deduped] == ["appt-beat81", "appt-yoga"]
    assert deduped[0].name == "HIIT Strength"
    assert deduped[0].spots_left == 8
    assert deduped[0].attendance_mode == "onsite"


def test_plan_filter_includes_beat81_by_default_but_excludes_for_essential() -> None:
    classes = dedupe_classes(parse_activity_cards(_fixture("activities.html"), date="2026-07-07"))

    assert [item.name for item in filter_by_plan(classes, None)] == ["HIIT Strength", "Morning Yoga"]
    assert [item.name for item in filter_by_plan(classes, "essential")] == ["Morning Yoga"]
    assert [item.name for item in filter_by_plan(classes, "classic")] == ["HIIT Strength", "Morning Yoga"]
