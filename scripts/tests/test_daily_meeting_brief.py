# contract-test-file: tooling
"""Daily meeting brief evidence collection, using only fixture data."""

from datetime import datetime, timezone
import json
from pathlib import Path

from scripts import daily_meeting_brief as brief


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
    assert summary["final_replies"] == ["Fixed and deployed."]
    assert summary["session"] == "abcdef12"


def test_transcript_without_human_prompts_in_window_is_skipped(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(_line(type="assistant", timestamp="2026-11-02T09:05:00Z",
                          message={"content": [{"type": "text", "text": "hi"}]}))
    assert brief.summarize_transcript(path, datetime(2026, 11, 1, tzinfo=timezone.utc)) is None


def test_monday_window_reaches_back_to_friday_morning():
    monday = datetime(2026, 11, 2, 7, 45, tzinfo=timezone.utc)
    since = brief.default_since(monday)
    assert (since.date().isoformat(), since.hour, since.minute) == ("2026-10-30", 8, 45)


def test_task_summary_reports_status_changes_against_previous_snapshot():
    previous = [{"id": "TASK-1", "title": "a", "status": "in_progress"},
                {"id": "TASK-2", "title": "b", "status": "todo"}]
    current = [{"id": "TASK-1", "title": "a", "status": "done", "priority": "none", "blocked": ""},
               {"id": "TASK-2", "title": "b", "status": "todo", "priority": "none", "blocked": ""},
               {"id": "TASK-3", "title": "c", "status": "blocked", "priority": "high", "blocked": "user"}]
    summary = brief.task_summary(current, previous)
    assert summary["counts"] == {"done": 1, "todo": 1, "blocked": 1}
    assert summary["changed_since_last_meeting"] == [
        {"id": "TASK-1", "title": "a", "from": "in_progress", "to": "done"},
        {"id": "TASK-3", "title": "c", "from": "new", "to": "blocked"},
    ]
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


def test_headline_uses_summary_section():
    text = "# Brief\n\n## 1. Instructions\nx\n\n## 2. Summary\n- one\n- two\n\n## 3. Next\ny\n"
    headline = brief.headline_for(text, "2026-11-02")
    assert "Daily meeting brief ready" in headline
    assert headline.endswith("- one\n- two")


def test_scheduled_mode_only_runs_in_berlin_eight_oclock_hour(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(brief, "collect", lambda *a, **k: calls.append(a) or ({}, None))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 6, 45, tzinfo=timezone.utc)  # 07:45 Berlin (CET)

    monkeypatch.setattr(brief, "datetime", Clock)
    assert brief.main(["run", "--scheduled", "--out-dir", str(tmp_path), "--root", str(tmp_path)]) == 0
    assert calls == []
    assert not list(Path(tmp_path).glob("*-brief.md"))
