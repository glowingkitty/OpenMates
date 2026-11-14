# backend/apps/calendar/skills/update_event_skill.py
#
# Calendar update-event skill.
# Updates require connected-account write permission and a broker-issued
# access-token handle. The skill re-reads the event after (possibly delayed)
# approval, sends only the fields the caller changes, and uses the event's
# etag as an If-Match precondition so intervening edits are never overwritten.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient, normalize_event
from backend.shared.providers.google_calendar.event_body import EventInputError, patch_body, validate_send_updates
from backend.shared.providers.google_calendar.models import CalendarEventMutationRequest
from backend.shared.python_utils.calendar_skill_support import (
    access_token_for_handle,
    run_calendar_request,
    summarize_errors,
)


class UpdateEventRequest(BaseModel):
    """Calendar update-event request."""

    requests: list[dict[str, Any]] = Field(default_factory=list)


class UpdateEventResponse(BaseModel):
    """Calendar update-event response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class UpdateEventSkill(BaseSkill):
    """Update Calendar events after connected-account authorization."""

    @staticmethod
    def build_provider_request(
        *,
        calendar_id: str,
        event_id: str,
        access_token_handle: str,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
    ) -> CalendarEventMutationRequest:
        if not access_token_handle:
            raise ValueError("access_token_handle is required")
        return CalendarEventMutationRequest(
            calendar_id=calendar_id,
            event_id=event_id,
            title=title,
            start=start,
            end=end,
            access_token_handle=access_token_handle,
            location=location,
            description=description,
            attendees=attendees,
        )

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        calendar_client_factory: Any | None = None,
        **_: Any,
    ) -> UpdateEventResponse:
        client_factory = calendar_client_factory or GoogleCalendarClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            request = CalendarEventMutationRequest(**raw)
            if not request.event_id:
                raise EventInputError("event_id_required", "event_id is required to update an event.")
            client = client_factory(access_token=access_token_for_handle(
                request.access_token_handle, connected_account_access_tokens,
            ))
            current_raw = await client.get_event_raw(calendar_id=request.calendar_id, event_id=request.event_id)
            previous_event = normalize_event(current_raw)
            if previous_event.status == "cancelled":
                return {"calendar_id": request.calendar_id, "error": "google_calendar_gone",
                        "reconnect_required": False, "retryable": False}
            if request.expected_etag and request.expected_etag != previous_event.etag:
                return {
                    "calendar_id": request.calendar_id,
                    "error": "google_calendar_conflict",
                    "message": "The event changed since it was shown; read it again before updating.",
                    "current_event": previous_event.model_dump(),
                    "reconnect_required": False,
                    "retryable": False,
                }
            if previous_event.recurring_event_id or previous_event.recurrence:
                raise EventInputError(
                    "recurring_not_supported",
                    "Changing recurring events is not supported yet; edit the series in Google Calendar.",
                )
            body = patch_body(
                current=current_raw,
                title=request.title,
                start=request.start,
                end=request.end,
                timezone_name=request.timezone,
                location=request.location,
                description=request.description,
                attendees=request.attendees,
                reminder_minutes=request.reminder_minutes,
            )
            event = await client.patch_event(
                calendar_id=request.calendar_id,
                event_id=request.event_id,
                body=body,
                etag=previous_event.etag,
                send_updates=validate_send_updates(request.send_updates),
            )
            return {
                "calendar_id": request.calendar_id,
                "status": "updated",
                "changed_fields": sorted(body),
                "event": event.model_dump(),
                "previous_event": previous_event.model_dump(),
                "has_attendees": bool(event.attendees),
                "notifications": validate_send_updates(request.send_updates),
            }

        results = [await run_calendar_request(item, run) for item in requests]
        return UpdateEventResponse(results=results, error=summarize_errors(results))
