"""Workflow input security helpers.

Workflow input accepts user text, corrected voice transcripts, and later
attachment-derived text. This module keeps the deterministic security boundary
close to the workflow-input service: sanitize invisible prompt-smuggling
characters before planner use and expose only sanitized statistics to callers.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from typing import Any

from backend.core.api.app.utils.text_sanitization import sanitize_text_payload_for_ascii_smuggling


def sanitize_workflow_input_text(text: str) -> tuple[str, dict[str, Any]]:
    """Remove ASCII-smuggling/control characters from workflow planner input."""

    sanitized, stats = sanitize_text_payload_for_ascii_smuggling(
        text,
        log_prefix="[WorkflowInput] ",
        include_stats=False,
    )
    return str(sanitized), stats


def redacted_event_summary(value: Any) -> str:
    """Return a log/event-safe summary without private payload text."""

    if value is None:
        return ""
    if isinstance(value, dict):
        return f"object:{len(value)}"
    if isinstance(value, list):
        return f"list:{len(value)}"
    if isinstance(value, str):
        return f"text:{len(value)}"
    return type(value).__name__
