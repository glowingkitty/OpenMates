# backend/apps/calendar/skills/get_events_skill.py
#
# Calendar get-events skill.
# Lists one page of events in a bounded, explicit interval with continuation.
# The skill requires an access-token handle produced after connected-account
# permission authorization; stateless REST execution is disabled in app.yml.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.event_body import EventInputError
from backend.shared.providers.google_calendar.models import CalendarEventsRequest
from backend.shared.python_utils.calendar_skill_support import (
    access_token_for_handle,
    run_calendar_request,
    summarize_errors,
)

MAX_INTERVAL_DAYS = 366


class GetEventsRequest(BaseModel):
    """Calendar get-events request."""

    requests: list[CalendarEventsRequest] = Field(default_factory=list)


class GetEventsResponse(BaseModel):
    """Calendar get-events response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


def _bound(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    except ValueError as exc:
        raise EventInputError("invalid_time", f"{field} is not an RFC 3339 date-time.") from exc
    if parsed.tzinfo is None:
        raise EventInputError("timezone_required", f"{field} needs a UTC offset such as Z or +01:00.")
    return parsed


def validate_interval(time_min: str, time_max: str) -> None:
    start, end = _bound(time_min, "time_min"), _bound(time_max, "time_max")
    if end <= start:
        raise EventInputError("end_before_start", "time_max must be after time_min.")
    if (end - start).days > MAX_INTERVAL_DAYS:
        raise EventInputError("interval_too_long", f"Read at most {MAX_INTERVAL_DAYS} days at once.")


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
        client_factory = calendar_client_factory or GoogleCalendarClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            item = CalendarEventsRequest(**raw)
            client = client_factory(access_token=access_token_for_handle(
                item.access_token_handle, connected_account_access_tokens,
            ))
            validate_interval(item.time_min, item.time_max)
            page = await client.list_events(
                calendar_id=item.calendar_id,
                time_min=item.time_min,
                time_max=item.time_max,
                max_results=item.max_results,
                page_token=item.page_token,
                query=item.query,
                time_zone=item.timezone,
            )
            return {
                "calendar_id": item.calendar_id,
                "time_min": item.time_min,
                "time_max": item.time_max,
                "events": [event.model_dump() for event in page["events"]],
                "next_page_token": page.get("next_page_token"),
                "has_more": bool(page.get("next_page_token")),
                "calendar_timezone": page.get("calendar_timezone"),
            }

        results = [await run_calendar_request(item, run) for item in requests]
        return GetEventsResponse(results=results, error=summarize_errors(results))
