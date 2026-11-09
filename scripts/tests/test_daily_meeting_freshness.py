# contract-test-file: tooling
"""Freshness gate and meeting structure of the daily briefing."""

from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402


def _live():
    return {"tasks_status": {"source": "live"}, "reminders": {"source": "live"}, "claude_chats": [{"title": "x"}]}


def test_everything_live_has_no_problems_and_discord_says_so():
    assert briefing.freshness(_live()) == []
    text = briefing.discord_text(date(2026, 11, 9), "https://x", [], "10:01")
    assert "✅" in text and "as of 10:01" in text


def test_stale_sources_are_named_in_problems_and_discord():
    ev = _live() | {"tasks_status": {"source": "cache", "fetched_at": "2026-11-08T10:00:00+00:00"},
                    "reminders": {"source": "cache", "fetched_at": "2026-11-08T09:00:00+00:00"}}
    problems = briefing.freshness(ev)
    assert len(problems) == 2 and "Tasks not live" in problems[0] and "Reminders not live" in problems[1]
    text = briefing.discord_text(date(2026, 11, 9), "https://x", problems)
    assert "⚠️ Not up to date" in text and "Reminders" in text
    assert briefing.freshness({}) and "no Claude chats" in " ".join(briefing.freshness({}))


def test_reminders_banner_only_when_not_live():
    assert briefing._reminders_banner({"source": "live"}) == []
    assert "NOT up to date" in "\n".join(briefing._reminders_banner({"source": "cache", "fetched_at": "2026-11-08T09:00"}))
    assert "UNAVAILABLE" in "\n".join(briefing._reminders_banner({}))


def test_meeting_script_starts_with_the_check_in_and_has_adhd_rules():
    script = briefing.MEETING_SCRIPT
    assert script.index("Block 1 — Check-in") < script.index("Block 2 — Safety net") < script.index("Block 3 — Focus")
    for question in ("What have you been up to", "How happy are you", "largest priorities", "energy today"):
        assert question in script
    assert "never more than **3** commitments" in script.replace("\\\n", "").replace("\n", " ") or "**3** commitments" in script
    assert "Check-in: progress" in script
