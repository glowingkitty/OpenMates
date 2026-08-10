"""
Issue-report text normalization helpers.

Issue reports are a support/debugging boundary: values may come from older
clients and must be readable in Directus, email, Linear, and S3 YAML. Keep this
module dependency-free so tests can import it without loading the FastAPI app.
"""

from __future__ import annotations

from typing import Optional


RAW_CHAT_ERROR_KEYS = ("chat.an_error_occured", "chat.an_error_occurred")
ISSUE_REPORT_CHAT_ERROR_TEXT = "AI processing error"


def normalize_issue_report_error_sentinels(value: Optional[str]) -> Optional[str]:
    """Replace raw chat error i18n keys before storing or forwarding reports."""
    if value is None:
        return None
    normalized = value
    for raw_key in RAW_CHAT_ERROR_KEYS:
        normalized = normalized.replace(raw_key, ISSUE_REPORT_CHAT_ERROR_TEXT)
    return normalized


def normalize_issue_report_trace_ids(trace_ids: Optional[list]) -> list[str]:
    """Bound trace IDs persisted in issue-report YAML for timeline correlation."""
    return [str(trace_id)[:64] for trace_id in (trace_ids or []) if trace_id]
