"""OpenMates events newsletter registry contract tests.

These tests pin the shared YAML registry that drives the internal events
newsletter automation. The registry is operational plaintext public event data,
not subscriber data, and must stay deterministic so campaign generation can be
reviewed, corrected, and replayed safely.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from backend.shared.python_utils.openmates_event_registry import load_openmates_events

REPO_ROOT = Path(__file__).resolve().parents[2]


EXPECTED_EVENT_IDS = {
    "openmates-community-hour-2026-09-29",
    "openmates-community-hour-2026-10-27",
    "openmates-berlin-meetup-2026-09-26",
    "everyday-workflows-webinar-2026-09-30",
    "openmates-teams-webinar-2026-10-14",
    "spec-driven-development-webinar-2026-10-28",
    "cli-sdk-webinar-2026-11-11",
    "self-hosting-webinar-2026-11-25",
}


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window
def test_openmates_events_registry_contains_scheduled_events() -> None:
    registry = load_openmates_events()

    assert registry["schema_version"] == 1
    events = registry["events"]
    assert {event["id"] for event in events} == EXPECTED_EVENT_IDS
    assert len(events) == 8
    assert all("social" not in event for event in events)
    assert all("recording" not in event for event in events)
    assert all("preparation" not in event for event in events)


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window
def test_openmates_events_registry_schema_is_complete_and_safe() -> None:
    registry = load_openmates_events()
    events = registry["events"]
    seen_slugs: set[str] = set()

    for language in ("en", "de"):
        header = registry["campaign"]["assets"]["header"][language]
        header_path = Path(header["path"])
        mobile_header_path = Path(header["mobile_path"])
        assert header_path.suffix == ".png"
        assert mobile_header_path.suffix == ".png"
        assert (REPO_ROOT / header_path).exists()
        assert (REPO_ROOT / mobile_header_path).exists()
        assert header["alt"]

    for event in events:
        assert event["id"] == event["slug"]
        assert event["slug"] not in seen_slugs
        seen_slugs.add(event["slug"])
        assert event["status"] in {"published", "cancelled"}
        assert event["timezone"] == "Europe/Berlin"

        starts_at = datetime.fromisoformat(event["starts_at"])
        ends_at = datetime.fromisoformat(event["ends_at"])
        assert starts_at.tzinfo is not None
        assert ends_at.tzinfo is not None
        assert ends_at > starts_at

        luma = urlparse(event["luma_url"])
        assert (luma.scheme, luma.netloc) == ("https", "luma.com")

        content = event["localized_content"]
        assert set(content) == {"en", "de"}
        for localized in content.values():
            assert localized["title"]
            assert localized["summary"]
            assert localized["description"]

        for language in ("en", "de"):
            asset = event["assets"]["card"][language]
            asset_path = Path(asset["path"])
            assert not asset_path.is_absolute()
            assert ".." not in asset_path.parts
            assert asset_path.parts[:3] == ("shared", "events", "assets")
            assert asset_path.suffix == ".png"
            assert (REPO_ROOT / asset_path).exists()
            assert asset["alt"]


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window
def test_published_events_are_online_with_october_community_hour() -> None:
    events = load_openmates_events()["events"]
    published = [event for event in events if event["status"] == "published"]
    assert len(published) == 7
    assert all(event["event_type"] != "in_person_meetup" for event in published)
    assert all(event["online_url"] == "https://meet.openmates.org" for event in published)

    october = next(event for event in published if event["id"] == "openmates-community-hour-2026-10-27")
    start = datetime.fromisoformat(october["starts_at"])
    end = datetime.fromisoformat(october["ends_at"])
    berlin_start = start.astimezone(ZoneInfo("Europe/Berlin"))
    assert berlin_start.isoformat() == "2026-10-27T19:00:00+01:00"
    assert berlin_start.weekday() == 1
    assert (end - start).total_seconds() == 3600

    meetup = next(event for event in events if event["id"] == "openmates-berlin-meetup-2026-09-26")
    assert meetup["status"] == "cancelled"
