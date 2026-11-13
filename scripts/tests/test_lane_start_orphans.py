# contract-test-file: tooling
"""Orphan session cleanup, lane_start rollback/retry and merge-race contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts import lane_start
from scripts.sessions_orphans import find_orphans, remove_orphans
from scripts.sessions_state_merge import merge_concurrent_state, remember_loaded

NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
OLD = "2026-11-08T10:00:00Z"


def sessions_data() -> dict:
    return {"sessions": {
        "orph": {"last_active": OLD, "modified_files": []},
        "fresh": {"last_active": "2026-11-08T11:59:59Z"},
        "wt": {"last_active": OLD, "worktree": {"path": "/x/wt"}},
        "dirty": {"last_active": OLD, "modified_files": ["a.py"]},
        "writing": {"last_active": OLD, "writing": {"file": "a.py"}},
    }}


def test_only_idle_worktreeless_clean_sessions_are_orphans():
    assert find_orphans(sessions_data(), now=NOW) == ["orph"]


def test_remove_orphans_keeps_sessions_with_work():
    data = sessions_data()
    assert remove_orphans(data, now=NOW, min_age_seconds=0) == ["orph", "fresh"]
    assert set(data["sessions"]) == {"wt", "dirty", "writing"}


def test_session_filter_never_removes_other_or_dirty_sessions():
    data = sessions_data()
    assert remove_orphans(data, session_id="dirty", now=NOW, min_age_seconds=0) == []
    assert "dirty" in data["sessions"]


def test_merge_keeps_worktree_registered_by_concurrent_writer():
    disk = {"sessions": {"s": {"worktree": {"path": "/x"}, "lane_edit": True}}}
    stale = remember_loaded({"sessions": {"s": {"task": "t"}}})
    merge_concurrent_state(stale, disk)
    assert stale["sessions"]["s"]["worktree"] == {"path": "/x"}
    assert stale["sessions"]["s"]["lane_edit"] is True


def run_script(responses):
    calls = []

    def run(args, env):
        calls.append(args)
        result = responses(args, len(calls))
        if isinstance(result, Exception):
            raise result
        return result

    return run, calls


def test_lane_start_rolls_back_and_retries():
    def responses(args, n):
        if args[0] == "start":
            return "Session abcd (created)\nWorkspace: /w/abcd\n"
        if args[0] == "lane-open" and n == 2:
            return lane_start.LaneStartError("no worktree")
        return ""

    run, calls = run_script(responses)
    assert lane_start.start_lane("feature", "t", run=run, sleep=lambda _s: None) == ("abcd", "/w/abcd")
    assert ["cleanup-orphans", "--session", "abcd", "--min-age-seconds", "0"] in calls


def test_lane_start_gives_clear_error_after_bounded_attempts():
    run, calls = run_script(lambda args, n: lane_start.LaneStartError("boom"))
    with pytest.raises(SystemExit, match="after 3 attempts.*boom"):
        lane_start.start_lane("feature", "t", run=run, sleep=lambda _s: None)
    assert len(calls) == 3
