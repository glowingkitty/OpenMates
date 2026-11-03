# contract-test-file: tooling
"""Apple Reminders meeting overview and the fixed Mac transport admission."""

from datetime import date
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import mac_reminders  # noqa: E402 - path set above for the guard's sibling imports


def _item(title, due, list_name="Personal Tasks"):
    return {"id": f"x-apple-reminder://{title}", "title": title, "list": list_name, "due": due,
            "notes": "", "priority": 0}


def test_overview_buckets_by_due_window_and_summarizes_old_backlog():
    today = date(2026, 11, 4)
    items = [
        _item("old-a", "2026-09-10"), _item("old-b", "2026-10-02T08:00:00Z"),
        _item("recent", "2026-11-01"), _item("today", "2026-11-04", "OpenMates"),
        _item("soon", "2026-11-11T09:00:00Z", "OpenMates"), _item("later", "2026-12-01"),
        _item("undated", None),
    ]
    view = mac_reminders.overview(items, today)
    assert view["open_total"] == 7
    assert [i["title"] for i in view["overdue_recent"]] == ["recent"]
    assert [i["title"] for i in view["due_next_days"]] == ["today", "soon"]
    assert [i["title"] for i in view["undated"]] == ["undated"]
    assert view["overdue_old_by_month"] == {"2026-09": 1, "2026-10": 1}
    assert view["counts"]["due_next_days"] == {"OpenMates": 2}
    assert "overdue_old" not in view  # the backlog is summarized, never listed in full


def test_utc_timestamps_are_bucketed_on_the_berlin_date():
    # 23:30 UTC on Nov 3 is already Nov 4 in Berlin: due today, not overdue.
    view = mac_reminders.overview([_item("late", "2026-11-03T23:30:00Z")], date(2026, 11, 4))
    assert [i["title"] for i in view["due_next_days"]] == ["late"]


def test_reminders_helper_is_admitted_and_cannot_delete(tmp_path, monkeypatch):
    guard = importlib.import_module("apple_no_delete_guard")
    monkeypatch.setattr(guard, "STATE_PATH", tmp_path / "stops.sqlite3")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-reminders")
    guard.require_safe_operation("reminders-op")
    guard.require_safe_command(guard.reminders_command())
    helper = (mac_reminders.SCRIPTS / "_apple_reminders_remote.py").read_text()
    assert '"delete"' not in helper and "remove(" not in helper
    assert 'ALLOWED_WRITE_LISTS = ["OpenMates", "Personal Tasks"]' in helper
