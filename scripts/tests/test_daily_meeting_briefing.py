# contract-test-file: tooling
"""Daily meeting briefing: phase calendar, rendering from sparse evidence, Discord text."""

from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_meeting_briefing as briefing  # noqa: E402 - scripts dir added to path above


def test_phase_alternates_from_marketing_week_on_2_november_2026():
    assert briefing.phase(date(2026, 11, 2))[0] == "Marketing Week"
    assert briefing.phase(date(2026, 11, 8))[0] == "Marketing Week"
    assert briefing.phase(date(2026, 11, 9))[0] == "Build Week"
    assert briefing.phase(date(2026, 11, 16))[0] == "Marketing Week"


def test_render_includes_meeting_script_usage_and_decisions_template_with_gaps():
    evidence = {
        "window": {"since": "2026-11-02T10:00+01:00", "until": "2026-11-03T10:00+01:00"},
        "focus_file": "# Focus\nWeek goals: record videos",
        "claude_usage": {"weekly": {"used_percent": 62.0, "resets": "Fri 06 Nov 11:00"},
                         "five_hour": None},
        "reminders": {}, "tasks": {}, "nightly": {}, "git": {}, "claude_chats": [],
        "gaps": ["Mac offline"],
    }
    text = briefing.render(evidence, {"themes": [], "loose_ends": [], "chats": []},
                           date(2026, 11, 3), datetime(2026, 11, 3, 9, tzinfo=timezone.utc))
    assert "Marketing Week" in text
    assert "DECISIONS 2026-11-03" in text
    assert "62% of this week's usage spent" in text
    assert "record videos" in text
    assert "Mac offline" in text


def test_discord_text_carries_link_not_document():
    text = briefing.discord_text(date(2026, 11, 3), "https://example.invalid/briefing.md")
    assert "https://example.invalid/briefing.md" in text
    assert "Marketing Week" in text and len(text) < 600
