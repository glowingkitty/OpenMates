# contract-test-file: infrastructure
# backend/tests/fake_google_calendar.py
#
# Stateful in-memory stand-in for the Google Calendar v3 REST API, served via
# httpx.MockTransport. It implements the request/response contract the
# OpenMates client relies on (calendarList, events list/insert/get/patch/
# delete, pagination, client-chosen ids, If-Match etags, 410 for deleted
# events, sendUpdates) so skill tests exercise real HTTP handling, not fakes
# of the client. Synthetic data only.
#
# Reference: https://developers.google.com/calendar/api/v3/reference/events

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import httpx

BASE_PATH = "/calendar/v3"


@dataclass
class FakeGoogleCalendar:
    access_token: str = "synthetic-access-token"
    calendars: list[dict[str, Any]] = field(default_factory=lambda: [
        {"id": "primary-synthetic@example.org", "summary": "Synthetic primary", "timeZone": "Europe/Berlin",
         "accessRole": "owner", "primary": True},
        {"id": "team-synthetic@example.org", "summary": "Synthetic team", "timeZone": "UTC",
         "accessRole": "writer"},
        {"id": "holidays-synthetic@example.org", "summary": "Synthetic holidays", "timeZone": "UTC",
         "accessRole": "reader"},
    ])
    events: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    granted_scopes: set[str] = field(default_factory=lambda: {"events", "calendarlist"})
    page_size: int = 2
    requests: list[httpx.Request] = field(default_factory=list)
    fail_next: list[httpx.Response | Exception] = field(default_factory=list)
    _counter: int = 0

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client_factory(self):
        from backend.shared.providers.google_calendar.client import GoogleCalendarClient

        def build(*, access_token: str) -> GoogleCalendarClient:
            return GoogleCalendarClient(access_token=access_token, transport=self.transport)

        return build

    def add_event(self, calendar_id: str, event_id: str, **fields: Any) -> dict[str, Any]:
        self._counter += 1
        event = {"id": event_id, "status": "confirmed", "etag": f'"etag-{self._counter}"', **fields}
        self.events[(calendar_id, event_id)] = event
        return event

    # ------------------------------------------------------------------ http
    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            failure = self.fail_next.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        if request.headers.get("authorization") != f"Bearer {self.access_token}":
            return _error(401, "authError", "Invalid Credentials")
        path = request.url.path.removeprefix(BASE_PATH)
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if parts[:3] == ["users", "me", "calendarList"]:
            return self._calendar_list(request)
        if parts[0] != "calendars" or len(parts) < 3 or parts[2] != "events":
            return _error(404, "notFound", "Not Found")
        calendar_id = parts[1]
        calendar = next((item for item in self.calendars if item["id"] == calendar_id), None)
        if calendar is None:
            return _error(404, "notFound", "Not Found")
        if len(parts) == 3 and request.method == "GET":
            return self._list(request, calendar_id)
        writable = calendar["accessRole"] in {"owner", "writer"}
        if request.method != "GET" and "events" not in self.granted_scopes:
            return _error(403, "insufficientPermissions", "Insufficient Permission")
        if request.method != "GET" and not writable:
            return _error(403, "requiredAccessLevel", "You need to have writer access to this calendar.")
        if len(parts) == 3 and request.method == "POST":
            return self._insert(request, calendar_id)
        event_id = parts[3]
        event = self.events.get((calendar_id, event_id))
        if request.method == "GET":
            return httpx.Response(200, json=event) if event else _error(404, "notFound", "Not Found")
        if event is None:
            return _error(404, "notFound", "Not Found")
        if event["status"] == "cancelled":
            return _error(410, "deleted", "Resource has been deleted")
        if_match = request.headers.get("if-match")
        if if_match and if_match != event["etag"]:
            return _error(412, "conditionNotMet", "Precondition Failed")
        if request.method == "PATCH":
            event.update(json.loads(request.content))
            self._counter += 1
            event["etag"] = f'"etag-{self._counter}"'
            return httpx.Response(200, json=event)
        if request.method == "DELETE":
            event["status"] = "cancelled"
            return httpx.Response(204)
        return _error(405, "methodNotAllowed", "Method Not Allowed")

    def _calendar_list(self, request: httpx.Request) -> httpx.Response:
        if not self.granted_scopes & {"calendarlist", "readonly"}:
            return _error(403, "insufficientPermissions", "Insufficient Permission")
        return httpx.Response(200, json={"items": self.calendars})

    def _list(self, request: httpx.Request, calendar_id: str) -> httpx.Response:
        params = request.url.params
        assert params["singleEvents"] == "true" and params["orderBy"] == "startTime"
        time_min, time_max = params["timeMin"], params["timeMax"]
        query = (params.get("q") or "").lower()
        items = [
            event for (cal, _), event in sorted(self.events.items(), key=lambda kv: _start(kv[1]))
            if cal == calendar_id and event["status"] != "cancelled"
            and time_min <= _start(event) < time_max
            and (not query or query in json.dumps(event).lower())
        ]
        offset = int(params.get("pageToken") or 0)
        size = min(int(params["maxResults"]), self.page_size)
        page = items[offset:offset + size]
        payload: dict[str, Any] = {"items": page, "timeZone": "UTC"}
        if offset + size < len(items):
            payload["nextPageToken"] = str(offset + size)
        return httpx.Response(200, json=payload)

    def _insert(self, request: httpx.Request, calendar_id: str) -> httpx.Response:
        body = json.loads(request.content)
        event_id = body.get("id")
        if event_id and (calendar_id, event_id) in self.events:
            return _error(409, "duplicate", "The requested identifier already exists.")
        if not event_id:
            self._counter += 1
            event_id = f"generated{self._counter}"
        created = self.add_event(calendar_id, event_id, **{k: v for k, v in body.items() if k != "id"})
        created["htmlLink"] = f"https://calendar.example.org/event/{event_id}"
        return httpx.Response(200, json=created)


def _start(event: dict[str, Any]) -> str:
    start = event.get("start") or {}
    return str(start.get("dateTime") or start.get("date") or "")


def _error(status: int, reason: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {
        "code": status, "message": message, "errors": [{"reason": reason, "message": message}],
    }})
