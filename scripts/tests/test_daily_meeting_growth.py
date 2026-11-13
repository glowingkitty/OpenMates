# contract-test-file: tooling
"""Production growth numbers in the daily meeting briefing: exclusions, snapshots, rendering."""

import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402 - sibling scripts, path set above
import daily_meeting_growth as growth  # noqa: E402

METRICS = {"since": "2026-11-12T10:30:00+00:00", "total_users": 640, "paying_users_total": 220,
           "excluded_accounts": 9, "active_users": {"last_24_hours": 41, "last_7_days": 150},
           "periods": {"since_last_meeting": {"signups_completed": 9, "signups_started": 12,
                                              "new_paying_users": 2, "credit_purchases": 5},
                       "since_last_meeting_previous": {"signups_completed": 4, "signups_started": 6,
                                                       "new_paying_users": 2, "credit_purchases": 3},
                       "last_7_days": {"signups_completed": 30, "signups_started": 40,
                                       "new_paying_users": 6, "credit_purchases": 14},
                       "previous_7_days": {"signups_completed": 20, "signups_started": 25,
                                           "new_paying_users": 0, "credit_purchases": 10}}}


def test_excluded_emails_come_from_env_and_private_file(tmp_path):
    (tmp_path / ".env").write_text("A_EMAIL=Owner@Example.org\n# B_EMAIL=old@example.org\n"
                                   "LIST=a@example.org, b@example.org\nTOKEN=abc\n")
    (tmp_path / growth.EXCLUDE_FILE).write_text("# founder\nsecond@example.org\n")
    emails = growth.excluded_emails(tmp_path, tmp_path)
    assert emails == {"owner@example.org", "a@example.org", "b@example.org", "second@example.org"}
    assert growth.email_hash("Owner@Example.org ") == base64.b64encode(
        hashlib.sha256(b"owner@example.org").digest()).decode()


def test_snapshot_returns_previous_day_and_keeps_counts_only(tmp_path):
    assert growth.remember(tmp_path, "2026-11-12", METRICS) is None
    previous = growth.remember(tmp_path, "2026-11-13", {**METRICS, "total_users": 650})
    assert previous["date"] == "2026-11-12" and previous["total_users"] == 640
    stored = json.loads((tmp_path / growth.HISTORY_FILE).read_text())
    assert set(stored["2026-11-13"]) == {"total_users", "paying_users_total", "active_users"}


def test_render_shows_trends_and_unavailable_state():
    lines = "\n".join(growth.render({"metrics": METRICS, "previous_snapshot": {
        "date": "2026-11-12", "total_users": 631, "active_users": {"last_24_hours": 30, "last_7_days": 150}}}))
    assert "## Marketing and growth numbers (production)" in lines
    assert "**Total users:** 640 (last meeting snapshot 2026-11-12: 631)" in lines
    assert "since the last meeting:** 9 (previous period: 4, +5, +125%); started but not finished: 3" in lines
    assert "41 in the last 24 h (previous period: 30, +11, +37%)" in lines
    assert "6 in the last 7 days (previous period: 0, +6)" in lines
    assert "9 accounts" in lines
    missing = "\n".join(growth.render(None))
    assert "unavailable" in missing and "do not guess" in missing


def test_collect_records_gap_when_production_is_unreachable(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("growth-metrics HTTP 404: Not Found")
    monkeypatch.setattr(growth, "fetch", boom)
    gaps: list[str] = []
    assert growth.collect(tmp_path, tmp_path, briefing.datetime(2026, 11, 12), "2026-11-13", gaps) is None
    assert gaps == ["production growth numbers unavailable (growth-metrics HTTP 404: Not Found)"]


def test_meeting_script_reports_growth_in_the_drift_check():
    script = briefing.MEETING_SCRIPT
    drift = script.index("daily drift check")
    numbers = script.index("**growth numbers**")
    question = script.index("**exactly one** open question", drift)
    assert drift < numbers < question
    assert "current milestone" in script[numbers:question] and "never guess" in script[numbers:question]
