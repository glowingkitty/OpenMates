# contract-test-file: tooling
"""Alerts for the daily meeting: reported issues and repeating errors."""

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_health as health  # noqa: E402

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def test_parse_issues_keeps_only_safe_fields_and_counts_older_open():
    payload = {"issues": [
        {"short_issue_id": "ab12", "title": "PDF  read\nfails for me@example.org", "created_at": "2026-11-05T10:00:00+00:00",
         "processed": False, "contact_email": "me@example.org", "chat_or_embed_url": "https://x/#key=SECRET"},
        {"short_issue_id": "old1", "title": "old", "created_at": "2026-10-01T10:00:00+00:00", "processed": False},
        {"short_issue_id": "old2", "title": "old done", "created_at": "2026-10-01T10:00:00+00:00", "processed": True},
    ]}
    result = health.parse_issues(payload, NOW)
    assert result["older_unprocessed_in_latest_batch"] == 1
    [issue] = result["recent"]
    assert issue["title"] == "PDF read fails for <email>"
    assert issue["age"] == "2 h ago"
    assert "SECRET" not in json.dumps(result) and "contact_email" not in issue


def test_errors_group_after_masking_ids_and_numbers():
    rows = [
        {"service": "api", "count": 2, "message": json.dumps({"name": "backend.core.x", "message": "failed for 123e4567-e89b-12d3-a456-426614174000 after 5s"})},
        {"service": "api", "count": 3, "message": json.dumps({"name": "backend.core.x", "message": "failed for 123e4567-e89b-12d3-a456-426614174001 after 9s"})},
    ]
    [top] = health.aggregate_errors(rows)
    assert top["count"] == 5 and top["message"] == "failed for <id> after <n>s"


def test_parse_query_rows_ignores_other_lines():
    assert health.parse_query_rows('header\n- {"a": 1}\n- not json\n') == [{"a": 1}]


def test_alerts_section_puts_unavailable_and_unprocessed_visibly():
    alerts = {"production": {"issues": {"recent": [{"id": "ab12", "title": "t", "age": "1 h ago", "admin": False, "processed": False}],
                                        "older_unprocessed_in_latest_batch": 2},
                             "errors": {"total": 4, "distinct": 1, "truncated": False,
                                        "top": [{"count": 4, "service": "api", "where": "x.y", "message": "boom"}]}},
              "dev": {"issues": None, "errors": None}}
    text = "\n".join(briefing._alerts_section(alerts))
    assert "not processed yet" in text and "4× `api` x.y: boom" in text
    assert "plus 2 older unprocessed" in text and "unavailable" in text
    assert text.index("Production") < text.index("Dev server")
