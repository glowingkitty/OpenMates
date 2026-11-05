"""Meeting regressions for recorded decisions and trustworthy CI coverage.

Fixtures contain no real task content. Reads use isolated CI receipts and
meeting records; no network, notifications, credentials or live tasks are
involved. Counts must preserve unknown data and distinguish retries from unique
cases. See .claude/skills/daily-meeting-and-orchestration/SKILL.md.
"""

# contract-test-file: tooling
from datetime import datetime, timezone
import json
from scripts import daily_meeting as meeting


def test_missing_or_wrong_commit_receipt_is_unknown(tmp_path):
    job = {"source": "abc", "run_id": 1, "mode": "e2e"}
    assert meeting.case_counts(tmp_path, job) is None
    (tmp_path / "receipt.json").write_text(
        json.dumps({"source_commit": "other", "run_id": 1})
    )
    assert meeting.case_counts(tmp_path, job) is None


def test_real_case_counts_not_batches(tmp_path):
    (tmp_path / "receipt.json").write_text(
        json.dumps(
            {
                "source_commit": "abc",
                "run_id": 1,
                "report": {
                    "results": [
                        {
                            "stats": {
                                "expected": 500,
                                "unexpected": 2,
                                "skipped": 3,
                                "flaky": 1,
                            }
                        }
                    ]
                },
            }
        )
    )
    count = meeting.case_counts(tmp_path, {"source": "abc", "run_id": 1, "mode": "e2e"})
    assert count["executed"] == 503 and count["discovered"] == 506


def test_reruns_keep_latest_counts_and_partial_overlap_never_sums(
    monkeypatch, tmp_path
):
    base = {
        "owner": "daily",
        "source": "a" * 40,
        "mode": "e2e",
        "run_id": 1,
        "state": "failure",
        "proof_profile": "",
    }
    jobs = [
        {**base, "id": "1", "specs": '["chat.spec.ts"]'},
        {**base, "id": "2", "specs": '["chat.spec.ts"]'},
        {**base, "id": "3", "specs": '["chat.spec.ts","signup.spec.ts"]'},
    ]
    monkeypatch.setattr(meeting, "read_jobs", lambda *a: (jobs, None))
    monkeypatch.setattr(
        meeting.subprocess,
        "check_output",
        lambda *a, **k: "tests/chat.spec.ts\ntests/signup.spec.ts\n",
    )
    monkeypatch.setattr(
        meeting, "case_counts", lambda *a: {"passed": 10, "executed": 10}
    )
    result = meeting.nightly_snapshot(tmp_path, 0, 100)["sources"][0]
    assert result["case_counts"] is None and result["overlapping_reruns"]
    assert result["rerun_batches"] == 1 and result["selected_unique_specs"] == 2
    assert result["batches"]["failure"] == 3


def test_research_requires_priorities_before_any_source_is_read(tmp_path, monkeypatch):
    import pytest

    def never_read(*args):
        raise AssertionError("Research happened before priorities")

    monkeypatch.setattr(meeting, "openmates_tasks", never_read)
    monkeypatch.setattr(meeting, "commits", never_read)
    with pytest.raises(ValueError, match="priorities"):
        meeting.collect(tmp_path, datetime.now(timezone.utc), "UTC")


def test_meeting_thread_accepts_claude_session_uuid_as_plain_id(tmp_path):
    session = "6f1c2b9e-3d4a-4c1e-9a2b-1234567890ab"
    record = meeting.save_meeting_step(
        tmp_path, "2026-09-08", session, "priorities", "Ship signup", "human-1", "UTC"
    )
    assert record["meeting_thread"] == session
    assert "link" not in record
    assert meeting.load_meeting(tmp_path, "2026-09-08", session)["priorities"] == "Ship signup"


def test_collect_reads_tasks_and_calendar_commits_without_agent_history(tmp_path, monkeypatch):
    days = []
    monkeypatch.setattr(meeting, "openmates_tasks", lambda root: {"coverage": "complete CLI snapshot"})
    monkeypatch.setattr(meeting, "commits", lambda root, day, zone: days.append(day) or [])
    monkeypatch.setattr(meeting, "nightly_snapshot", lambda *a: {})
    result = meeting.collect(
        tmp_path, datetime(2026, 9, 8, 1, tzinfo=timezone.utc), "America/Los_Angeles",
        {"priorities": "Focus"},
    )
    assert result["review_day"] == "2026-09-06"
    assert days == ["2026-09-06", "2026-09-07"]
    assert "history" not in result


