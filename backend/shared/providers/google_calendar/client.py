# backend/shared/providers/google_calendar/client.py
#
# Pure async Google Calendar API wrapper.
# It accepts short-lived access tokens from the token broker and never handles
# refresh tokens, user account labels, or app-specific permission decisions.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .models import CalendarEvent

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
DEFAULT_TIMEOUT_SECONDS = 15.0


class GoogleCalendarClient:
    """Minimal Google Calendar API client for authorized event operations."""

    def __init__(self, *, access_token: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.timeout = timeout

    async def list_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """List events from a Google Calendar event feed."""

        url = f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{_path(calendar_id)}/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(max_results, 250)),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        return [_normalize_event(item) for item in payload.get("items", [])]

    async def create_event(
        self,
        *,
        calendar_id: str,
        title: str,
        start: str,
        end: str,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
    ) -> CalendarEvent:
        """Create an event in a Google Calendar."""

        url = f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{_path(calendar_id)}/events"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=_event_payload(
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=description,
                    attendees=attendees or [],
                ),
                headers=self._headers(),
            )
            response.raise_for_status()
            return _normalize_event(response.json())

    async def update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        title: str,
        start: str,
        end: str,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
    ) -> CalendarEvent:
        """Update an existing Google Calendar event."""

        url = f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{_path(calendar_id)}/events/{_path(event_id)}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                url,
                json=_event_payload(
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=description,
                    attendees=attendees or [],
                ),
                headers=self._headers(),
            )
            response.raise_for_status()
            return _normalize_event(response.json())

    async def delete_event(self, *, calendar_id: str, event_id: str) -> dict[str, str]:
        """Delete an event from a Google Calendar."""

        url = f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{_path(calendar_id)}/events/{_path(event_id)}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(url, headers=self._headers())
            response.raise_for_status()
        return {"status": "deleted", "event_id": event_id}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _normalize_event(item: dict[str, Any]) -> CalendarEvent:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    end = item.get("end") if isinstance(item.get("end"), dict) else {}
    return CalendarEvent(
        id=str(item.get("id", "")),
        title=str(item.get("summary", "")),
        start=start.get("dateTime") or start.get("date"),
        end=end.get("dateTime") or end.get("date"),
        location=item.get("location"),
        html_link=item.get("htmlLink"),
        etag=item.get("etag"),
    )


def _event_payload(
    *,
    title: str,
    start: str,
    end: str,
    location: str | None,
    description: str | None,
    attendees: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if location:
        payload["location"] = location
    if description:
        payload["description"] = description
    if attendees:
        payload["attendees"] = [{"email": email} for email in attendees]
    return payload


def _path(value: str) -> str:
    return quote(value, safe="")
