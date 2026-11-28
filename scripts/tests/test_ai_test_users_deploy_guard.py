# contract-test-file: infrastructure
"""AI test-user production runs stay out of production updates (scripts/ai_test_users_deploy_guard.py)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_test_users_deploy_guard as guard  # noqa: E402 - script module next to the tests

NOW = datetime(2026, 11, 23, 12, 8, tzinfo=UTC)


def state(marker=None, main_at=None, starts=()):
    return guard.State(now=NOW, marker=marker, main_commit_at=main_at, api_start_logs=list(starts))


def test_clear_when_nothing_happens():
    assert guard.blocker(state(main_at=NOW - timedelta(days=2), starts=[NOW - timedelta(days=1)])) is None


def test_marker_blocks():
    assert "in progress" in guard.blocker(state(marker={"started_at": NOW.isoformat(), "reason": "PR 537"}))


def test_settling_after_api_start_blocks():
    # 23 Nov: the API started at 11:50 and its cutover closed every socket until 12:09.
    reason = guard.blocker(state(main_at=NOW - timedelta(hours=1, minutes=30), starts=[NOW - timedelta(minutes=13)]))
    assert "settle" in reason


def test_merged_release_not_live_yet_blocks():
    reason = guard.blocker(state(main_at=NOW - timedelta(minutes=20), starts=[NOW - timedelta(days=3)]))
    assert "not live" in reason


def test_old_main_commit_never_blocks_forever():
    assert guard.blocker(state(main_at=NOW - timedelta(hours=13), starts=[NOW - timedelta(days=3)])) is None


def test_overlap_marks_run_with_start_during_or_shortly_before():
    run_start, run_end = NOW - timedelta(minutes=3), NOW + timedelta(minutes=5)
    assert guard.overlap(run_start, run_end, state(starts=[NOW - timedelta(minutes=20)]))
    assert guard.overlap(run_start, run_end, state(starts=[NOW - timedelta(hours=2)])) is None


def test_stale_marker_is_ignored(tmp_path):
    path = tmp_path / "marker"
    path.write_text(json.dumps({"started_at": (NOW - timedelta(hours=5)).isoformat(), "reason": "x"}))
    assert guard.read_marker(path, NOW) is None
    path.write_text(json.dumps({"started_at": (NOW - timedelta(hours=1)).isoformat(), "reason": "x"}))
    assert guard.read_marker(path, NOW)["reason"] == "x"
