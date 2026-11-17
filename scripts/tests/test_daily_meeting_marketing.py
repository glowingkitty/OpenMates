# contract-test-file: tooling
"""Marketing and business development block: menu, win counter, ideas, style loop, feature rule."""

from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_marketing as marketing  # noqa: E402

TODAY = date(2026, 11, 18)  # Wednesday
MENU = """# menu
- videos | home | record one take; done when saved |
- press contacts | anywhere | write 3 emails; done when sent |
- business angels | anywhere | send 1 intro; done when sent | after: videos, landing page
- community posts | anywhere | one post; done when published |
- partnerships | anywhere | one proposal; done when sent |
Marketing finished: landing page
"""


def _notes(tmp_path):
    (tmp_path / "2026-11-16-decisions.md").write_text(
        "DECISIONS 2026-11-16\nMarketing pick: press contacts (done when: 3 emails; at 11:30)\n"
        "Wins: messages 5, replies 1, posts 2, applications 0\nMarketing ideas: partner with a privacy newsletter -> take\n")
    (tmp_path / "2026-11-17-decisions.md").write_text(
        "DECISIONS 2026-11-17\nWins: messages 3, replies 0, posts 1, applications 2\nMarketing finished: videos\n")
    (tmp_path / "2026-11-18-decisions.md").write_text("Wins: messages 99\n")  # today's note is never counted


def test_wins_are_parsed_and_summed_per_week_without_today(tmp_path):
    _notes(tmp_path)
    block = marketing.collect(tmp_path, {"menu": MENU}, None, TODAY)
    c = block["counter"]
    assert c["last"] == {"messages": 3, "replies": 0, "posts": 1, "applications": 2} and c["last_day"] == "2026-11-17"
    assert c["week"]["messages"] == 8 and c["last_14_days"]["posts"] == 3 and c["streak_days"] == 2
    assert marketing.parse_wins("Wins: messages 4, Replies 1, nonsense 9") == {"messages": 4, "replies": 1}


def test_proposals_rotate_least_recent_and_respect_prerequisites(tmp_path):
    _notes(tmp_path)
    block = marketing.collect(tmp_path, {"menu": MENU}, None, TODAY)
    home = [p["name"] for p in block["proposals"]["home"]]
    away = [p["name"] for p in block["proposals"]["on the go"]]
    assert len(home) == 3 and len(away) == 3 and "videos" not in away  # camera work only at home
    assert "business angels" in home and "press contacts" not in home  # angels unlocked (videos+landing finished); just-picked item waits
    fresh = marketing.collect(tmp_path / "none", {"menu": MENU.replace("Marketing finished: landing page", "")}, None, TODAY)
    assert "business angels" not in [p["name"] for p in fresh["proposals"]["home"]]


def test_missing_menu_falls_back_to_defaults_with_a_visible_gap_and_never_empty(tmp_path):
    block = marketing.collect(tmp_path, {}, {"metrics": {"paying_users_total": 228, "active_users": {"last_7_days": 9},
                                                         "periods": {"last_7_days": {"signups_completed": 0}}}}, TODAY)
    assert "built-in menu used" in block["menu_gap"] and len(block["proposals"]["on the go"]) == 3
    lapsed = [p for r in block["proposals"].values() for p in r if p["name"].startswith("outreach")]
    assert lapsed and "228 have paid ever" in lapsed[0]["done"] and "9 users were active" in lapsed[0]["done"]
    assert block["interpretation"].startswith("0 signups in 7 days: people aren't finding us yet")


def test_ideas_already_offered_and_style_rules_are_in_the_rendered_block(tmp_path):
    _notes(tmp_path)
    style = "# guide\n## Feedback rules from the daily meeting\n- 2026-11-16: never say 'supercharge'\n\n## Other\nx\n"
    press = "## Words and tone (confirmed)\n- No exclamation marks.\n\n## Founder quotes\nq\n"
    block = marketing.collect(tmp_path, {"menu": MENU, "ideas": "- promote events", "style": style, "press": press}, None, TODAY)
    text = "\n".join(marketing.render(block))
    assert "## Marketing and business development block" in text and "partner with a privacy newsletter" in text
    assert "never say 'supercharge'" in text and "No exclamation marks" in text and "Founder quotes" not in text
    assert "promote events" in text and "1-2 every day" in text
    assert "unavailable" in "\n".join(marketing.render(None))


def test_script_has_ideas_style_loop_feature_rule_and_decision_fields():
    script = briefing.MEETING_SCRIPT
    assert "1-2 fresh ideas" in script and "replaces the old weekly marketing ideas email" in script
    assert "doesn't sound like me" in script and "doesn't make sense" in script and "Style feedback:" in script
    assert "Marketing ideas: <1-2 fresh ideas offered today> -> take | park | drop" in script
    assert "Feature priority rule" in script and "how likely it is to gain users" in script
    assert "business angels, partnerships, press contacts" in script
