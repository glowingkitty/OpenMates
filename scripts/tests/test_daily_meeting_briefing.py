# contract-test-file: tooling
"""Daily meeting briefing: rendering from sparse evidence, Discord text, no phase rules."""

from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_meeting_briefing as briefing  # noqa: E402 - scripts dir added to path above


def test_briefing_has_no_marketing_or_build_week_phase():
    assert not hasattr(briefing, "phase") and not hasattr(briefing, "PHASE_ANCHOR")
    for word in ("Marketing Week", "Build Week", "Phase rules", "push back"):
        assert word not in briefing.MEETING_SCRIPT


def test_render_includes_meeting_script_usage_and_decisions_template_with_gaps():
    evidence = {
        "window": {"since": "2026-11-02T10:00+01:00", "until": "2026-11-03T10:00+01:00"},
        "focus_file": "# Focus\nWeek goals: record videos",
        "product": {"tagline": "Your agentic operating system", "description": "OpenMates is an assistant.",
                    "features": ["**Apps inside chat:** search"]},
        "claude_usage": {"weekly": {"used_percent": 62.0, "resets": "Fri 06 Nov 11:00",
                                    "week_elapsed_percent": 60, "runs_out": "Fri 06 Nov 04:12"},
                         "five_hour": None},
        "reminders": {}, "nightly": {}, "git": {}, "claude_chats": [],
        "tasks": {"changed_since_last_meeting": [{"id": "TASK-1", "title": "Send the journalist emails",
                                                  "from": "todo", "to": "in_progress"}]},
        "gaps": ["Mac offline"],
    }
    text = briefing.render(evidence, {"themes": [], "loose_ends": [], "chats": []},
                           date(2026, 11, 3), datetime(2026, 11, 3, 9, tzinfo=timezone.utc))
    assert "Marketing Week" not in text and "Build Week" not in text and "Phase" not in text
    assert "## 1. Focus file (FOCUS.md)" in text
    assert "DECISIONS 2026-11-03" in text
    assert "38% of the weekly limit left" in text
    assert "runs out **Fri 06 Nov 04:12**" in text
    assert text.index("weekly limit left") < text.index("How to run this meeting")
    assert "## About OpenMates" in text and "Your agentic operating system" in text
    assert "- **Apps inside chat:** search" in text
    assert "record videos" in text
    assert "Mac offline" in text
    assert "**Changed since the last meeting, still open (1):**" in text
    assert "- TASK-1 Send the journalist emails (todo → in_progress)" in text


def test_discord_text_carries_link_not_document():
    text = briefing.discord_text(date(2026, 11, 3), "https://example.invalid/briefing.md")
    assert "https://example.invalid/briefing.md" in text
    assert "Marketing Week" not in text and len(text) < 600


def test_meeting_script_asks_exactly_one_question_at_a_time():
    assert "exactly one question at a time" in briefing.MEETING_SCRIPT
    assert "at most 3 questions" not in briefing.MEETING_SCRIPT


def test_scheduled_run_only_proceeds_on_weekdays_from_0830_berlin():
    from datetime import datetime
    berlin = briefing.TZ
    assert briefing.in_scheduled_slot(datetime(2026, 11, 11, 8, 30, tzinfo=berlin))
    assert briefing.in_scheduled_slot(datetime(2026, 7, 1, 8, 31, tzinfo=berlin))  # summer time
    assert not briefing.in_scheduled_slot(datetime(2026, 11, 11, 8, 29, tzinfo=berlin))
    assert not briefing.in_scheduled_slot(datetime(2026, 11, 11, 9, 30, tzinfo=berlin))
    assert not briefing.in_scheduled_slot(datetime(2026, 11, 14, 8, 30, tzinfo=berlin))  # Saturday
