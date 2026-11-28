#!/usr/bin/env python3
# contract-test-file: tooling
"""Triage gate of scripts/ci_triage_gate.py (tooling test)."""

import json
import sqlite3

import pytest

from scripts import ci_triage_gate as gate


def make_queue(tmp_path, jobs):
    path = tmp_path / "queue.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE jobs (id TEXT, owner TEXT, mode TEXT, specs TEXT, state TEXT, created REAL, error TEXT)")
    db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)", jobs)
    db.commit()
    db.close()
    (tmp_path / "triage-gate.json").write_text('{"enabled": true}')
    return path


def job(job_id, state, created, spec="a.spec.ts", owner="s1", mode="e2e", error="Expected the ready row"):
    return (job_id, owner, mode, json.dumps([spec]), state, created, error)


def test_two_failures_in_a_row_require_a_diagnosis(tmp_path):
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2)])
    with pytest.raises(ValueError) as refused:
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")
    assert "ci_coordinator.py failures j1 j2" in str(refused.value)
    assert "--after-triage" in str(refused.value)


def test_success_other_spec_other_chat_and_daily_do_not_count(tmp_path):
    queue = make_queue(tmp_path, [
        job("j1", "failure", 1), job("j2", "success", 2), job("j3", "failure", 3),
        job("k1", "failure", 4, spec="b.spec.ts"), job("k2", "failure", 5, spec="b.spec.ts"),
        job("o1", "failure", 6, owner="s2"), job("o2", "failure", 7, owner="s2"),
        job("d1", "failure", 8, owner="daily"), job("d2", "failure", 9, owner="daily"),
        job("c1", "cancelled", 10),
    ])
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")
    gate.check(queue, "s1", "pytest", ["b.spec.ts"], "")
    gate.check(queue, "daily", "e2e", ["a.spec.ts"], "")
    with pytest.raises(ValueError):
        gate.check(queue, "s2", "e2e", ["a.spec.ts"], "")


def test_note_is_recorded_and_opens_the_gate_for_one_more_attempt(tmp_path):
    jobs = [job("j1", "failure", 1), job("j2", "failure", 2)]
    queue = make_queue(tmp_path, jobs)
    with pytest.raises(ValueError, match="at least"):
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "flaky")
    cause = "The chat list renders before sync finishes; this run waits for the sync marker."
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], cause, clock=lambda: 3)
    note = json.loads(gate.notes_path(queue).read_text().splitlines()[0])
    assert note["cause"] == cause and note["failed_jobs"] == {"a.spec.ts": ["j1", "j2"]}
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")

    db = sqlite3.connect(queue)
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)", job("j3", "failure", 4))
    db.commit()
    db.close()
    # Third failure in a row: the loop brake (owner, 23 Nov) replaces a second pair of attempts.
    with pytest.raises(ValueError, match="Loop brake"):
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")


def test_gate_is_off_without_the_switch(tmp_path):
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2)])
    (tmp_path / "triage-gate.json").unlink()
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")


def test_loop_brake_after_three_failures_a_triage_note_does_not_open_it(tmp_path):
    """Owner decision 23 Nov (receipt 5096e6d1abf8b55f): third failure in a row stops the chat."""
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2)])
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "the selector waited for a stale toast; now waits for the row",
               clock=lambda: 3)
    db = sqlite3.connect(queue)
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)", job("j3", "failure", 4))
    db.commit()
    db.close()
    with pytest.raises(ValueError) as refused:
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "another long enough cause for the next try")
    text = str(refused.value)
    assert "Loop brake" in text and "agent_question.py ask" in text and "failures j1 j2 j3" in text
    assert "--after-owner-answer" in text


def test_only_a_verified_owner_answer_opens_the_brake_and_restarts_the_count(tmp_path):
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2), job("j3", "failure", 3)])
    with pytest.raises(ValueError) as refused:
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "", owner_answer="abc", chat_id="c1",
                   verify=lambda receipt, chat: (False, "issued for another chat"))
    assert "not the owner's answer" in str(refused.value)
    seen = []
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "", owner_answer="abc", chat_id="c1", clock=lambda: 10,
               verify=lambda receipt, chat: seen.append((receipt, chat)) or (True, "VERIFIED"))
    assert seen == [("abc", "c1")]
    notes = [json.loads(line) for line in (tmp_path / "triage-notes.jsonl").read_text().splitlines()]
    assert notes[-1]["kind"] == "owner" and notes[-1]["receipt"] == "abc"
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")  # after the answer: no brake and no triage due


def test_brake_is_off_with_the_gate_switch_off(tmp_path):
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2), job("j3", "failure", 3)])
    (tmp_path / "triage-gate.json").write_text('{"enabled": false}')
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")


def test_different_diagnostics_break_the_streak(tmp_path):
    queue = make_queue(tmp_path, [
        job("j1", "failure", 1), job("j2", "failure", 2, error="Worker did not start"),
        job("j3", "failure", 3), job("j4", "failure", 4),
    ])
    assert gate.braked_targets(queue, "s1", "e2e", ["a.spec.ts"]) == {}


def test_identical_proof_failures_use_report_evidence(tmp_path):
    path = tmp_path / "logs/ci-coordinator"
    path.mkdir(parents=True)
    queue = make_queue(path, [
        job(key, "failure", n, mode="artifact", error=None) for n, key in enumerate(("j1", "j2", "j3"), 1)
    ])
    for n, key in enumerate(("j1", "j2", "j3"), 1):
        folder = tmp_path / "test-results/ci-runs" / key
        report = folder / "subject/test-results"
        report.mkdir(parents=True)
        (folder / "receipt.json").write_text(json.dumps({
            "mode": "artifact", "state": "failure", "directory": str(folder),
        }))
        (report / "ci-spec-proof.json").write_text(json.dumps({
            "suites": [{"specs": [{"title": "opens preview", "tests": [{
                "status": "unexpected", "results": [{"error": {"message": f"Preview timed out in {n} ms"}}],
            }]}]}],
        }))
    assert gate.braked_targets(queue, "s1", "artifact", ["a.spec.ts"]) == {"a.spec.ts": ["j1", "j2", "j3"]}
