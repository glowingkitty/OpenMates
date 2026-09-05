# Connected-account calendar discovery.
# Uses the existing first-party permission and token brokers, never API keys alone.
# Returns one explicit page of selectable calendar metadata and safe failures.
# No refresh tokens or raw provider diagnostics are returned to callers.
# Architecture: docs/architecture/app_skills.md

from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_calendar.client import GoogleCalendarClient


class CalendarListRequest(BaseModel):
    access_token_handle: str = Field(min_length=1)
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
        results: list[dict[str, Any]] = []
        for item in normalized.requests:
            token = (connected_account_access_tokens or {}).get(item.access_token_handle)
            if not token:
                raise PermissionError("connected account access token context is required")
            client = (calendar_client_factory or GoogleCalendarClient)(access_token=token)
            try:
                results.append(await client.list_calendars(
                    page_token=item.page_token, show_hidden=item.show_hidden,
                    max_results=item.max_results,
                ))
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                code = "google_calendar_provider_error"
                try:
                    errors = exc.response.json().get("error", {}).get("errors", [])
                    missing_scope = any(error.get("reason") == "insufficientPermissions" for error in errors)
                except (ValueError, AttributeError, TypeError):
                    missing_scope = False
                if status == 403 and missing_scope:
                    code = "google_calendar_missing_scope"
                elif status == 401:
                    code = "google_calendar_reconnect_required"
                results.append({
                    "error": code, "status": status,
                    "reconnect_required": code in {"google_calendar_missing_scope", "google_calendar_reconnect_required"},
                })
            except httpx.RequestError:
                results.append({"error": "google_calendar_unavailable", "reconnect_required": False})
        return ListCalendarsResponse(results=results)
