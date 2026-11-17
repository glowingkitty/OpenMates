# contract-test-file: tooling
"""Decision log of dropped items, daily limits and the re-check of the daily meeting."""

from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_apply as apply  # noqa: E402
import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_triage as triage  # noqa: E402
import decision_log as log  # noqa: E402


@pytest.fixture(autouse=True)
def _log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DECISION_LOG_DIR", str(tmp_path))


def test_entries_are_appended_with_what_date_why_by_and_never_rewritten():
    first = log.add("idea", "Referral page with invite credits", "no users to refer yet", "Marco (daily meeting)", day="2026-11-10")
    log.add("chat", "Benchmark old embeds", "not a priority", "Marco (daily meeting)", "TASK-1", "2026-11-11")
    assert first == {"kind": "idea", "what": "Referral page with invite credits", "date": "2026-11-10",
                     "why": "no users to refer yet", "by": "Marco (daily meeting)", "ref": ""}
    assert [e["what"] for e in log.entries()] == ["Referral page with invite credits", "Benchmark old embeds"]
    with pytest.raises(ValueError):
        log.add("idea", "x", "", "me")  # a drop without a reason is not logged
    with pytest.raises(ValueError):
        log.add("thing", "x", "y", "me")


def test_match_finds_similar_new_items_and_ignores_unrelated_ones():
    log.add("idea", "Referral page with invite credits", "no users to refer yet", "Marco", day="2026-11-10")
    hits = log.match("Add invite credits referral page")
    assert len(hits) == 1 and log.question(hits[0]) == "We dropped this on 2026-11-10 because no users to refer yet. Still want it?"
    assert log.match("Record a landing page video") == [] and log.match("page") == []


def test_daily_limit_keeps_three_now_and_moves_the_rest_to_later_with_a_date():
    tri = triage.Triage("", [], date(2026, 11, 18))
    verdicts = [(i, tri._v("NOW", "serves marketing")) for i in range(5)]
    verdicts.insert(1, ("x", tri._v("DROP", "noise")))
    tri.cap_now(verdicts, "waiting chats")
    labels = [v["label"] for _, v in verdicts]
    assert labels == ["NOW", "DROP", "NOW", "NOW", "LATER", "LATER"] and verdicts[4][1]["date"] == "2026-11-19"
    assert "daily limit of 3 waiting chats" in verdicts[4][1]["reason"]


def test_briefing_rechecks_new_items_against_the_log_and_says_nothing_otherwise():
    entry = log.add("idea", "Referral page with invite credits", "no users to refer yet", "Marco", day="2026-11-10")
    ev = {"drop_log": [entry], "tasks": {"idea_inbox": [{"title": "Referral invite credits page"}]},
          "waiting_chats": {"chats": [{"title": "Unrelated chat", "needs": "pick a color"}]}}
    text = "\n".join(briefing._dropped_recheck(ev))
    assert "Dropped before — still want it? (1)" in text and "We dropped this on 2026-11-10 because no users to refer yet" in text
    assert briefing._dropped_recheck({"drop_log": [entry], "tasks": {}, "waiting_chats": {}}) == []


def test_apply_writes_dropped_lines_once_and_flags_a_missing_reason():
    note = ("DECISIONS 2026-11-18\nDropped:\n- idea | Referral page | no users to refer yet | \n"
            "- chat | Old benchmark chat | |\n- revive: Landing video | matters again\n")
    rows = apply.drop_rows(apply.parse_sections(note))
    assert [r["kind"] for r in rows] == ["idea", "chat"]
    first = apply.log_drops(rows, "2026-11-18", True)
    assert first[0].startswith("OK") and first[1].startswith("NEEDS ATTENTION")
    assert apply.log_drops(rows, "2026-11-18", True)[0].endswith("(already in the decision log)")
    assert len(log.entries()) == 1 and log.entries()[0]["by"] == "Marco (daily meeting)"


def test_script_documents_limits_later_archive_and_dropped_field():
    s = briefing.MEETING_SCRIPT
    assert "at most 3 waiting chats and 3 reminders are NOW" in s and "Dropped before" in s
    assert "Dropped (EVERY DROP" in s and "brings it back on that date by itself" in s
