# contract-test-file: tooling
"""ci_failures: one report of every failure of a job set, and a rerun of only the failed targets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_failures  # noqa: E402


def job(tmp_path: Path, name: str, mode: str, specs: list[str], state: str, files: dict) -> dict:
    directory = tmp_path / name
    results = directory / "subject" / "test-results"
    results.mkdir(parents=True)
    for file_name, data in files.items():
        (results / file_name).write_text(json.dumps(data))
    return {"id": name * 8, "mode": mode, "selected_specs": specs, "state": state,
            "directory": str(directory), "run_id": "1", "report": {"error": None}}


def playwright_report(media_root: str) -> dict:
    failed = {"status": "unexpected", "results": [{"status": "failed",
              "error": {"message": "\x1b[31mError: expect(locator).toBeVisible() failed\x1b[39m\nLocator: x"},
              "attachments": [{"name": "screenshot", "path": f"{media_root}/test-results/ci-0/case/test-failed-1.png"},
                              {"name": "video", "path": f"{media_root}/test-results/ci-0/case/video.webm"},
                              {"name": "error-context", "path": f"{media_root}/test-results/ci-0/case/ctx.md"}]}]}
    passed = {"status": "expected", "results": [{"status": "passed"}]}
    return {"suites": [{"title": "a.spec.ts", "specs": [], "suites": [{"title": "group", "specs": [
        {"title": "breaks", "file": "a.spec.ts", "tests": [failed]},
        {"title": "works", "file": "a.spec.ts", "tests": [passed]},
    ]}]}], "errors": []}


# contract-test: tooling
def test_report_lists_every_failure_with_media_and_reruns_only_failed_targets(tmp_path):
    e2e = job(tmp_path, "a", "e2e", ["a.spec.ts"], "failure",
              {"ci-spec-0.json": playwright_report("/home/runner/work/x/subject/frontend/apps/web_app")})
    shot = Path(e2e["directory"]) / "subject/frontend/apps/web_app/test-results/ci-0/case/test-failed-1.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    green = job(tmp_path, "b", "e2e", ["b.spec.ts"], "success", {})
    pytest = job(tmp_path, "c", "pytest", [], "failure", {"ci-pytest.json": {"tests": [
        {"nodeid": "backend/tests/test_a.py::test_one", "outcome": "failed",
         "call": {"outcome": "failed", "longrepr": "assert 1 == 2"}},
        {"nodeid": "backend/tests/test_a.py::test_two", "outcome": "passed"},
        {"nodeid": "backend/tests/test_b.py::test_three", "outcome": "failed",
         "setup": {"outcome": "failed", "longrepr": "fixture missing"}},
    ]}})
    vitest = job(tmp_path, "d", "vitest", [], "failure", {"ci-unit-ui.json": {"testResults": [
        {"name": "/home/runner/work/x/subject/frontend/packages/ui/src/a.test.ts", "status": "failed",
         "assertionResults": [{"fullName": "adds", "status": "failed", "failureMessages": ["expected 3"]}]},
        {"name": "/home/runner/work/x/subject/frontend/packages/ui/src/b.test.ts", "status": "passed"},
    ]}})
    reports = [ci_failures.collect(item) for item in (e2e, green, pytest, vitest)]
    by_mode = {report["id"][0]: report for report in reports}
    assert [item["test"] for item in by_mode["a"]["failures"]] == ["group > breaks"]
    assert by_mode["a"]["failures"][0]["trace"][0] == "Error: expect(locator).toBeVisible() failed"
    assert str(shot) in by_mode["a"]["failures"][0]["media"]
    assert len(by_mode["a"]["failures"][0]["media"]) == 2
    assert by_mode["a"]["rerun"] == ["a.spec.ts"] and by_mode["b"]["rerun"] == []
    assert by_mode["c"]["rerun"] == ["backend/tests/test_a.py::test_one", "backend/tests/test_b.py::test_three"]
    assert by_mode["c"]["failures"][1]["trace"] == ["fixture missing"]
    assert by_mode["d"]["rerun"] == ["frontend/packages/ui/src/a.test.ts"]
    text = ci_failures.render(reports)
    assert text.startswith("4 jobs, 3 failed, 4 failing tests")
    assert "--mode e2e --spec 'a.spec.ts'" in text and "b.spec.ts'" not in text
    assert "--mode pytest --spec 'backend/tests/test_a.py::test_one' --spec 'backend/tests/test_b.py::test_three'" in text


# contract-test: tooling
def test_job_that_failed_before_its_tests_is_reported_and_rerun_whole(tmp_path):
    broken = job(tmp_path, "e", "component", ["c.spec.ts"], "failure", {})
    broken["report"] = {"error": "Isolated backend did not start"}
    report = ci_failures.collect(broken)
    assert report["failures"][0]["test"] == "(job failed outside the tests)"
    assert report["failures"][0]["trace"] == ["Isolated backend did not start"]
    assert report["rerun"] == ["c.spec.ts"]
