# contract-test-file: tooling
"""The narrow recovery case selection preserves file fixtures and honest CI scope."""

import json
import re
import sys

import pytest

from scripts import ci_coordinator, ci_environment, ci_results

SOURCE = "a" * 40
SPEC = "cli-recovery-discovery.spec.ts"
TITLE = ci_coordinator.RECOVERY_FAILURE_CASE_TITLE


def test_default_and_filtered_jobs_have_distinct_identity_and_same_preparation(tmp_path, monkeypatch):
    queue = ci_coordinator.Queue(tmp_path / "queue.sqlite3")
    monkeypatch.setattr(ci_coordinator, "source_coverage_manifest",
                        lambda *_args: {"groups": {"uploads": {"specs": []}}})
    monkeypatch.setattr(ci_coordinator, "harness_commit", lambda _root: "b" * 40)
    base = dict(source_root=tmp_path, prepared_builds=True, supersede=False)
    full = ci_coordinator.enqueue_submission(queue, "owner", SOURCE, [SPEC], "e2e", **base)[0]
    narrow = ci_coordinator.enqueue_submission(
        queue, "owner", SOURCE, [SPEC], "e2e", case_title=TITLE, **base,
    )[0]
    assert full["case_title"] == ""
    assert narrow["case_title"] == TITLE
    assert full["id"] != narrow["id"]
    assert full["specs"] == narrow["specs"] == json.dumps([SPEC], separators=(",", ":"))
    assert full["preparation_key"] == narrow["preparation_key"]
    assert full["preparation_id"] == narrow["preparation_id"]
    with pytest.raises(ValueError, match="Case filter requires"):
        queue.enqueue("owner", SOURCE, ["other.spec.ts"], "e2e", case_title=TITLE)
    with pytest.raises(ValueError, match="Case filter requires"):
        queue.enqueue("owner", SOURCE, [SPEC], "e2e", case_title=".*")
    with pytest.raises(ValueError, match="Case filter requires"):
        ci_coordinator.enqueue_submission(queue, "owner", SOURCE, [SPEC], "e2e",
                                          case_title=".*", **base)
    assert queue.supersede_pending(narrow) == 0
    assert queue.status(full["id"])[0]["state"] == "queued"


def test_dispatch_transports_title_as_structured_input(tmp_path, monkeypatch):
    requests = []
    github = object.__new__(ci_coordinator.GitHub)
    github.repo = "openmates/example"
    monkeypatch.setattr(github, "request", lambda route, body: requests.append((route, body)))
    github.dispatch({"source": SOURCE, "specs": json.dumps([SPEC]), "mode": "e2e",
                     "token": "ci-test", "case_title": TITLE})
    inputs = requests[0][1]["inputs"]
    assert inputs["case_title"] == TITLE
    assert json.loads(inputs["specs_json"]) == [SPEC]


def test_playwright_receives_literal_exact_case_and_stats_are_partial(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests

    assert ci_run_tests.playwright_case_args("") == []
    assert ci_run_tests.playwright_case_args(TITLE) == ["--grep", re.escape(TITLE) + "$"]
    pattern = ci_run_tests.playwright_case_args(TITLE)[1]
    assert re.search(pattern, f"{SPEC} {TITLE}")
    assert not re.search(pattern, f"{SPEC} {TITLE} unrelated")
    with pytest.raises(ValueError, match="Unknown recovery case"):
        ci_run_tests.playwright_case_args(".*")
    assert ci_run_tests.case_coverage_complete(7, 0, "")
    assert ci_run_tests.case_coverage_complete(1, 0, TITLE, TITLE)
    assert not ci_run_tests.case_coverage_complete(0, 0, TITLE, TITLE)
    assert not ci_run_tests.case_coverage_complete(2, 0, TITLE, TITLE)
    assert not ci_run_tests.case_coverage_complete(1, 1, TITLE, TITLE)
    assert not ci_run_tests.case_coverage_complete(1, 0, TITLE, "prefix " + TITLE)

    def playwright_report(actual_title):
        return {"stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0},
                "suites": [{"title": SPEC, "specs": [{"title": actual_title,
                            "tests": [{"status": "expected", "results": [{"status": "passed"}]}]}]}]}

    exact = ci_run_tests.reported_playwright_case_title(playwright_report(TITLE))
    wrong = ci_run_tests.reported_playwright_case_title(playwright_report("prefix " + TITLE))
    assert exact == TITLE and wrong == "prefix " + TITLE
    assert ci_run_tests.case_coverage_complete(1, 0, TITLE, exact)
    assert not ci_run_tests.case_coverage_complete(1, 0, TITLE, wrong)


def test_native_receipt_cannot_claim_full_spec_for_filtered_case():
    result = {"spec": SPEC, "case_title": TITLE, "coverage_scope": "single-case",
              "coverage_complete": True, "exit_code": 0,
              "reported_case_title": TITLE,
              "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0}}
    filtered = {"case_title": TITLE}
    full = {"case_title": ""}
    report = {"results": [result], "case_title": TITLE, "coverage_scope": "single-case"}
    assert ci_results.valid_e2e_case_coverage(report, filtered)
    assert not ci_results.valid_e2e_case_coverage(report, full)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "coverage_scope": "full-spec"}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "coverage_complete": False}]}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "stats": {**result["stats"], "expected": 2}}]}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "reported_case_title": "prefix " + TITLE}]}, filtered)
    assert ci_results.valid_e2e_case_coverage(
        {"results": [{"spec": SPEC}], "coverage_scope": "full-spec"}, full)
