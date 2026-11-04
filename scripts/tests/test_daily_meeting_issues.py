"""Tests for scripts/daily_meeting_issues.py and its briefing section."""

# contract-test-file: tooling
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_issues as issues  # noqa: E402


def test_linear_without_key_is_a_gap_not_a_failure(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    gaps: list[str] = []
    assert issues.linear_issues(gaps) is None
    assert "LINEAR_API_KEY" in gaps[0]


def test_github_failure_is_reported_as_gap(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(issues.subprocess, "run", boom)
    gaps: list[str] = []
    assert issues.github_issues(gaps) is None
    assert "GitHub issues unavailable" in gaps[0]


def test_issue_section_lists_rows_and_marks_missing_trackers():
    rows = [{"id": "#502", "title": "Upgrade OCR", "labels": ["apps"], "state": ""}]
    text = "\n".join(briefing._issue_section("GitHub issues", rows, "state"))
    assert "GitHub issues (1 open)" in text and "#502 Upgrade OCR (apps)" in text
    assert "unavailable" in "\n".join(briefing._issue_section("Linear issues", None, "state"))
