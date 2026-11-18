# Connected-account calendar discovery.
# Uses the existing first-party permission and token brokers, never API keys alone.
# Returns one explicit page of selectable calendar metadata and safe failures.
# No refresh tokens or raw provider diagnostics are returned to callers.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.python_utils.calendar_skill_support import (
    access_token_for_handle,
    run_calendar_request,
    summarize_errors,
)


class CalendarListRequest(BaseModel):
    access_token_handle: str = Field(min_length=1)
    connected_account_id: str | None = None
    page_token: str | None = Field(default=None, max_length=4096)
    show_hidden: bool = False
    max_results: int = Field(default=100, ge=1, le=250)


class ListCalendarsRequest(BaseModel):
    requests: list[CalendarListRequest] = Field(min_length=1, max_length=20)


class ListCalendarsResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class ListCalendarsSkill(BaseSkill):
    """Discover selectable calendars using a broker-authorized account."""

    async def execute(
        self, requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        calendar_client_factory: Any | None = None, **_: Any,
    ) -> ListCalendarsResponse:
        normalized = ListCalendarsRequest(requests=requests)
        client_factory = calendar_client_factory or GoogleCalendarClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            item = CalendarListRequest(**raw)
            client = client_factory(access_token=access_token_for_handle(
                item.access_token_handle, connected_account_access_tokens,
            ))
            page = await client.list_calendars(
                page_token=item.page_token, show_hidden=item.show_hidden, max_results=item.max_results,
            )
            return {**page, "has_more": bool(page.get("next_page_token"))}

        results = [await run_calendar_request(item.model_dump(), run) for item in normalized.requests]
        return ListCalendarsResponse(results=results, error=summarize_errors(results))
