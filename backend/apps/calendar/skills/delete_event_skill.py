# backend/apps/calendar/skills/delete_event_skill.py
#
# Calendar delete-event skill.
# Deletes require connected-account delete permission and a broker-issued
# access-token handle. The skill re-reads the event, deletes with its etag as
# an If-Match precondition, and reports absence accurately (already deleted,
# not found) instead of claiming a deletion it did not perform.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.event_body import EventInputError, validate_send_updates
from backend.shared.providers.google_calendar.models import CalendarEventDeleteRequest
from backend.shared.python_utils.calendar_skill_support import (
    access_token_for_handle,
    run_calendar_request,
    summarize_errors,
)


class DeleteEventRequest(BaseModel):
    """Calendar delete-event request."""

    requests: list[dict[str, Any]] = Field(default_factory=list)


class DeleteEventResponse(BaseModel):
    """Calendar delete-event response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class DeleteEventSkill(BaseSkill):
    """Delete Calendar events after connected-account authorization."""

    @staticmethod
    def build_provider_request(
        *,
        calendar_id: str,
        event_id: str,
        access_token_handle: str,
    ) -> CalendarEventDeleteRequest:
        if not access_token_handle:
            raise ValueError("access_token_handle is required")
        return CalendarEventDeleteRequest(
            calendar_id=calendar_id,
            event_id=event_id,
            access_token_handle=access_token_handle,
        )

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        calendar_client_factory: Any | None = None,
        **_: Any,
    ) -> DeleteEventResponse:
        client_factory = calendar_client_factory or GoogleCalendarClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            request = CalendarEventDeleteRequest(**raw)
            client = client_factory(access_token=access_token_for_handle(
                request.access_token_handle, connected_account_access_tokens,
            ))
            deleted_event = await client.get_event(calendar_id=request.calendar_id, event_id=request.event_id)
            if deleted_event.status == "cancelled":
                return {"calendar_id": request.calendar_id, "status": "already_deleted",
                        "event_id": request.event_id, "deleted_event": deleted_event.model_dump()}
            if request.expected_etag and request.expected_etag != deleted_event.etag:
                return {
                    "calendar_id": request.calendar_id,
                    "error": "google_calendar_conflict",
                    "message": "The event changed since it was shown; read it again before deleting.",
                    "current_event": deleted_event.model_dump(),
                    "reconnect_required": False,
                    "retryable": False,
                }
            if deleted_event.recurring_event_id or deleted_event.recurrence:
                raise EventInputError(
                    "recurring_not_supported",
                    "Deleting recurring events is not supported yet; delete the series in Google Calendar.",
                )
            result = await client.delete_event(
                calendar_id=request.calendar_id,
                event_id=request.event_id,
                etag=deleted_event.etag,
                send_updates=validate_send_updates(request.send_updates),
            )
            return {
                "calendar_id": request.calendar_id,
                "deleted_event": deleted_event.model_dump(),
                "had_attendees": bool(deleted_event.attendees),
                "notifications": validate_send_updates(request.send_updates),
                **result,
            }

        results = [await run_calendar_request(item, run) for item in requests]
        return DeleteEventResponse(results=results, error=summarize_errors(results))
