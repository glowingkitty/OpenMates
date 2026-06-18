# backend/apps/calendar/skills/get_events_skill.py
#
# Calendar get-events skill contract.
# The skill requires an access-token handle produced after connected-account
# permission authorization; stateless REST execution is disabled in app.yml.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.models import CalendarEventsRequest

logger = logging.getLogger(__name__)


class GetEventsRequest(BaseModel):
    """Calendar get-events request."""

    requests: list[CalendarEventsRequest] = Field(default_factory=list)


class GetEventsResponse(BaseModel):
    """Calendar get-events response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class GetEventsSkill(BaseSkill):
    """Read Calendar events with a broker-issued access-token handle."""

    @staticmethod
    def build_provider_request(
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        access_token_handle: str,
    ) -> CalendarEventsRequest:
        if not access_token_handle:
            raise ValueError("access_token_handle is required")
        return CalendarEventsRequest(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            access_token_handle=access_token_handle,
        )

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        calendar_client_factory: Any | None = None,
        **_: Any,
    ) -> GetEventsResponse:
        normalized = [CalendarEventsRequest(**item) for item in requests]
        results: list[dict[str, Any]] = []
        for item in normalized:
            access_token = _access_token_for_handle(
                item.access_token_handle,
                connected_account_access_tokens,
            )
            client_factory = calendar_client_factory or GoogleCalendarClient
            client = client_factory(access_token=access_token)
            events = await client.list_events(
                calendar_id=item.calendar_id,
                time_min=item.time_min,
                time_max=item.time_max,
            )
            results.append(
                {
                    "calendar_id": item.calendar_id,
                    "events": [event.model_dump() for event in events],
                }
            )
        return GetEventsResponse(results=results)


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
