# contract-test-file: tooling
"""Goals and milestones evidence, drift warnings, Monday block and the structured note template."""

from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_goals as goals  # noqa: E402

MONDAY, TUESDAY = date(2026, 11, 16), date(2026, 11, 17)


def _task(task_id, status, priority="none", labels=()):
    return {"id": task_id, "title": f"title {task_id}", "status": status, "priority": priority, "labels": list(labels)}


def test_progress_counts_labels_movement_and_unlabelled_high_priority():
    now = [_task("A", "done", labels=["milestone:money"]), _task("B", "todo", "high", ["milestone:money"]),
           _task("C", "in_progress", "urgent"), _task("D", "todo", "low")]
    old = [_task("A", "todo"), _task("B", "todo")]
    progress = goals.milestone_progress(now, old)
    assert progress["milestones"]["money"]["statuses"] == {"done": 1, "todo": 1}
    assert progress["milestones"]["money"]["moved_this_week"] == 1 and progress["milestones"]["money"]["open_high"] == 1
    assert progress["high_open_without_milestone"] == {"count": 1, "examples": ["title C"]}


def test_drift_warnings_cover_missing_file_overdue_review_and_stalled_milestone():
    assert "does not exist yet" in goals.drift_warnings({}, "", MONDAY)[0]
    old_file = "# Goals\nLast weekly review: 2026-11-02\n"
    assert any("overdue" in w for w in goals.drift_warnings({}, old_file, MONDAY))
    stalled = {"baseline": "snapshot about a week ago", "milestones": {"money": {"moved_this_week": 0, "open_high": 2}}}
    assert any("none moved this week" in w for w in goals.drift_warnings(stalled, "Last weekly review: 2026-11-16", MONDAY))


def test_collect_reads_goals_settings_and_old_snapshot(tmp_path):
    (tmp_path / "GOALS.md").write_text("# Goals\nLast weekly review: 2026-11-09\n")
    out = tmp_path / "logs/daily-meetings"
    out.mkdir(parents=True)
    (out / "meeting-settings.md").write_text("Keep block 6 to 5 minutes.")
    (out / "meeting-changelog.md").write_text("- 2026-11-09 shorten block 6 (trial until 2026-11-16)\n")
    (out / "2026-11-09-tasks.json").write_text(json.dumps([_task("A", "todo", labels=["milestone:money"])]))
    result = goals.collect(tmp_path, out, [_task("A", "done", labels=["milestone:money"])], MONDAY)
    assert result["is_monday"] and result["last_review"] == "2026-11-09"
    assert result["progress"]["milestones"]["money"]["moved_this_week"] == 1
    assert result["meeting_settings"] == "Keep block 6 to 5 minutes." and len(result["meeting_changelog"]) == 1


def test_goals_section_marks_monday_and_adjustments_are_injected():
    data = {"goals_file": "# Goals\nMission: x", "last_review": "2026-11-09", "warnings": ["review overdue"],
            "progress": {"milestones": {}, "baseline": "none"}, "meeting_settings": "Be brief.",
            "meeting_changelog": ["- 2026-11-09 shorter"]}
    monday = "\n".join(briefing._goals_section(data, MONDAY))
    assert "Monday: run the goals block" in monday and "review overdue" in monday and "no Task carries a milestone label" in monday
    assert "Not a Monday" in "\n".join(briefing._goals_section(data, TUESDAY))
    assert "Be brief." in "\n".join(briefing._meeting_adjustments(data)) and briefing._meeting_adjustments({}) == []


def test_meeting_script_has_goals_block_retro_and_structured_tables():
    script = briefing.MEETING_SCRIPT
    assert "Block 6 on Mondays — Goals and milestones" in script and "Improve the meeting" in script
    assert "| Action | Reminder (exact title) | List | New due | New title | Notes |" in script
    assert "| Action | Task (exact title) | New title | Priority | Status | Label | Due | Description |" in script
    assert "Goals:" in script and "Meeting: <" in script and "milestone does today's top task serve" in script
