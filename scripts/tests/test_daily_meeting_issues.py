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
    assert "GitHub issues (1 open)" in text and "Upgrade OCR (#502, apps)" in text
    assert "unavailable" in "\n".join(briefing._issue_section("Linear issues", None, "state"))


def test_cleanup_batch_takes_oldest_items_and_skips_recently_kept():
    from datetime import date

    tasks = [{"id": f"TASK-{n}", "title": f"t{n}", "status": "todo"} for n in (30, 5, 12)]
    tasks.append({"id": "TASK-1", "title": "done", "status": "done"})
    github = [{"id": "#2", "title": "old", "updated": "2025-01-01"},
              {"id": "#9", "title": "newer", "updated": "2026-10-01"},
              {"id": "#7", "title": "kept", "updated": "2024-01-01"}]
    result = issues.cleanup_candidates(tasks, github, None, {"#7": "2026-10-20"}, date(2026, 11, 4), batch=2)
    assert [t["id"] for t in result["tasks"]["batch"]] == ["TASK-5", "TASK-12"]
    assert result["tasks"]["total"] == 3
    assert [i["id"] for i in result["github"]["batch"]] == ["#2", "#9"]
    assert result["linear"] == {"total": 0, "batch": []}
    old_keep = issues.cleanup_candidates(None, github, None, {"#7": "2026-09-01"}, date(2026, 11, 4))
    assert old_keep["github"]["batch"][0]["id"] == "#7"


def test_briefing_has_cleanup_section_and_template_lines():
    cleanup = {"tasks": {"total": 3, "batch": [{"id": "TASK-5", "title": "Old idea", "status": "todo",
                                                  "priority": "low"}]},
               "github": {"total": 1, "batch": [{"id": "#2", "title": "Stale", "updated": "2025-01-01"}]},
               "linear": {"total": 0, "batch": []}}
    text = "\n".join(briefing._cleanup_section(cleanup))
    assert "## 4. Backlog cleanup" in text and "Old idea (TASK-5)" in text and "Stale (#2" in text
    assert "nothing to review" in text
    assert "Cleanup:" in briefing.MEETING_SCRIPT and "backlog cleanup" in briefing.MEETING_SCRIPT
