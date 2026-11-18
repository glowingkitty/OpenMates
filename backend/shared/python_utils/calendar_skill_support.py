# backend/shared/python_utils/calendar_skill_support.py
#
# Shared execution helpers for Calendar skills (skills must not import each other).
# Resolves broker-issued access-token handles and turns classified provider or
# input failures into per-request structured results, so one failed calendar
# never hides the others and provider errors never surface as validation errors.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from backend.shared.providers.google_calendar.errors import GoogleCalendarProviderError
from backend.shared.providers.google_calendar.event_body import EventInputError


def access_token_for_handle(
    access_token_handle: str, connected_account_access_tokens: dict[str, str] | None,
) -> str:
    """The skill only runs with a token the broker issued for this exact call."""

    if not connected_account_access_tokens:
        raise PermissionError("connected account access token context is required")
    access_token = connected_account_access_tokens.get(access_token_handle)
    if not access_token:
        raise PermissionError("access_token_handle is not authorized for this skill call")
    return access_token


def input_error_result(code: str, message: str) -> dict[str, Any]:
    return {"error": f"calendar_{code}", "message": message, "reconnect_required": False, "retryable": False}


async def run_calendar_request(
    request: dict[str, Any], operation: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run one request; classified failures become that request's result."""

    calendar_id = request.get("calendar_id") if isinstance(request, dict) else None
    target = {"calendar_id": calendar_id} if calendar_id else {}
    try:
        return await operation(request)
    except GoogleCalendarProviderError as error:
        return {**target, **error.to_result()}
    except EventInputError as error:
        return {**target, **input_error_result(error.code, str(error))}
    except ValidationError as error:
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        return {**target, **input_error_result("invalid_input", "Invalid or missing fields: " + ", ".join(fields))}


def summarize_errors(results: list[dict[str, Any]]) -> str | None:
    """Top-level error only when every request failed, naming the first code."""

    if results and all(result.get("error") for result in results):
        return str(results[0]["error"])
    return None
