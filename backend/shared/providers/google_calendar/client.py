# backend/shared/providers/google_calendar/client.py
#
# Pure async Google Calendar API wrapper.
# It accepts short-lived access tokens from the token broker and never handles
# refresh tokens, user account labels, or app-specific permission decisions.
# Every failure is raised as a classified GoogleCalendarProviderError.
#
# API reference: https://developers.google.com/calendar/api/v3/reference
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .errors import GoogleCalendarProviderError, classify_status_error
from .models import CalendarEvent

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_EVENTS_PAGE_SIZE = 250


class GoogleCalendarClient:
    """Minimal Google Calendar API client for authorized calendar operations."""

    def __init__(
        self,
        *,
        access_token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.timeout = timeout
        self._transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        mutation: bool = False,
    ) -> httpx.Response:
        request_headers = {"Authorization": f"Bearer {self.access_token}", **(headers or {})}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.request(
                    method, f"{GOOGLE_CALENDAR_API_BASE_URL}{path}",
                    params=params, json=json, headers=request_headers,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The request never reached Google, so nothing changed.
            raise GoogleCalendarProviderError("google_calendar_unavailable") from exc
        except httpx.TransportError as exc:
            # A write may have been applied before the connection failed.
            code = "google_calendar_outcome_uncertain" if mutation else "google_calendar_unavailable"
            raise GoogleCalendarProviderError(code) from exc
        if response.is_error:
            error = classify_status_error(response)
            logger.info("Google Calendar %s %s failed: %s", method, path.split("/")[1], error.code)
            raise error
        return response

    async def list_calendars(
        self, *, page_token: str | None = None, show_hidden: bool = False,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Return one calendar-list page without discarding its continuation."""
        params: dict[str, Any] = {
            "maxResults": max(1, min(max_results, 250)),
            "showHidden": str(show_hidden).lower(),
        }
        if page_token:
            params["pageToken"] = page_token
        payload = (await self._request("GET", "/users/me/calendarList", params=params)).json()
        return {
            "calendars": [{
                "id": item["id"],
                "name": item.get("summaryOverride") or item.get("summary", ""),
                "timezone": item.get("timeZone"),
                "access_role": item.get("accessRole"),
                "primary": bool(item.get("primary", False)),
                "hidden": bool(item.get("hidden", False)),
            } for item in payload.get("items", [])],
            "next_page_token": payload.get("nextPageToken"),
        }

    async def list_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int = 50,
        page_token: str | None = None,
        query: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        """List one page of expanded events in a bounded interval."""

        params: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(max_results, MAX_EVENTS_PAGE_SIZE)),
        }
        if page_token:
            params["pageToken"] = page_token
        if query:
            params["q"] = query
        if time_zone:
            params["timeZone"] = time_zone
        payload = (await self._request("GET", f"/calendars/{_path(calendar_id)}/events", params=params)).json()
        return {
            "events": [normalize_event(item) for item in payload.get("items", [])],
            "next_page_token": payload.get("nextPageToken"),
            "calendar_timezone": payload.get("timeZone"),
        }

    async def get_event_raw(self, *, calendar_id: str, event_id: str) -> dict[str, Any]:
        """Raw provider event, used as the base for partial updates."""

        path = f"/calendars/{_path(calendar_id)}/events/{_path(event_id)}"
        return (await self._request("GET", path)).json()

    async def get_event(self, *, calendar_id: str, event_id: str) -> CalendarEvent:
        return normalize_event(await self.get_event_raw(calendar_id=calendar_id, event_id=event_id))

    async def create_event(
        self, *, calendar_id: str, body: dict[str, Any], send_updates: str = "none",
    ) -> tuple[CalendarEvent, bool]:
        """Insert an event. Returns (event, already_existed).

        When ``body`` carries a client-chosen ``id`` a 409 means an earlier
        attempt of the same operation already created it; that event is returned.
        """

        path = f"/calendars/{_path(calendar_id)}/events"
        try:
            response = await self._request(
                "POST", path, params={"sendUpdates": send_updates}, json=body, mutation=True,
            )
        except GoogleCalendarProviderError as error:
            if error.code != "google_calendar_duplicate" or not body.get("id"):
                raise
            existing = await self.get_event(calendar_id=calendar_id, event_id=str(body["id"]))
            if existing.status == "cancelled":
                # Same operation key but deleted since: never resurrect silently.
                raise
            return existing, True
        return normalize_event(response.json()), False

    async def patch_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        etag: str | None,
        send_updates: str = "none",
    ) -> CalendarEvent:
        """Partially update an event, refusing if it changed since ``etag``."""

        path = f"/calendars/{_path(calendar_id)}/events/{_path(event_id)}"
        headers = {"If-Match": etag} if etag else None
        response = await self._request(
            "PATCH", path, params={"sendUpdates": send_updates}, json=body,
            headers=headers, mutation=True,
        )
        return normalize_event(response.json())

    async def delete_event(
        self, *, calendar_id: str, event_id: str, etag: str | None, send_updates: str = "none",
    ) -> dict[str, str]:
        """Delete an event. A 410 means it was already deleted."""

        path = f"/calendars/{_path(calendar_id)}/events/{_path(event_id)}"
        headers = {"If-Match": etag} if etag else None
        try:
            await self._request(
                "DELETE", path, params={"sendUpdates": send_updates}, headers=headers, mutation=True,
            )
        except GoogleCalendarProviderError as error:
            if error.code == "google_calendar_gone":
                return {"status": "already_deleted", "event_id": event_id}
            raise
        return {"status": "deleted", "event_id": event_id}


def normalize_event(item: dict[str, Any]) -> CalendarEvent:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    end = item.get("end") if isinstance(item.get("end"), dict) else {}
    return CalendarEvent(
        id=str(item.get("id", "")),
        title=str(item.get("summary", "")),
        start=start.get("dateTime") or start.get("date"),
        end=end.get("dateTime") or end.get("date"),
        all_day=bool(start.get("date") and not start.get("dateTime")),
        timezone=start.get("timeZone"),
        status=item.get("status"),
        location=item.get("location"),
        description=item.get("description"),
        attendees=[str(attendee.get("email")) for attendee in item.get("attendees", []) if attendee.get("email")],
        recurring_event_id=item.get("recurringEventId"),
        recurrence=list(item.get("recurrence") or []),
        html_link=item.get("htmlLink"),
        etag=item.get("etag"),
    )


def _path(value: str) -> str:
    return quote(value, safe="")
