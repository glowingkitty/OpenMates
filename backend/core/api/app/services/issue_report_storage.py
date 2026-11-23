"""Fit an issue report's text into the Directus ``issues`` columns without losing it.

The ``issues.title`` column is still varchar(255) on existing databases (the
schema YAML declares TEXT, but setup_schemas.py does not alter existing custom
fields). The Report Issue form sends its single free-text field as the title,
so a long report used to be cut to 250 characters and the rest was lost
(issue A5455). The title stays a short preview and the complete text goes to
the unbounded ``description`` column, ahead of any description the client sent.

Used by: backend/core/api/app/routes/settings.py (report_issue)
Tests: backend/tests/test_issue_report_storage.py
"""

from __future__ import annotations

ISSUE_REPORT_DB_TITLE_MAX_CHARS = 250


def fit_issue_text_for_storage(
    title: str, description: str | None
) -> tuple[str, str | None, bool]:
    """Return ``(db_title, db_description, truncated)`` keeping the full title text."""
    if len(title) <= ISSUE_REPORT_DB_TITLE_MAX_CHARS:
        return title, description, False
    full_text = title if not description else f"{title}\n\n{description}"
    return title[:ISSUE_REPORT_DB_TITLE_MAX_CHARS], full_text, True
