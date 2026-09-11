"""Meeting regressions for real calendar boundaries and trustworthy coverage.

Fixtures contain no real task content. Reads use isolated transcripts and CI
receipts; no network, notifications, credentials or live tasks are involved.
Counts must preserve unknown data and distinguish retries from unique cases.
See docs/architecture/codex-orchestration.md.
"""

# contract-test-file: tooling
from datetime import datetime, timezone
import json
from scripts import codex_meeting as meeting


def write(path, rows):
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": ts,
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"text": text}],
                    },
                }
            )
            for ts, text in rows
        )
    )


def test_yesterday_uses_message_dates_and_deduplicates_forks(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a, [("2026-09-07T10:00:00Z", "Verification passed")])
    b.write_text(a.read_text())
    result = meeting.review_history(
        [
            {"id": "a", "path": str(a), "updatedAt": 9999999999},
            {"id": "b", "path": str(b), "forkedFromId": "a"},
        ],
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        "UTC",
    )
    assert result["review_day"] == "2026-09-07"
    assert len(result["tasks"]) == 1 and result["tasks"][0]["thread"] == "a"


def test_heartbeat_day_is_not_last_working_day_and_missing_history_is_visible(tmp_path):
    a = tmp_path / "a"
    write(
        a,
        [
            ("2026-09-06T10:00:00Z", "Fix verified"),
            ("2026-09-07T10:00:00Z", "AUTOMATED ORCHESTRATION CHECKPOINT"),
        ],
    )
    result = meeting.review_history(
        [{"id": "a", "path": str(a)}, {"id": "b", "path": str(tmp_path / "missing")}],
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        "UTC",
    )
    assert result["review_day"] == "2026-09-06" and result["coverage"] == "incomplete"


def test_calendar_uses_requested_timezone(tmp_path):
    a = tmp_path / "a"
    write(a, [("2026-09-08T01:00:00Z", "Yesterday in California")])
    result = meeting.review_history(
        [{"id": "a", "path": str(a)}],
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        "America/Los_Angeles",
    )
    assert result["review_day"] == "2026-09-07"


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


def test_today_keeps_running_and_finished_candidates_without_changing_yesterday(
    tmp_path,
):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(
        a,
        [
            ("2026-09-07T10:00:00Z", "Previous work"),
            ("2026-09-08T10:00:00Z", "Completed verification"),
        ],
    )
    write(b, [])
    result = meeting.review_history(
        [
            {"id": "a", "path": str(a), "status": {"type": "idle"}},
            {"id": "b", "path": str(b), "status": {"type": "active"}},
        ],
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        "UTC",
    )
    assert result["review_day"] == "2026-09-07"
    assert {t["thread"] for t in result["today_tasks"]} == {"a", "b"}
    assert (
        next(t for t in result["today_tasks"] if t["thread"] == "a")["last_message"][
            "excerpt"
        ]
        == "Completed verification"
    )


def test_research_requires_priorities_before_any_source_is_read(tmp_path):
    import pytest

    class NeverRead:
        def call(self, *args):
            raise AssertionError("Research happened before priorities")

    with pytest.raises(ValueError, match="priorities"):
        meeting.collect(tmp_path, datetime.now(timezone.utc), "UTC", NeverRead())


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
    from scripts import codex_orchestration, codex_rpc, _daily_meeting_helper as helper

    monkeypatch.setitem(sys.modules, "codex_meeting", meeting)
    monkeypatch.setitem(sys.modules, "codex_orchestration", codex_orchestration)
    monkeypatch.setitem(sys.modules, "codex_rpc", codex_rpc)
    monkeypatch.setattr(codex_orchestration, "canonical_root", lambda _: tmp_path)
    monkeypatch.setattr(
        codex_rpc,
        "CodexRPC",
        lambda: (_ for _ in ()).throw(AssertionError("Research started")),
    )
    data = helper.gather_all_data(str(tmp_path), "2026-09-07")
    assert data["needs_priorities"]
    assert "FIRST ask" in helper.build_meeting_prompt(data, "2026-09-08", "2026-09-07")


def test_meeting_prompt_keeps_large_inputs_in_private_receipt(monkeypatch, tmp_path):
    import re
    from scripts import _daily_meeting_helper as helper
    monkeypatch.setattr(helper, "TMP_DIR", tmp_path)
    data = {"meeting": {"history": {"coverage": "complete"}, "raw": "private" * 100000}, "_failures": []}
    prompt = helper.build_meeting_prompt(data, "2026-09-11", "2026-09-10")
    assert len(prompt) < 1500
    assert "privateprivate" not in prompt
    receipt = tmp_path / re.search(r"daily-meeting-[^\s]+\.json", prompt).group(0)
    assert json.loads(receipt.read_text()) == data
    assert receipt.stat().st_mode & 0o777 == 0o600
