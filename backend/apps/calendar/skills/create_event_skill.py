# backend/apps/calendar/skills/create_event_skill.py
#
# Calendar create-event skill.
# Provider mutation execution is gated by connected-account permission policy
# and a broker-issued access-token handle. Each create carries a stable event id
# derived from the chat message and request, so a retried or uncertain create
# returns the event that already exists instead of making a duplicate.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.event_body import (
    create_body,
    idempotent_event_id,
    validate_send_updates,
)
from backend.shared.providers.google_calendar.models import CalendarEventMutationRequest
from backend.shared.python_utils.calendar_skill_support import (
    access_token_for_handle,
    run_calendar_request,
    summarize_errors,
)


class CreateEventRequest(BaseModel):
    """Calendar create-event request."""

    requests: list[dict[str, Any]] = Field(default_factory=list)


class CreateEventResponse(BaseModel):
    """Calendar create-event response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class CreateEventSkill(BaseSkill):
    """Create Calendar events after connected-account authorization."""

    @staticmethod
    def build_provider_request(
        *,
        calendar_id: str,
        title: str,
        start: str,
        end: str,
        access_token_handle: str,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
    ) -> CalendarEventMutationRequest:
        if not access_token_handle:
            raise ValueError("access_token_handle is required")
        return CalendarEventMutationRequest(
            calendar_id=calendar_id,
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
        message_id: str | None = None,
        **_: Any,
    ) -> CreateEventResponse:
        client_factory = calendar_client_factory or GoogleCalendarClient
        results: list[dict[str, Any]] = []

        for index, raw in enumerate(requests):
            async def run(raw: dict[str, Any], index: int = index) -> dict[str, Any]:
                request = CalendarEventMutationRequest(**raw)
                client = client_factory(access_token=access_token_for_handle(
                    request.access_token_handle, connected_account_access_tokens,
                ))
                operation_key = (
                    f"{message_id}:{index}:{request.calendar_id}:{request.title}:{request.start}:{request.end}"
                    if message_id else None
                )
                body = create_body(
                    title=request.title or "",
                    start=request.start or "",
                    end=request.end,
                    timezone_name=request.timezone,
                    location=request.location,
                    description=request.description,
                    attendees=request.attendees,
                    reminder_minutes=request.reminder_minutes,
                    event_id=idempotent_event_id(operation_key) if operation_key else None,
                )
                event, already_existed = await client.create_event(
                    calendar_id=request.calendar_id,
                    body=body,
                    send_updates=validate_send_updates(request.send_updates),
                )
                if not event.id:
                    return {"calendar_id": request.calendar_id, "error": "google_calendar_outcome_uncertain",
                            "reconnect_required": False, "retryable": False}
                return {
                    "calendar_id": request.calendar_id,
                    "status": "already_created" if already_existed else "created",
                    "event": event.model_dump(),
                    "invited_attendees": [] if not request.attendees else event.attendees,
                    "notifications": validate_send_updates(request.send_updates),
                }

            results.append(await run_calendar_request(raw, run))
        return CreateEventResponse(results=results, error=summarize_errors(results))
