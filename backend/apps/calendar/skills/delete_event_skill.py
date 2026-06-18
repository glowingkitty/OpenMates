# backend/apps/calendar/skills/delete_event_skill.py
#
# Calendar delete-event skill contract.
# Deletes require connected-account delete permission and a broker-issued
# access-token handle before provider mutation.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.models import CalendarEventDeleteRequest


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
        results: list[dict[str, Any]] = []
        for request in [CalendarEventDeleteRequest(**item) for item in requests]:
            access_token = _access_token_for_handle(
                request.access_token_handle,
                connected_account_access_tokens,
            )
            client_factory = calendar_client_factory or GoogleCalendarClient
            client = client_factory(access_token=access_token)
            deleted_event = await client.get_event(
                calendar_id=request.calendar_id,
                event_id=request.event_id,
            )
            result = await client.delete_event(
                calendar_id=request.calendar_id,
                event_id=request.event_id,
            )
            results.append(
                {
                    "calendar_id": request.calendar_id,
                    "deleted_event": deleted_event.model_dump(),
                    **result,
                }
            )
        return DeleteEventResponse(results=results)


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
