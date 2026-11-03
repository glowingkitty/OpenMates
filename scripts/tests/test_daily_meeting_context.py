# contract-test-file: tooling
"""Daily meeting context collection, using only fixture data."""

from datetime import datetime, timedelta, timezone
import json
import os

from scripts import daily_meeting_context as brief


def _line(**row) -> str:
    return json.dumps(row)


def test_transcript_summary_keeps_human_prompts_and_final_replies_in_window(tmp_path):
    path = tmp_path / "abcdef12-session.jsonl"
    path.write_text("\n".join([
        _line(type="user", timestamp="2026-11-01T08:00:00Z", turnOrigin="human",
              message={"content": "too old"}),
        _line(type="user", timestamp="2026-11-02T09:00:00Z", turnOrigin="human",
              message={"content": "Fix the login bug, token sk-abcdefghijklmnopqrstuvwx, mail me@example.com"}),
        _line(type="user", timestamp="2026-11-02T09:01:00Z", turnOrigin="human",
              message={"content": "<system-reminder>injected</system-reminder>"}),
        _line(type="user", timestamp="2026-11-02T09:02:00Z",
              message={"content": [{"type": "tool_result", "content": "tool output"}]}),
        _line(type="assistant", timestamp="2026-11-02T09:05:00Z",
              message={"content": [{"type": "text", "text": "Fixed and deployed."}]}),
        _line(type="assistant", timestamp="2026-11-02T09:06:00Z", isSidechain=True,
              message={"content": [{"type": "text", "text": "subagent noise"}]}),
        "not json",
    ]))
    since = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    summary = brief.summarize_transcript(path, since)
    assert summary["user_prompts"] == ["Fix the login bug, token <redacted>, mail <email>"]
    assert summary["final_reply"] == "Fixed and deployed."
    assert summary["session"] == "abcdef12-session"


