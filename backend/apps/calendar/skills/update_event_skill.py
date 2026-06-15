# backend/apps/calendar/skills/update_event_skill.py
#
# Calendar update-event skill contract.
# Updates require connected-account write permission and a broker-issued
# access-token handle before provider mutation.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.models import CalendarEventMutationRequest


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
            event_id=event_id,
            title=title,
            start=start,
            end=end,
            access_token_handle=access_token_handle,
            location=location,
            description=description,
            attendees=attendees or [],
        )

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        calendar_client_factory: Any | None = None,
        **_: Any,
    ) -> UpdateEventResponse:
        results: list[dict[str, Any]] = []
        for request in [CalendarEventMutationRequest(**item) for item in requests]:
            if not request.event_id:
                raise ValueError("event_id is required")
            access_token = _access_token_for_handle(
                request.access_token_handle,
                connected_account_access_tokens,
            )
            client_factory = calendar_client_factory or GoogleCalendarClient
            client = client_factory(access_token=access_token)
            event = await client.update_event(
                calendar_id=request.calendar_id,
                event_id=request.event_id,
                title=request.title,
                start=request.start,
                end=request.end,
                location=request.location,
                description=request.description,
                attendees=request.attendees,
            )
            results.append({"calendar_id": request.calendar_id, "event": event.model_dump()})
        return UpdateEventResponse(results=results)


def _access_token_for_handle(
    access_token_handle: str,
    connected_account_access_tokens: dict[str, str] | None,
) -> str:
    if not connected_account_access_tokens:
        raise PermissionError("connected account access token context is required")
    access_token = connected_account_access_tokens.get(access_token_handle)
    if not access_token:
        raise PermissionError("access_token_handle is not authorized for this skill call")
    return access_token
