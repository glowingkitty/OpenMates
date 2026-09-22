"""Private terminal-failure marker shared by main processing and its consumer."""

from __future__ import annotations

from typing import Any, Final


MAIN_PROCESSING_FAILURE_MARKER: Final = "__main_processing_failure__"
MAIN_PROCESSING_FAILURE_REASONS: Final = frozenset(
    {
        "provider_exhausted",
        "protocol_guard",
        "empty_post_tool_response",
    }
)


def main_processing_failure(reason: str) -> dict[str, Any]:
    """Build a bounded internal marker; provider details never enter the stream."""
    if reason not in MAIN_PROCESSING_FAILURE_REASONS:
        raise ValueError(f"Unsupported main-processing failure reason: {reason}")
    return {MAIN_PROCESSING_FAILURE_MARKER: True, "reason": reason}


def main_processing_failure_reason(value: object) -> str | None:
    """Return the validated reason when *value* is a terminal failure marker."""
    if not isinstance(value, dict) or value.get(MAIN_PROCESSING_FAILURE_MARKER) is not True:
        return None
    reason = value.get("reason")
    return reason if isinstance(reason, str) and reason in MAIN_PROCESSING_FAILURE_REASONS else None
