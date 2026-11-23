# backend/shared/providers/gmail/errors.py
#
# Classified Gmail API failures with stable, safe codes. A missing scope is
# distinguished from a plain permission failure so the UI can ask the user to
# reconnect with the needed capability instead of showing an empty mailbox.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

from typing import Any

import httpx

_MISSING_SCOPE_REASONS = frozenset({"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"})
# Cloud project has the API switched off (operator action, not a user reconnect).
_API_DISABLED_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"})

RECONNECT_CODES = frozenset({"gmail_missing_scope", "gmail_reconnect_required"})
RETRYABLE_CODES = frozenset({"gmail_rate_limited", "gmail_provider_error", "gmail_unavailable"})


class GmailProviderError(RuntimeError):
    """A classified Gmail failure with a safe, stable code."""

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


class MailInputError(ValueError):
    """The request itself is invalid; nothing was sent to Google."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def classify_status_error(response: httpx.Response) -> GmailProviderError:
    """Map an HTTP error response to a classified provider error."""

    status = response.status_code
    reasons = _reasons(response)
    if status == 401:
        code = "gmail_reconnect_required"
    elif status == 403 and reasons & _API_DISABLED_REASONS:
        code = "gmail_api_disabled"
    elif status == 403 and reasons & _MISSING_SCOPE_REASONS:
        code = "gmail_missing_scope"
    elif status == 429 or (status == 403 and reasons & _RATE_LIMIT_REASONS):
        code = "gmail_rate_limited"
    elif status == 403:
        code = "gmail_forbidden"
    elif status == 404:
        code = "gmail_not_found"
    elif status == 400:
        code = "gmail_invalid_request"
    else:
        code = "gmail_provider_error"
    return GmailProviderError(code, status=status, retry_after_seconds=_retry_after(response))
