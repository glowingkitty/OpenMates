# backend/tests/live/test_google_calendar_permissions_live.py
#
# Live Google Calendar permission test scaffold.
# This test is skipped unless explicit live credentials are present, so regular
# CI/local contract runs do not contact Google or require user secrets.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token


pytestmark = pytest.mark.live


def _live_refresh_token() -> str | None:
    return os.getenv("OPENMATES_LIVE_GOOGLE_CALENDAR_REFRESH_TOKEN")


@pytest.mark.asyncio
async def test_live_google_calendar_read_create_update_delete_roundtrip() -> None:
    refresh_token = _live_refresh_token()
    if not refresh_token:
        pytest.skip("OPENMATES_LIVE_GOOGLE_CALENDAR_REFRESH_TOKEN is not configured")

    calendar_id = os.getenv("OPENMATES_LIVE_GOOGLE_CALENDAR_ID", "primary")
    token_response = await exchange_google_refresh_token(
        refresh_token,
        {"app_id": "calendar", "action": "write", "calendar_id": calendar_id},
    )
    access_token = token_response.get("access_token")
    if not access_token:
        pytest.skip("Google token exchange did not return an access token")

    client = GoogleCalendarClient(access_token=str(access_token))
    start = datetime.now(UTC) + timedelta(days=30)
    end = start + timedelta(minutes=30)
    created = await client.create_event(
        calendar_id=calendar_id,
        title="OpenMates live permission test",
        start=start.isoformat().replace("+00:00", "Z"),
        end=end.isoformat().replace("+00:00", "Z"),
        description="Created by OpenMates live Google Calendar permission test.",
    )
    try:
        assert created.id
        updated = await client.update_event(
            calendar_id=calendar_id,
            event_id=created.id,
            title="OpenMates live permission test updated",
            start=start.isoformat().replace("+00:00", "Z"),
            end=end.isoformat().replace("+00:00", "Z"),
        )
        assert updated.title == "OpenMates live permission test updated"
        events = await client.list_events(
            calendar_id=calendar_id,
            time_min=(start - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            time_max=(end + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        )
        assert any(event.id == created.id for event in events)
    finally:
        if created.id:
            await client.delete_event(calendar_id=calendar_id, event_id=created.id)
