"""Events newsletter generator contract tests.

The generator is a pure, internal helper: it selects public OpenMates events,
resolves safe event destinations, and produces a deterministic campaign payload
that later admin-only services can preview, correct, schedule, or cancel without
addressing real subscribers.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.core.api.app.services.newsletter_campaign_service import NewsletterCampaignService
from backend.shared.python_utils.events_newsletter_generator import (
    build_events_campaign_payload,
    resolve_event_destination,
    select_events_for_newsletter,
)
from backend.shared.python_utils.openmates_event_registry import load_openmates_events


RUN_AT = datetime.fromisoformat("2026-08-20T09:00:00+02:00")


class FakeDirectus:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.created = 0
        self.updated = 0

    async def get_items(self, collection: str, params: dict, admin_required: bool) -> list[dict]:
        assert collection == "newsletter_campaigns"
        assert admin_required is True
        slug = params["filter"]["slug"]["_eq"]
        item = self.items.get(slug)
        return [item] if item else []

    async def create_item(self, collection: str, data: dict, admin_required: bool) -> tuple[bool, dict]:
        assert collection == "newsletter_campaigns"
        assert admin_required is True
        self.created += 1
        item = {**data, "id": f"campaign-{self.created}"}
        self.items[item["slug"]] = item
        return True, item

    async def update_item(self, collection: str, item_id: str, data: dict, admin_required: bool) -> dict:
        assert collection == "newsletter_campaigns"
        assert admin_required is True
        self.updated += 1
        for slug, item in self.items.items():
            if item["id"] == item_id:
                self.items[slug] = {**item, **data}
                return self.items[slug]
        raise AssertionError(f"unknown item id: {item_id}")


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window
def test_select_events_uses_next_four_weeks_and_explicit_status() -> None:
    registry_events = load_openmates_events()["events"]
    extra_events = [
        {**registry_events[0], "id": "past", "slug": "past", "starts_at": "2026-08-19T19:00:00+02:00"},
        {**registry_events[0], "id": "draft", "slug": "draft", "status": "draft"},
        {**registry_events[0], "id": "cancelled", "slug": "cancelled", "status": "cancelled"},
        {**registry_events[0], "id": "outside", "slug": "outside", "starts_at": "2026-09-17T09:00:00+02:00"},
    ]

    selected = select_events_for_newsletter([*registry_events, *extra_events], RUN_AT)

    assert [event["id"] for event in selected] == [event["id"] for event in registry_events]


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window
def test_campaign_payload_is_deterministic_for_same_cadence_window() -> None:
    selected = select_events_for_newsletter(load_openmates_events()["events"], RUN_AT)

    first = build_events_campaign_payload(selected, RUN_AT)
    second = build_events_campaign_payload(selected, RUN_AT)

    assert first == second
    assert first["slug"] == "openmates-events-2026-08-20"
    assert first["category"] == "openmates_events"
    assert first["metadata"]["event_ids"] == [event["id"] for event in selected]
    assert first["metadata"]["email_event_links"] == {
        event["id"]: f"#embed-id={event['id']}" for event in selected
    }
    assert len(first["metadata"]["payload_hash"]) == 64
    assert first["metadata"]["email_copy"]["en"]["closing_note"].startswith("Hope to see you")
    assert first["metadata"]["email_copy"]["de"]["intro"].endswith("kostenlose Webinare!")
    assert "openmates-community-hour-2026-08-25" in first["body_markdown"]["en"]
    assert "OpenMates Monthly Community Hour" in first["body_markdown"]["en"]
    assert "OpenMates Monatlicher Community Call" in first["body_markdown"]["de"]


@pytest.mark.parametrize(
    ("openmates_url", "is_live", "expected"),
    [
        ("https://openmates.org/events/community-hour", True, "https://openmates.org/events/community-hour"),
        ("https://openmates.org/events/community-hour", False, "https://luma.com/qfwdd70e"),
        (None, False, "https://luma.com/qfwdd70e"),
    ],
)
# contract-test: direct surface=cli assertions=newsletter.campaign.event-link-fallback
def test_event_destination_prefers_live_openmates_page_then_luma(
    openmates_url: str | None,
    is_live: bool,
    expected: str,
) -> None:
    event = {
        "openmates_url": openmates_url,
        "luma_url": "https://luma.com/qfwdd70e",
    }

    assert resolve_event_destination(event, is_openmates_url_live=lambda _: is_live) == expected


# contract-test: direct surface=cli assertions=newsletter.campaign.event-link-fallback
def test_event_destination_fails_without_usable_url() -> None:
    with pytest.raises(ValueError, match="No usable destination"):
        resolve_event_destination(
            {"openmates_url": "https://openmates.org/events/missing", "luma_url": ""},
            is_openmates_url_live=lambda _: False,
        )


# contract-test: direct surface=rest_api assertions=newsletter.campaign.deterministic-event-window
async def test_events_campaign_service_reuses_unchanged_cadence_campaign() -> None:
    directus = FakeDirectus()
    service = NewsletterCampaignService(directus)  # type: ignore[arg-type]

    first = await service.generate_events_campaign(admin_user_id="admin-1", run_at=RUN_AT)
    second = await service.generate_events_campaign(admin_user_id="admin-1", run_at=RUN_AT)

    assert first["campaign"]["slug"] == "openmates-events-2026-08-20"
    assert first["created"] is True
    assert second["reused"] is True
    assert second["campaign"]["id"] == first["campaign"]["id"]
    assert directus.created == 1
    assert directus.updated == 0
