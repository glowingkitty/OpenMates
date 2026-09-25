"""Regression tests for app-skill result quality contracts.

These tests cover shared filtering and metadata behavior introduced by the
app-skill-processing-quality spec. They use pure helpers and fixed payloads so
provider API drift cannot make quality guardrails flaky.
"""

from __future__ import annotations

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.apps.events.skills.search_skill import SearchSkill  # noqa: E402


# contract-test: direct surface=rest_api assertions=events-search.request.validated,events-search.surface-parity
def test_event_quality_filter_excludes_physical_from_online_strict_results() -> None:
    events = [
        {"title": "Venue talk", "event_type": "PHYSICAL", "date_start": "2026-06-13T10:00:00+02:00"},
        {
            "title": "Eventbrite venue-only talk",
            "venue": {"name": "Flutgraben", "city": "Berlin"},
            "date_start": "2026-06-13T11:00:00+02:00",
        },
        {"title": "Luma webinar", "event_type": "online", "date_start": "2026-06-13T12:00:00+02:00"},
        {"title": "Meetup webinar", "event_type": "ONLINE", "date_start": "2026-06-13T13:00:00+02:00"},
    ]

    filtered, metadata = SearchSkill._apply_quality_filters(
        events,
        event_type="ONLINE",
        start_date=None,
        end_date=None,
        query="data engineering",
    )

    assert [event["title"] for event in filtered] == ["Luma webinar", "Meetup webinar"]
    assert all(event["event_type"] == "ONLINE" for event in filtered)
    assert metadata["filtered_out_count"] == 2
    assert metadata["applied_filters"] == ["event_type"]


# contract-test: direct surface=rest_api assertions=events-search.request.validated,events-search.surface-parity
def test_event_quality_filter_excludes_out_of_window_results() -> None:
    events = [
        {"title": "Friday pre-party", "event_type": "PHYSICAL", "date_start": "2026-06-12T22:00:00+02:00"},
        {"title": "Saturday meetup", "event_type": "PHYSICAL", "date_start": "2026-06-13T14:00:00+02:00"},
        {"title": "Saturday provider-local meetup", "event_type": "PHYSICAL", "date_start": "2026-06-14T14:00:00"},
        {"title": "Monday meetup", "event_type": "PHYSICAL", "date_start": "2026-06-15T10:00:00+02:00"},
    ]

    filtered, metadata = SearchSkill._apply_quality_filters(
        events,
        event_type="PHYSICAL",
        start_date="2026-06-13T00:00:00+02:00",
        end_date="2026-06-15T00:00:00+02:00",
        query="tech talks",
    )

    assert [event["title"] for event in filtered] == ["Saturday meetup", "Saturday provider-local meetup"]
    assert metadata["filtered_out_count"] == 2
    assert "date_window" in metadata["applied_filters"]


# contract-test: direct surface=rest_api assertions=events-search.relevance.bounded-candidates,events-search.results.actionable
def test_event_quality_filter_rejects_unparseable_dates_in_bounded_search() -> None:
    events = [
        {"title": "Provider display date", "date_start": "Sat 24 August 2024, 18:00"},
        {"title": "Missing start"},
        {"title": "In range", "date_start": "2026-10-10T19:00:00+02:00"},
    ]

    filtered, metadata = SearchSkill._apply_quality_filters(
        events,
        event_type=None,
        start_date="2026-10-01T00:00:00+02:00",
        end_date="2026-11-01T00:00:00+01:00",
        query="classical concert",
    )

    assert [event["title"] for event in filtered] == ["In range"]
    assert metadata["filtered_out_count"] == 2


# contract-test: direct surface=rest_api assertions=events-search.relevance.bounded-candidates
def test_event_semantic_deduplication_collapses_cross_provider_copies() -> None:
    events = [
        {
            "provider": "luma",
            "title": "Physical AI & Humanoid Robotics Workshop",
            "url": "https://lu.ma/physical-ai",
            "date_start": "2026-10-10T18:00:00+02:00",
        },
        {
            "provider": "meetup",
            "title": "Physical AI and Humanoid Robotics",
            "url": "https://meetup.com/events/123",
            "date_start": "2026-10-10T18:30:00+02:00",
        },
        {
            "provider": "eventbrite",
            "title": "PHYSICAL AI & HUMANOID ROBOTICS WORKSHOP",
            "url": "https://eventbrite.com/e/456",
            "date_start": "2026-10-10T18:00:00+02:00",
        },
        {
            "provider": "luma",
            "title": "AI Founder Night",
            "url": "https://lu.ma/founders",
            "date_start": "2026-10-10T18:00:00+02:00",
        },
    ]

    deduplicated = SearchSkill._deduplicate_events(events)

    assert [event["url"] for event in deduplicated] == [
        "https://lu.ma/physical-ai",
        "https://lu.ma/founders",
    ]


# contract-test: direct surface=rest_api assertions=events-search.results.actionable
def test_event_quality_filter_ranks_free_and_cheap_before_expensive() -> None:
    events = [
        {"title": "Expensive club", "event_type": "PHYSICAL", "fee": {"amount": "€38.47", "currency": "EUR"}},
        {"title": "Unknown price workshop", "event_type": "PHYSICAL"},
        {"title": "Free workshop", "event_type": "PHYSICAL", "fee": {"amount": "0.00", "currency": "EUR"}},
        {"title": "Cheap concert", "event_type": "PHYSICAL", "price": "€8"},
    ]

    filtered, metadata = SearchSkill._apply_quality_filters(
        events,
        event_type="PHYSICAL",
        start_date=None,
        end_date=None,
        query="free cheap music",
    )

    assert [event["title"] for event in filtered] == [
        "Free workshop",
        "Cheap concert",
        "Unknown price workshop",
        "Expensive club",
    ]
    assert metadata["price_intent"] == "free_or_cheap"
    assert filtered[0]["constraint_matches"]["price"] == "free"
    assert filtered[2]["constraint_matches"]["price"] == "unknown"


# contract-test: direct surface=rest_api assertions=events-search.results.actionable
def test_event_quality_filter_marks_accessibility_as_unknown_when_unproven() -> None:
    events = [
        {"title": "Family yoga", "event_type": "PHYSICAL", "description": "Kids welcome"},
        {"title": "Accessible museum day", "event_type": "PHYSICAL", "description": "Wheelchair accessible entrance."},
    ]

    filtered, metadata = SearchSkill._apply_quality_filters(
        events,
        event_type="PHYSICAL",
        start_date=None,
        end_date=None,
        query="wheelchair accessible family events",
    )

    by_title = {event["title"]: event for event in filtered}
    assert by_title["Family yoga"]["constraint_matches"]["accessibility"] == "unknown"
    assert by_title["Accessible museum day"]["constraint_matches"]["accessibility"] == "mentioned"
    assert metadata["accessibility_intent"] is True