def test_transcript_without_human_prompts_in_window_is_skipped(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(_line(type="assistant", timestamp="2026-11-02T09:05:00Z",
                          message={"content": [{"type": "text", "text": "hi"}]}))
    assert brief.summarize_transcript(path, datetime(2026, 11, 1, tzinfo=timezone.utc)) is None


def test_monday_window_reaches_back_to_friday_meeting():
    monday = datetime(2026, 11, 2, 9, 20, tzinfo=timezone.utc)
    since = brief.default_since(monday)
    assert (since.date().isoformat(), since.hour, since.minute) == ("2026-10-30", 10, 0)


def test_window_starts_at_previous_days_collection_not_todays_rerun():
    now = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
    state = {"collected": {"2026-11-03": "2026-11-03T09:40:00+00:00",
                           "2026-11-04": "2026-11-04T09:10:00+00:00"}}
    assert brief.window_start(state, now) == datetime(2026, 11, 3, 9, 40, tzinfo=timezone.utc)
    assert brief.window_start({}, now) == brief.default_since(now)


def test_previous_meeting_reads_latest_earlier_record(tmp_path):
    folder = tmp_path / "logs/daily-meetings"
    folder.mkdir(parents=True)
    record = {"meetings": {"t": {"priorities": "ship signup", "proposal": "p", "answers": [{"text": "yes"}]}}}
    (folder / "2026-11-02.json").write_text(json.dumps(record))
    (folder / "2026-11-04.json").write_text(json.dumps({"meetings": {"t": {"priorities": "today"}}}))
    previous = brief.previous_meeting(tmp_path, "2026-11-04")
    assert previous["date"] == "2026-11-02"
    assert previous["meetings"][0]["priorities"] == "ship signup"
    assert previous["meetings"][0]["answers"] == ["yes"]


def test_task_summary_reports_status_changes_against_previous_snapshot():
    previous = [{"id": "TASK-1", "title": "a", "status": "in_progress"},
                {"id": "TASK-2", "title": "b", "status": "todo"}]
    current = [{"id": "TASK-1", "title": "a", "status": "done", "priority": "none", "blocked": ""},
               {"id": "TASK-2", "title": "b", "status": "todo", "priority": "none", "blocked": ""},
               {"id": "TASK-3", "title": "c", "status": "blocked", "priority": "high", "blocked": "user"}]
    summary = brief.task_summary(current, previous)
    assert summary["counts"] == {"done": 1, "todo": 1, "blocked": 1}
    assert summary["done_since_last_meeting"] == [
        {"id": "TASK-1", "title": "a", "from": "in_progress", "to": "done"}]
    assert summary["changed_since_last_meeting"] == [
        {"id": "TASK-3", "title": "c", "from": "new", "to": "blocked"}]
    assert brief.task_summary(current, None)["changed_since_last_meeting"] == []


def test_nightly_overview_counts_consecutive_empty_runs_and_last_results(tmp_path):
    runs = tmp_path / "test-results/daily-runs"
    runs.mkdir(parents=True)
    receipts = tmp_path / "test-results/ci-runs"
    for job, spec, code in (("job-pass", "a.spec.ts", 0), ("job-fail", "b.spec.ts", 1)):
        (receipts / job).mkdir(parents=True)
        (receipts / job / "receipt.json").write_text(json.dumps({
            "state": "success" if code == 0 else "failure",
            "report": {"results": [{"spec": spec, "exit_code": code,
                                    "failed_tests": ["login works"] if code else None}]}}))
    manifests = [
        {"created": 1, "run_date": "2026-10-04", "jobs": ["job-pass", "job-fail"], "status": "queued",
         "held_specs": ["c.spec.ts"], "held_reasons": {"c.spec.ts": "needs live AI"}},
        {"created": 2, "run_date": "2026-10-05", "jobs": [], "status": "blocked",
         "selection_error": "RuntimeError: Unclassified AI spec"},
        {"created": 3, "run_date": "2026-10-06", "jobs": [], "status": "blocked",
         "selection_error": "RuntimeError: Unclassified AI spec"},
    ]
    for index, manifest in enumerate(manifests):
        (runs / f"{index}.json").write_text(json.dumps(manifest))
    result = brief.nightly(tmp_path, datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert result["nights_without_any_test_jobs"] == 2
    last = result["last_nightly_run_with_tests"]
    assert (last["date"], last["passed_count"], last["failed_count"], last["not_run_count"]) == (
        "2026-10-04", 1, 1, 1)
    assert last["failed"] == [{"test": "b.spec.ts", "reason": "login works"}]
    assert last["not_run"] == [{"test": "c.spec.ts", "reason": "needs live AI"}]


def test_in_progress_tasks_report_whether_their_chat_is_active():
    tasks = [
        {"id": "T-1", "title": "a", "status": "in_progress", "chat": "claude:live"},
        {"id": "T-2", "title": "b", "status": "in_progress", "chat": "claude:quiet"},
        {"id": "T-3", "title": "c", "status": "in_progress", "chat": "codex:old"},
        {"id": "T-4", "title": "d", "status": "in_progress", "chat": ""},
        {"id": "T-5", "title": "e", "status": "todo", "chat": ""},
    ]
    summary = brief.task_summary(tasks, None, {"live"})
    assert summary["in_progress_by_chat_state"] == {
        "active": 1, "idle": 1, "codex_legacy": 1, "no_chat": 1}
    assert [t["chat_state"] for t in summary["open"]["in_progress"]] == [
        "active", "idle", "codex_legacy", "no_chat"]


def test_usage_pace_projects_when_the_weekly_limit_runs_out():
    resets = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
    now = resets - timedelta(days=5)  # 2 of 7 days elapsed
    pace = brief.usage_pace(60.0, resets, now)
    assert pace["week_elapsed_percent"] == 29
    # week began Fri 30 Oct 10:00 UTC; 60% after 2 days reaches 100% after 3.33 days
    assert pace["runs_out"] == "Mon 02 Nov 19:00"
    assert "runs_out" not in brief.usage_pace(10.0, resets, now)


def test_parked_code_at_risk_lists_only_referenced_archives_near_purge(tmp_path):
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    old = tmp_path / "agent-33bc-aa-bb.tar.gz"
    other = tmp_path / "agent-9999-aa-bb.tar.gz"
    for path in (old, other):
        path.write_bytes(b"")
        stamp = (now - timedelta(days=10)).timestamp()
        os.utime(path, (stamp, stamp))
    rows = brief.parked_code_at_risk("TASK-4971: recover agent-33bc first", now, tmp_path)
    assert [r["worktree"] for r in rows] == ["agent-33bc"]
    assert rows[0]["purged"] == "Sat 07 Nov"
