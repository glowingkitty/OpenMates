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
