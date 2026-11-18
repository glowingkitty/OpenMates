# backend/shared/providers/figma/errors.py
#
# Classified Figma failures with stable, safe codes. Provider message text is
# only inspected for classification and never returned, because it can echo
# file content.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

from typing import Any

import httpx

RECONNECT_CODES = frozenset({"figma_reconnect_required", "figma_missing_scope"})
RETRYABLE_CODES = frozenset({
    "figma_rate_limited", "figma_provider_error", "figma_unavailable", "figma_token_superseded",
})


class FigmaProviderError(RuntimeError):
    """A classified Figma failure with a safe, stable code."""

    def __init__(
        self, code: str, *, status: int | None = None, retry_after_seconds: int | None = None,
        plan_tier: str | None = None, rate_limit_type: str | None = None,
        upgrade_link: str | None = None, message: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.plan_tier = plan_tier
        self.rate_limit_type = rate_limit_type
        self.upgrade_link = upgrade_link
        self.message = message

    @property
    def reconnect_required(self) -> bool:
        return self.code in RECONNECT_CODES

    def to_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": self.code,
            "reconnect_required": self.reconnect_required,
            "retryable": self.code in RETRYABLE_CODES,
        }
        for key in ("status", "retry_after_seconds", "plan_tier", "rate_limit_type", "upgrade_link"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.message:
            result["message"] = self.message
        return result


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("message") or payload.get("err") or "").lower()


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after", "").strip()
    return int(value) if value.isdigit() else None


def classify_status_error(response: httpx.Response) -> FigmaProviderError:
    """Map an HTTP error response to a classified provider error."""

    status = response.status_code
    text = _message(response)
    extra: dict[str, Any] = {}
    if status == 401:
        code = "figma_reconnect_required"
    elif status == 403 and "invalid scope" in text:
        code = "figma_missing_scope"
    elif status == 403 and ("token" in text and ("invalid" in text or "expired" in text)):
        code = "figma_token_superseded"
    elif status == 403 and ("plan" in text or "limited" in text):
        code = "figma_plan_limited"
    elif status == 403:
        code = "figma_forbidden"
    elif status == 404:
        code = "figma_not_found"
    elif status == 429:
        code = "figma_rate_limited"
        extra = {
            "plan_tier": response.headers.get("x-figma-plan-tier"),
            "rate_limit_type": response.headers.get("x-figma-rate-limit-type"),
            "upgrade_link": response.headers.get("x-figma-upgrade-link"),
        }
    elif status == 400:
        code = "figma_invalid_request"
    else:
        code = "figma_provider_error"
    return FigmaProviderError(code, status=status, retry_after_seconds=_retry_after(response), **extra)
