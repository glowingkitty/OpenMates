# contract-test-file: tooling
"""Opportunities: private profiles, new-only searches, tracking, one-line briefing, chat commands."""

from datetime import date
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402 - sibling script, path set above
import daily_meeting_opportunities as opp  # noqa: E402

TODAY = date(2026, 11, 16)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_OPPORTUNITIES_DIR", str(tmp_path / "opportunities"))
    return tmp_path / "opportunities"


def _fake_cli(events=None, jobs=None):
    calls = []

    def fake(app, requests):
        calls.append((app, requests))
        rows = events if app == "events" else jobs
        return {"results": [{"results": rows or []}] + [{"results": []}] * (len(requests) - 1), "warnings": []}
    return fake, calls


EVENTS = [{"title": f"AI night {n}", "url": f"https://example.org/e{n}", "date_start": f"2026-11-{17 + n}T18:00:00+01:00",
           "venue": {"name": "Hall", "city": "Example City"}, "provider": "Meetup"} for n in range(7)]
JOBS = [{"id": f"my_provider:{n}", "title": f"AI engineer {n}", "company": "Example GmbH", "url": f"https://example.org/j{n}",
         "location": "Example City", "remote": n % 2 == 0, "employment_type": "full_time",
         "description": "<p>Build agents.</p>"} for n in range(7)]


def _setup_profiles():
    opp.edit_profile("events", "Search", "set", "cities: Example City from 2026-11-16 until 2026-11-30", TODAY)
    opp.edit_profile("jobs", "Search", "set", "queries: AI", TODAY)


def test_new_store_is_private_and_empty_profiles_skip_searches(folder, monkeypatch):
    fake, calls = _fake_cli(EVENTS, JOBS)
    monkeypatch.setattr(opp, "_cli", fake)
    data = opp.collect(TODAY, [])
    assert (folder.stat().st_mode & 0o777) == 0o700
    assert (folder / "jobs-profile.md").stat().st_mode & 0o777 == 0o600
    assert data["jobs_empty"] and data["events_no_city"] and calls == []
    text = "\n".join(opp.render(data))
    assert "jobs profile is not set up yet" in text and "Jobs chat runs the setup" in text
    assert "no city with dates" in text


def test_daily_search_appends_only_new_items_and_briefing_shows_one_line_per_area(folder, monkeypatch):
    fake, calls = _fake_cli(EVENTS, JOBS)
    monkeypatch.setattr(opp, "_cli", fake)
    opp.home()
    _setup_profiles()
    first = opp.collect(TODAY, [])
    assert calls[0][1][0]["location"] == "Example City" and calls[0][1][0]["providers"] == opp.EVENT_PROVIDERS
    assert first["events"]["new_today"] == 5 and first["jobs"]["new_today"] == 5
    lines = opp.render(first)
    assert [line for line in lines if line.startswith("- ")] == [
        "- Events: 5 new events waiting (5 found today); continue in the Events chat.",
        "- Jobs: 5 new jobs waiting (5 found today); continue in the Jobs chat."]
    assert "AI night" not in "\n".join(lines)  # no items in the meeting
    opp.collect(TODAY, [])  # meeting_refresh rebuild on the same day adds nothing
    tracking = json.loads((folder / "tracking.json").read_text())
    assert len(tracking["events"]) == 5 and len(tracking["jobs"]) == 5
    opp.collect(date(2026, 11, 17), [])
    tracking = json.loads((folder / "tracking.json").read_text())
    assert len(tracking["events"]) == 7
    assert all("<p>" not in row["summary"] for row in tracking["jobs"].values())


def test_chat_commands_update_statuses_profile_and_deadlines(folder, monkeypatch):
    fake, _ = _fake_cli(EVENTS, JOBS)
    monkeypatch.setattr(opp, "_cli", fake)
    opp.home()
    _setup_profiles()
    opp.collect(TODAY, [])
    tracking = json.loads((folder / "tracking.json").read_text())
    event_id = next(k for k, v in tracking["events"].items() if v["title"] == "AI night 0")
    job_id = next(iter(tracking["jobs"]))
    assert "is now signed_up" in opp.set_status("events", f"AI night 0 [{event_id}]", "sign up", "with a friend", today=TODAY)
    assert "is now skipped" in opp.set_status("events", "AI night 1", "skip", today=TODAY)
    assert "deadline 2026-11-18" in opp.set_status("jobs", job_id, "interested", deadline="2026-11-18", today=TODAY)
    with pytest.raises(ValueError):
        opp.set_status("jobs", "Unknown job", "apply", today=TODAY)
    opp.edit_profile("jobs", "Experience and CV", "add", "Founder of an AI assistant", TODAY)
    jobs = (folder / "jobs-profile.md").read_text()
    assert "_Status: empty" not in jobs and "- Founder of an AI assistant (2026-11-16)" in jobs
    assert list((folder / "history").iterdir())
    text = opp.read_area("events", today=TODAY)
    assert f"[{event_id}] AI night 0 — signed_up" in text and "AI night 1" not in text  # skipped hidden
    assert "AI night 1" in opp.read_area("events", include_skipped=True, today=TODAY)
    added = opp.add_item("events", "Founders breakfast", "https://example.org/b", "2026-11-18T09:00", today=TODAY)
    assert "as interested" in added
    lines = opp.summary_lines(opp.summary(TODAY))
    deadlines = [line for line in lines if line.startswith("- Deadline")]
    assert deadlines == ["- Deadline 2026-11-17: AI night 0 (event, signed up)",
                         "- Deadline 2026-11-18: Founders breakfast (event, interested)",
                         f"- Deadline 2026-11-18: {tracking['jobs'][job_id]['title']} (job, interested)"]


def test_cities_follow_travel_dates():
    cities = opp.parse_cities("Munich until 2026-11-17; Example City from 2026-11-18; Old from 2026-12-30", TODAY, 14)
    assert cities == [("Munich", TODAY, date(2026, 11, 17)), ("Example City", date(2026, 11, 18), date(2026, 11, 30))]


def test_cli_reports_errors_without_traceback(folder, capsys):
    assert opp.main(["set-status", "--area", "jobs", "--item", "nothing", "--status", "apply"]) == 2
    assert "ERROR: not found" in capsys.readouterr().err


def test_meeting_script_points_to_the_dedicated_chats_only():
    script = briefing.MEETING_SCRIPT
    assert "continue in the Events chat / the Jobs chat" in script
    assert "Never go through events or jobs one by one here" in script
    assert "Opportunities:" not in script.split("DECISIONS {date}")[1]  # no per-item rows in the note
