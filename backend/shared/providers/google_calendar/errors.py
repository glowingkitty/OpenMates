# backend/shared/providers/google_calendar/errors.py
#
# Classification of Google Calendar API failures into stable, safe error codes.
# Skills return these codes to the assistant; raw provider bodies, URLs and
# tokens never leave this module.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

from typing import Any

import httpx

# Google "reason" values (error.errors[].reason) that mean the token lacks a scope.
_MISSING_SCOPE_REASONS = frozenset({"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"})
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"})

RECONNECT_CODES = frozenset({"google_calendar_missing_scope", "google_calendar_reconnect_required"})
RETRYABLE_CODES = frozenset({
    "google_calendar_rate_limited", "google_calendar_provider_error", "google_calendar_unavailable",
})


class GoogleCalendarProviderError(RuntimeError):
    """A classified Google Calendar failure with a safe, stable code."""

    def __init__(
        self, code: str, *, status: int | None = None, retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retry_after_seconds = retry_after_seconds

    @property
    def reconnect_required(self) -> bool:
        return self.code in RECONNECT_CODES

    def to_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": self.code,
            "reconnect_required": self.reconnect_required,
            "retryable": self.code in RETRYABLE_CODES,
        }
        if self.status is not None:
            result["status"] = self.status
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        return result


def _reasons(response: httpx.Response) -> set[str]:
    try:
        payload = response.json()
    except ValueError:
        return set()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return set()
    reasons = {
        str(item.get("reason"))
        for item in error.get("errors") or []
        if isinstance(item, dict) and item.get("reason")
    }
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            reasons.add(str(detail["reason"]))
    return reasons


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after")
    if value and value.strip().isdigit():
        return int(value.strip())
    return None


def classify_status_error(response: httpx.Response) -> GoogleCalendarProviderError:
    """Map an HTTP error response to a classified provider error."""

    status = response.status_code
    reasons = _reasons(response)
    if status == 401:
        code = "google_calendar_reconnect_required"
    elif status == 403 and reasons & _MISSING_SCOPE_REASONS:
        code = "google_calendar_missing_scope"
    elif status == 429 or (status == 403 and reasons & _RATE_LIMIT_REASONS):
        code = "google_calendar_rate_limited"
    elif status == 403:
        # Read-only calendar, not the organizer, or no access to this calendar.
        code = "google_calendar_forbidden"
    elif status == 404:
        code = "google_calendar_not_found"
    elif status == 409:
        code = "google_calendar_duplicate"
    elif status == 410:
        code = "google_calendar_gone"
    elif status == 412:
        code = "google_calendar_conflict"
    elif status == 400:
        code = "google_calendar_invalid_request"
    else:
        code = "google_calendar_provider_error"
    return GoogleCalendarProviderError(code, status=status, retry_after_seconds=_retry_after(response))
