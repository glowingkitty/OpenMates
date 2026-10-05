# contract-test-file: infrastructure
"""Capacity worker failures stay bounded and private for a source-bound CI run."""

import json

from scripts import ci_run_tests
from scripts.ci_run_tests import retain_capacity_failure_rows


def test_private_failure_receipt_is_bounded_mode_0600_and_exclusive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ci_run_tests, "RESULTS", tmp_path)
    results = tmp_path / "results.jsonl"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    rows = [{"kind": "round", "user": 0, "number": 0}] + [
        {"kind": "failure", "phase": "version_send", "error_class": "Error",
         "source_location": "storage_capacity_version_adapter.mjs:73", "reason": "x" * 300}
        for _ in range(25)]
    results.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    assert retain_capacity_failure_rows(results, private) == 20
    destination = tmp_path / "ci-capacity-private" / "capacity-failure-rows.jsonl"
    saved = [json.loads(line) for line in destination.read_text().splitlines()]
    assert len(saved) == 20
    assert all(len(row["reason"]) == 200 and set(row) ==
               {"phase", "error_class", "source_location", "reason"} for row in saved)
    assert destination.stat().st_mode & 0o777 == 0o600
    try:
        retain_capacity_failure_rows(results, private)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Private diagnostic receipt must be exclusive")


def test_private_failure_receipt_absent_when_no_worker_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ci_run_tests, "RESULTS", tmp_path)
    results = tmp_path / "results.jsonl"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    results.write_text(json.dumps({"kind": "round", "user": 0, "number": 0}) + "\n")
    assert retain_capacity_failure_rows(results, private) == 0
    assert not (tmp_path / "ci-capacity-private").exists()
