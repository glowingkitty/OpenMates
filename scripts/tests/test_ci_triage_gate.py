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
    db.execute("CREATE TABLE jobs (id TEXT, owner TEXT, mode TEXT, specs TEXT, state TEXT, created REAL)")
    db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?)", jobs)
    db.commit()
    db.close()
    (tmp_path / "triage-gate.json").write_text('{"enabled": true}')
    return path


def job(job_id, state, created, spec="a.spec.ts", owner="s1", mode="e2e"):
    return (job_id, owner, mode, json.dumps([spec]), state, created)


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


def test_note_is_recorded_and_opens_the_gate_for_one_more_pair(tmp_path):
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
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", job("j3", "failure", 4))
    db.commit()
    db.close()
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")
    db = sqlite3.connect(queue)
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", job("j4", "failure", 5))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="failures j3 j4"):
        gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")


def test_gate_is_off_without_the_switch(tmp_path):
    queue = make_queue(tmp_path, [job("j1", "failure", 1), job("j2", "failure", 2)])
    (tmp_path / "triage-gate.json").unlink()
    gate.check(queue, "s1", "e2e", ["a.spec.ts"], "")
