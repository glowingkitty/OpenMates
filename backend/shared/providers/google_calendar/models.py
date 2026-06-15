# backend/shared/providers/google_calendar/models.py
#
# Pydantic models for normalized Google Calendar provider requests and results.
# These schemas intentionally use provider-neutral field names where possible so
# Calendar skills can render events without exposing provider internals to LLMs.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from pydantic import BaseModel, Field


class CalendarEventsRequest(BaseModel):
    """Request to list events from a connected Google Calendar."""

    calendar_id: str = Field(default="primary")
    time_min: str
    time_max: str
    access_token_handle: str


class CalendarEventMutationRequest(BaseModel):
    """Request to create or update a connected Google Calendar event."""

    calendar_id: str = Field(default="primary")
    access_token_handle: str
    title: str
    start: str
    end: str
    event_id: str | None = None
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)


class CalendarEventDeleteRequest(BaseModel):
    """Request to delete a connected Google Calendar event."""

    calendar_id: str = Field(default="primary")
    event_id: str
    access_token_handle: str


class CalendarEvent(BaseModel):
    """Normalized Calendar event result."""

    id: str
    title: str = ""
    start: str | None = None
    end: str | None = None
    location: str | None = None
    html_link: str | None = None
    etag: str | None = None
