# backend/tests/live/test_google_calendar_permissions_live.py
#
# Live Google Calendar checks against a dedicated test account. Skipped unless
# OPENMATES_LIVE_GOOGLE_CALENDAR_REFRESH_TOKEN is set, so regular CI/local runs
# never contact Google. Never point this at a personal calendar: it creates and
# deletes events (all titled "OpenMates live test ..." and 30+ days ahead).
#
# Covers the provider behaviour the calendar skills rely on: refresh-token
# exchange, client-chosen event ids (idempotent retries), etag preconditions,
# all-day events, DST-crossing time zones, sendUpdates=none and delete
# idempotency.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.errors import GoogleCalendarProviderError
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token


pytestmark = pytest.mark.live


def _live_refresh_token() -> str | None:
    return os.getenv("OPENMATES_LIVE_GOOGLE_CALENDAR_REFRESH_TOKEN")


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _event_id() -> str:
    # Google event ids: base32hex characters (a-v, 0-9), 5-1024 long.
    return "omlive" + uuid.uuid4().hex


async def _client() -> tuple[GoogleCalendarClient, str]:
    refresh_token = _live_refresh_token()
    if not refresh_token:
        pytest.skip("OPENMATES_LIVE_GOOGLE_CALENDAR_REFRESH_TOKEN is not configured")
    calendar_id = os.getenv("OPENMATES_LIVE_GOOGLE_CALENDAR_ID", "primary")
    token = await exchange_google_refresh_token(
        refresh_token, {"app_id": "calendar", "action": "write", "calendar_id": calendar_id}
    )
    assert token.get("access_token"), "refresh-token exchange returned no access token"
    return GoogleCalendarClient(access_token=str(token["access_token"])), calendar_id


# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations
@pytest.mark.asyncio
async def test_live_google_calendar_full_roundtrip() -> None:
    client, calendar_id = await _client()
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=30)
    end = start + timedelta(minutes=30)
    event_id = _event_id()
    body = {
        "id": event_id,
        "summary": "OpenMates live test timed",
        "start": {"dateTime": _iso(start)},
        "end": {"dateTime": _iso(end)},
        "description": "Created by the OpenMates live Google Calendar test.",
    }
    created, replayed = await client.create_event(calendar_id=calendar_id, body=body, send_updates="none")
    try:
        assert created.id == event_id and not replayed and created.etag

        # Retry with the same client id returns the same event instead of a duplicate.
        again, replayed = await client.create_event(calendar_id=calendar_id, body=body, send_updates="none")
        assert again.id == event_id and replayed

        updated = await client.patch_event(
            calendar_id=calendar_id, event_id=event_id,
            body={"summary": "OpenMates live test timed updated"}, etag=created.etag,
        )
        assert updated.title == "OpenMates live test timed updated"
        assert updated.etag and updated.etag != created.etag

        # A stale etag is refused, so a concurrent edit is never overwritten.
        with pytest.raises(GoogleCalendarProviderError) as stale:
            await client.patch_event(
                calendar_id=calendar_id, event_id=event_id,
                body={"summary": "must not apply"}, etag=created.etag,
            )
        assert stale.value.code == "google_calendar_conflict"

        listed = await client.list_events(
            calendar_id=calendar_id, time_min=_iso(start - timedelta(minutes=5)),
            time_max=_iso(end + timedelta(minutes=5)),
        )
        assert any(event.id == event_id for event in listed["events"])
    finally:
        first = await client.delete_event(calendar_id=calendar_id, event_id=event_id, etag=None)
    assert first["status"] == "deleted"
    # Deleting again is reported, not an error (undo/retry safety).
    second = await client.delete_event(calendar_id=calendar_id, event_id=event_id, etag=None)
    assert second["status"] == "already_deleted"
    # The deleted id is never silently resurrected by a replayed create.
    with pytest.raises(GoogleCalendarProviderError):
        await client.create_event(calendar_id=calendar_id, body=body, send_updates="none")


# contract-test: supporting surface=rest_api assertions=calendar.events.time-and-recurrence
@pytest.mark.asyncio
async def test_live_google_calendar_all_day_and_dst() -> None:
    client, calendar_id = await _client()
    year = datetime.now(UTC).year + 1
    all_day_id, dst_id = _event_id(), _event_id()
    all_day, _ = await client.create_event(calendar_id=calendar_id, body={
        "id": all_day_id, "summary": "OpenMates live test all-day",
        "start": {"date": f"{year}-03-28"}, "end": {"date": f"{year}-03-29"},
    })
    # Europe/Berlin switches to summer time on the last Sunday of March; a
    # Saturday-to-Monday event crosses it and must keep its wall-clock times.
    last_sunday = max(day for day in range(25, 32) if datetime(year, 3, day).weekday() == 6)
    dst, _ = await client.create_event(calendar_id=calendar_id, body={
        "id": dst_id, "summary": "OpenMates live test DST",
        "start": {"dateTime": f"{year}-03-{last_sunday - 1:02d}T09:00:00", "timeZone": "Europe/Berlin"},
        "end": {"dateTime": f"{year}-03-{last_sunday + 1:02d}T09:00:00", "timeZone": "Europe/Berlin"},
    })
    try:
        assert all_day.all_day and all_day.start == f"{year}-03-28" and all_day.end == f"{year}-03-29"
        fetched = await client.get_event(calendar_id=calendar_id, event_id=dst_id)
        assert fetched.timezone == "Europe/Berlin"
        assert fetched.start.endswith("+01:00") and fetched.end.endswith("+02:00"), (fetched.start, fetched.end)
        assert fetched.start[11:16] == "09:00" and fetched.end[11:16] == "09:00"
    finally:
        await client.delete_event(calendar_id=calendar_id, event_id=all_day_id, etag=None)
        await client.delete_event(calendar_id=calendar_id, event_id=dst_id, etag=None)
