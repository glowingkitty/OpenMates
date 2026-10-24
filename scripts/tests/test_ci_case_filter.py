# contract-test-file: tooling
"""Approved exact case selection preserves file fixtures and honest CI scope."""

import json
import re
import sys

import pytest

from scripts import ci_coordinator, ci_environment, ci_results

SOURCE = "a" * 40
SPEC = "cli-recovery-discovery.spec.ts"
TITLE = ci_coordinator.RECOVERY_FAILURE_CASE_TITLE


@pytest.mark.parametrize(("spec", "title"), sorted(ci_coordinator.APPROVED_RECOVERY_CASES))
def test_default_and_filtered_jobs_have_distinct_identity_and_same_preparation(tmp_path, monkeypatch, spec, title):
    queue = ci_coordinator.Queue(tmp_path / "queue.sqlite3")
    monkeypatch.setattr(ci_coordinator, "source_coverage_manifest",
                        lambda *_args: {"groups": {"uploads": {"specs": []}}})
    monkeypatch.setattr(ci_coordinator, "harness_commit", lambda _root: "b" * 40)
    base = dict(source_root=tmp_path, prepared_builds=True, supersede=False)
    full = ci_coordinator.enqueue_submission(queue, "owner", SOURCE, [spec], "e2e", **base)[0]
    narrow = ci_coordinator.enqueue_submission(
        queue, "owner", SOURCE, [spec], "e2e", case_title=title, **base,
    )[0]
    assert full["case_title"] == ""
    assert narrow["case_title"] == title
    assert full["id"] != narrow["id"]
    assert full["specs"] == narrow["specs"] == json.dumps([spec], separators=(",", ":"))
    assert full["preparation_key"] == narrow["preparation_key"]
    assert full["preparation_id"] == narrow["preparation_id"]
    with pytest.raises(ValueError, match="Case filter requires"):
        queue.enqueue("owner", SOURCE, ["other.spec.ts"], "e2e", case_title=title)
    with pytest.raises(ValueError, match="Case filter requires"):
        queue.enqueue("owner", SOURCE, [spec], "e2e", case_title=".*")
    with pytest.raises(ValueError, match="Case filter requires"):
        ci_coordinator.enqueue_submission(queue, "owner", SOURCE, [spec], "e2e",
                                          case_title=".*", **base)
    assert queue.supersede_pending(narrow) == 0
    assert queue.status(full["id"])[0]["state"] == "queued"


@pytest.mark.parametrize(("spec", "title"), sorted(ci_coordinator.APPROVED_RECOVERY_CASES))
def test_dispatch_transports_title_as_structured_input(tmp_path, monkeypatch, spec, title):
    requests = []
    github = object.__new__(ci_coordinator.GitHub)
    github.repo = "openmates/example"
    monkeypatch.setattr(github, "request", lambda route, body: requests.append((route, body)))
    github.dispatch({"source": SOURCE, "specs": json.dumps([spec]), "mode": "e2e",
                     "token": "ci-test", "case_title": title})
    inputs = requests[0][1]["inputs"]
    assert inputs["case_title"] == title
    assert json.loads(inputs["specs_json"]) == [spec]


@pytest.mark.parametrize(("spec", "title"), sorted(ci_coordinator.APPROVED_RECOVERY_CASES))
def test_playwright_receives_literal_exact_case_and_stats_are_partial(monkeypatch, spec, title):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests

    assert ci_run_tests.APPROVED_RECOVERY_CASES == ci_coordinator.APPROVED_RECOVERY_CASES

    assert ci_run_tests.playwright_case_args("") == []
    assert ci_run_tests.playwright_case_args(title) == ["--grep", re.escape(title) + "$"]
    pattern = ci_run_tests.playwright_case_args(title)[1]
    assert re.search(pattern, f"{spec} {title}")
    assert not re.search(pattern, f"{spec} {title} unrelated")
    with pytest.raises(ValueError, match="Unknown recovery case"):
        ci_run_tests.playwright_case_args(".*")
    assert ci_run_tests.case_coverage_complete(7, 0, "")
    assert ci_run_tests.case_coverage_complete(1, 0, title, title)
    assert not ci_run_tests.case_coverage_complete(0, 0, title, title)
    assert not ci_run_tests.case_coverage_complete(2, 0, title, title)
    assert not ci_run_tests.case_coverage_complete(1, 1, title, title)
    assert not ci_run_tests.case_coverage_complete(1, 0, title, "prefix " + title)

    def playwright_report(actual_title):
        return {"stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0},
                "suites": [{"title": spec, "specs": [{"title": actual_title,
                            "tests": [{"status": "expected", "results": [{"status": "passed"}]}]}]}]}

    exact = ci_run_tests.reported_playwright_case_title(playwright_report(title))
    wrong = ci_run_tests.reported_playwright_case_title(playwright_report("prefix " + title))
    assert exact == title and wrong == "prefix " + title
    assert ci_run_tests.case_coverage_complete(1, 0, title, exact)
    assert not ci_run_tests.case_coverage_complete(1, 0, title, wrong)


@pytest.mark.parametrize(("spec", "title"), sorted(ci_coordinator.APPROVED_RECOVERY_CASES))
def test_native_receipt_cannot_claim_full_spec_for_filtered_case(spec, title):
    result = {"spec": spec, "case_title": title, "coverage_scope": "single-case",
              "coverage_complete": True, "exit_code": 0,
              "reported_case_title": title,
              "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0}}
    filtered = {"case_title": title}
    full = {"case_title": ""}
    report = {"results": [result], "case_title": title, "coverage_scope": "single-case"}
    assert ci_results.valid_e2e_case_coverage(report, filtered)
    assert not ci_results.valid_e2e_case_coverage(report, full)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "coverage_scope": "full-spec"}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "coverage_complete": False}]}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "stats": {**result["stats"], "expected": 2}}]}, filtered)
    assert not ci_results.valid_e2e_case_coverage(
        {**report, "results": [{**result, "reported_case_title": "prefix " + title}]}, filtered)
    assert ci_results.valid_e2e_case_coverage(
        {"results": [{"spec": spec}], "coverage_scope": "full-spec"}, full)


def test_registered_recovery_titles_cannot_select_a_different_spec(tmp_path):
    queue = ci_coordinator.Queue(tmp_path / "queue.sqlite3")
    pairs = sorted(ci_coordinator.APPROVED_RECOVERY_CASES)
    assert len(pairs) == 3
    assert ("startup-sync-contract.spec.ts",
            "authenticated startup observes HTTP-cache cold fill and two same-route warm reloads") in pairs
    for spec, title in pairs:
        for wrong_spec, _ in pairs:
            if wrong_spec == spec:
                continue
            with pytest.raises(ValueError, match="Case filter requires"):
                queue.enqueue("owner", SOURCE, [wrong_spec], "e2e", case_title=title)
            with pytest.raises(ValueError, match="Case filter requires"):
                ci_coordinator.enqueue_submission(queue, "owner", SOURCE, [wrong_spec], "e2e", case_title=title)
        with pytest.raises(ValueError, match="Case filter requires"):
            queue.enqueue("owner", SOURCE, [spec], "pytest", case_title=title)