def test_daily_records_preserve_history_without_forcing_question_rounds(tmp_path):

    tid = "00000000-0000-0000-0000-000000000001"
    first = meeting.save_meeting_step(
        tmp_path, "2026-09-07", tid, "priorities", "Ship signup", "human-1", "UTC"
    )
    meeting.save_meeting_step(
        tmp_path, "2026-09-08", tid, "priorities", "Finish billing", "human-2", "UTC"
    )
    assert (
        meeting.previous_priorities(tmp_path, "2026-09-08")["calendar_yesterday"][
            "meetings"
        ][tid]["priorities"]
        == "Ship signup"
    )
    proposal = meeting.save_meeting_step(
        tmp_path, "2026-09-08", tid, "proposal", "Today focus", "", "UTC"
    )
    assert proposal["phase"] == "proposed" and proposal["answers"] == []
    for i in range(4):
        meeting.save_meeting_step(
            tmp_path, "2026-09-08", tid, "answer", f"Answer {i}", f"reply-{i}", "UTC"
        )
    meeting.save_meeting_step(
        tmp_path, "2026-09-08", tid, "answer", "Answer 3", "reply-3", "UTC"
    )
    record = meeting.save_meeting_step(
        tmp_path, "2026-09-08", tid, "proposal", "Today focus", "", "UTC"
    )
    assert len(record["answers"]) == 4 and record["phase"] == "proposed"
    assert first["phase"] == "research"


def test_cli_tasks_require_complete_global_response(tmp_path):
    calls = []

    def read(root, args):
        calls.append(args)
        return {
            "tasks": [{"task_id": str(i), "status": "todo"} for i in range(185)],
            "complete": True,
        }

    result = meeting.openmates_tasks(tmp_path, read)
    assert calls == [["list"]]
    assert len(result["tasks"]) == 185
    assert result["coverage"] == "complete CLI snapshot"
    incomplete = meeting.openmates_tasks(tmp_path, lambda *a: {"tasks": []})
    assert incomplete["coverage"] == "incomplete"
    assert incomplete["errors"]


def test_priority_revisions_and_legacy_decisions_are_not_lost(tmp_path):
    tid = "00000000-0000-0000-0000-000000000001"
    meeting.save_meeting_step(
        tmp_path, "2026-09-07", tid, "priorities", "Old focus", "first", "UTC"
    )
    meeting.save_meeting_step(
        tmp_path, "2026-09-07", tid, "priorities", "Corrected focus", "second", "UTC"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/.daily-meeting-state.json").write_text(
        json.dumps({"date": "2026-09-06", "priorities": ["Earlier focus"]})
    )
    previous = meeting.previous_priorities(tmp_path, "2026-09-08")
    assert previous["calendar_yesterday"]["revisions"][0]["priorities"] == "Old focus"
    assert (
        previous["calendar_yesterday"]["meetings"][tid]["priorities"]
        == "Corrected focus"
    )
    assert previous["legacy_state"]["priorities"] == ["Earlier focus"]
    assert meeting.meeting_path(tmp_path, "2026-09-07").stat().st_mode & 0o777 == 0o600


def test_legacy_entry_point_asks_priorities_without_research(monkeypatch, tmp_path):
    import sys
    from scripts import agent_identity, agent_state, _daily_meeting_helper as helper

    monkeypatch.setitem(sys.modules, "daily_meeting", meeting)
    monkeypatch.setitem(sys.modules, "agent_state", agent_state)
    monkeypatch.setitem(sys.modules, "agent_identity", agent_identity)
    monkeypatch.setattr(agent_state, "canonical_root", lambda _: tmp_path)
    monkeypatch.setattr(
        meeting,
        "collect",
        lambda *a: (_ for _ in ()).throw(AssertionError("Research started")),
    )
    data = helper.gather_all_data(str(tmp_path), "2026-09-07")
    assert data["needs_priorities"]
    assert "FIRST ask" in helper.build_meeting_prompt(data, "2026-09-08", "2026-09-07")


def test_meeting_prompt_keeps_large_inputs_in_private_receipt(monkeypatch, tmp_path):
    import re
    from scripts import _daily_meeting_helper as helper
    monkeypatch.setattr(helper, "TMP_DIR", tmp_path)
    data = {"meeting": {"openmates_tasks": {"coverage": "complete CLI snapshot"}, "raw": "private" * 100000}, "_failures": []}
    prompt = helper.build_meeting_prompt(data, "2026-09-11", "2026-09-10")
    assert len(prompt) < 1500
    assert "privateprivate" not in prompt
    receipt = tmp_path / re.search(r"daily-meeting-[^\s]+\.json", prompt).group(0)
    assert json.loads(receipt.read_text()) == data
    assert receipt.stat().st_mode & 0o777 == 0o600
