# backend/shared/providers/google_calendar/models.py
#
# Pydantic models for normalized Google Calendar provider requests and results.
# These schemas intentionally use provider-neutral field names where possible so
# Calendar skills can render events without exposing provider internals to LLMs.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

SEND_UPDATES_PATTERN = "^(none|all|externalOnly)$"


class CalendarEventsRequest(BaseModel):
    """Request to list events from a connected Google Calendar."""

    calendar_id: str = Field(default="primary", min_length=1)
    time_min: str = Field(min_length=1)
    time_max: str = Field(min_length=1)
    access_token_handle: str
    connected_account_id: str | None = None
    page_token: str | None = Field(default=None, max_length=4096)
    max_results: int = Field(default=50, ge=1, le=250)
    query: str | None = Field(default=None, max_length=512)
    timezone: str | None = None


class CalendarEventMutationRequest(BaseModel):
    """Request to create or update a connected Google Calendar event.

    For updates every field except calendar_id/event_id is optional and omitted
    fields stay unchanged. location/description set to "" clear the value.
    """

    model_config = ConfigDict(extra="ignore")

    calendar_id: str = Field(min_length=1)
    access_token_handle: str
    connected_account_id: str | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    timezone: str | None = None
    event_id: str | None = None
    location: str | None = None
    description: str | None = None
    attendees: list[str] | None = None
    reminder_minutes: list[int] | None = None
    send_updates: str | None = Field(default=None, pattern=SEND_UPDATES_PATTERN)
    expected_etag: str | None = None


class CalendarEventDeleteRequest(BaseModel):
    """Request to delete a connected Google Calendar event."""

    calendar_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    access_token_handle: str
    connected_account_id: str | None = None
    send_updates: str | None = Field(default=None, pattern=SEND_UPDATES_PATTERN)
    expected_etag: str | None = None


class CalendarEvent(BaseModel):
    """Normalized Calendar event result."""

    id: str
    title: str = ""
    start: str | None = None
    end: str | None = None
    all_day: bool = False
    timezone: str | None = None
    status: str | None = None
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)
    recurring_event_id: str | None = None
    recurrence: list[str] = Field(default_factory=list)
    html_link: str | None = None
    etag: str | None = None
