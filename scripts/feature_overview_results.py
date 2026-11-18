#!/usr/bin/env python3
"""Latest CI result per test file, for the feature overview (specifications/test-results.yml).

The feature overview derives each surface cell from Specification assertions, the
tests that declare them and the latest CI result of those tests. CI results live
only on the dev host (``logs/ci-coordinator/queue.sqlite3`` plus the validated
receipts under ``test-results/ci-runs/<job>/``) and are pruned after about two
weeks, so ``refresh`` folds them into a committed snapshot that keeps older
results until a newer run replaces them. The overview generator reads only the
snapshot, which keeps it deterministic and offline.

Rules (one result per repo-relative test file, the newest definite one wins):
- e2e/component: each full-spec Playwright result; unexpected > 0 -> failed,
  flaky > 0 -> flaky, only skipped -> skipped, else passed. Case-scoped runs and
  runs that failed without a test failure (infrastructure) are ignored.
- pytest/vitest: focused selections only. Exit 0 -> every selected file passed;
  a failure with named failed tests -> those files failed and the rest passed;
  any other failure is not attributable and ignored.
- apple-unit/apple-ui/apple-core: per test class from the xcodebuild log
  ("Test Case '-[Module.Class method]' passed|failed|skipped"), mapped to the
  Swift file that declares the class.
- Where the run records test cases (Playwright JSON report, pytest failed node
  ids, xcodebuild cases) a failed file also lists the failed case names, so a
  failure only marks the assertions whose declared test failed.
- Receipts must match the job (id, source commit, run id), as for the daily report.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SNAPSHOT = Path("specifications/test-results.yml")
QUEUE = Path("logs/ci-coordinator/queue.sqlite3")
RUNS = Path("test-results/ci-runs")
WEB_TESTS = "frontend/apps/web_app/tests/"
RESULTS = ("passed", "flaky", "skipped", "failed")
BROWSER_MODES = ("e2e", "component")
FOCUSED_MODES = ("pytest", "vitest")
APPLE_MODES = ("apple-unit", "apple-ui", "apple-core")
APPLE_CASE_RE = re.compile(r"^Test Case '-\[(\w+)\.(\w+) (\w+)\]' (passed|failed|skipped)", re.MULTILINE)
SWIFT_CLASS_RE = re.compile(r"^\s*(?:@\w+\s+)*(?:final\s+)?class\s+(\w+)\s*:", re.MULTILINE)
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def canonical_root(root: Path) -> Path:
    """The main checkout, which holds the dev-host CI stores (worktrees do not)."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


def load_snapshot(root: Path) -> dict[str, Any]:
    path = root / SNAPSHOT
    if not path.exists():
        return {"schema_version": 1, "as_of": None, "tests": {}}
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER) or {}
    data.setdefault("tests", {})
    return data


def _receipt(stores: Path, job: dict[str, Any]) -> dict[str, Any] | None:
    try:
        data = json.loads((stores / RUNS / job["id"] / "receipt.json").read_text())
    except (OSError, ValueError):
        return None
    if data.get("id") != job["id"] or data.get("source_commit") != job["source"]:
        return None
    if job.get("run_id") and str(data.get("run_id")) != str(job["run_id"]):
        return None
    return data


def _browser_results(result: dict[str, Any], receipt: dict[str, Any]) -> dict[str, str]:
    scope = result.get("coverage_scope") or receipt.get("coverage_scope")
    stats = result.get("stats") or {}
    spec = str(result.get("spec") or "")
    if scope != "full-spec" or not spec or not all(type(stats.get(k)) is int for k in ("expected", "unexpected", "skipped", "flaky")):
        return {}
    if stats["unexpected"]:
        outcome = "failed"
    elif result.get("exit_code") not in (0, None):
        return {}
    elif stats["flaky"]:
        outcome = "flaky"
    elif stats["expected"]:
        outcome = "passed"
    elif stats["skipped"]:
        outcome = "skipped"
    else:
        return {}
    return {WEB_TESTS + spec.removeprefix("tests/"): outcome}


def _playwright_failures(stores: Path, job_id: str) -> dict[str, list[str]]:
    """spec file name -> titles of tests whose final attempt failed, from ci-spec-*.json."""
    failures: dict[str, list[str]] = {}

    def walk(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                attempts = test.get("results") or []
                if attempts and attempts[-1].get("status") in ("failed", "timedOut", "interrupted"):
                    failures.setdefault(str(spec.get("file") or ""), []).append(str(spec.get("title") or ""))
        for child in suite.get("suites") or []:
            walk(child)

    for report in sorted((stores / RUNS / job_id / "subject/test-results").glob("ci-spec-*.json")):
        try:
            data = json.loads(report.read_text())
        except (OSError, ValueError):
            continue
        for suite in data.get("suites") or []:
            walk(suite)
    return failures


def _case_name(test_id: str) -> str:
    """pytest node id -> test function name (class prefix and parameters dropped)."""
    return test_id.rsplit("::", 1)[-1].split("[", 1)[0]


def _file_of(test_id: str) -> str:
    return test_id.split("::", 1)[0]


def _focused_results(result: dict[str, Any], root: Path) -> dict[str, str]:
    if result.get("selection_mode") != "focused":
        return {}
    selected = list(dict.fromkeys(_file_of(str(t)) for t in result.get("selected_tests") or []))
    if not selected:
        return {}
    if result.get("exit_code") == 0:
        return {path: "passed" for path in selected}
    failed_ids = [str(t) for t in result.get("failed_tests") or []]
    if not failed_ids:
        return {path: "failed" for path in selected} if len(selected) == 1 else {}
    outcome: dict[str, Any] = {}
    for path in selected:
        names = sorted({_case_name(f) for f in failed_ids if path == _file_of(f) or path.endswith("/" + _file_of(f))})
        outcome[path] = ("failed", names) if names else "passed"
    return outcome


def swift_test_classes(root: Path) -> dict[str, str]:
    """Swift test class name -> repo-relative file declaring it."""
    classes: dict[str, str] = {}
    for path in sorted((root / "apple").glob("*Tests/**/*.swift")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name in SWIFT_CLASS_RE.findall(text):
            classes.setdefault(name, str(path.relative_to(root)))
    return classes


def _apple_results(stores: Path, job: dict[str, Any], classes: dict[str, str]) -> dict[str, Any]:
    outcome: dict[str, str] = {}
    failed: dict[str, set[str]] = {}
    for log in sorted((stores / RUNS / job["id"]).glob("apple-*/rows/xcodebuild-test-*.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for _module, cls, method, state in APPLE_CASE_RE.findall(text):
            path = classes.get(cls)
            if not path:
                continue
            if state == "failed":
                failed.setdefault(path, set()).add(method)
            previous = outcome.get(path)
            if state == "failed" or previous == "failed":
                outcome[path] = "failed"
            elif state == "passed" or previous == "passed":
                outcome[path] = "passed"
            else:
                outcome[path] = "skipped"
    return {path: (state, sorted(failed[path])) if state == "failed" else state for path, state in outcome.items()}


def collect(stores: Path, root: Path) -> dict[str, dict[str, Any]]:
    """test path -> {result, date, commit, job} from every validated job still in the queue."""
    database = stores / QUEUE
    if not database.is_file():
        return {}
    modes = (*BROWSER_MODES, *FOCUSED_MODES, *APPLE_MODES)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        jobs = [dict(row) for row in connection.execute(
            f"SELECT id, source, run_id, mode, state, created FROM jobs WHERE mode IN ({','.join('?' * len(modes))})"
            " AND state IN ('success', 'failure') ORDER BY created",
            modes,
        )]
    classes = swift_test_classes(root) if any(job["mode"] in APPLE_MODES for job in jobs) else {}
    latest: dict[str, dict[str, Any]] = {}
    for job in jobs:
        receipt = _receipt(stores, job)
        if receipt is None:
            continue
        found: dict[str, Any] = {}
        if job["mode"] in APPLE_MODES:
            found = _apple_results(stores, job, classes)
        else:
            cases = _playwright_failures(stores, job["id"]) if job["mode"] in BROWSER_MODES else {}
            for result in (receipt.get("report") or {}).get("results") or []:
                if job["mode"] in BROWSER_MODES:
                    for path, outcome in _browser_results(result, receipt).items():
                        names = cases.get(path.removeprefix(WEB_TESTS))
                        found[path] = (outcome, sorted(set(names))) if outcome == "failed" and names else outcome
                else:
                    found.update(_focused_results(result, root))
        day = datetime.fromtimestamp(job["created"], timezone.utc).date().isoformat()
        for path, outcome in found.items():
            if (root / path).is_file():
                state, names = outcome if isinstance(outcome, tuple) else (outcome, [])
                latest[path] = {"result": state, "date": day, "commit": job["source"][:10], "job": job["id"][:12]}
                if names:
                    latest[path]["failed"] = names
    return latest


def refresh(root: Path, stores: Path | None = None) -> dict[str, int]:
    """Fold current CI results into the committed snapshot; return counts per result."""
    stores = stores or canonical_root(root)
    snapshot = load_snapshot(root)
    tests: dict[str, dict[str, Any]] = {
        path: data for path, data in snapshot["tests"].items() if (root / path).is_file()
    }
    for path, data in collect(stores, root).items():
        old = tests.get(path)
        if old is None or str(old.get("date")) <= data["date"]:
            tests[path] = data
    as_of = max((str(d["date"]) for d in tests.values()), default=None)
    text = (
        "# GENERATED by scripts/feature_overview.py refresh-results from the dev-host CI receipts.\n"
        "# Latest definite CI result per test file; older results stay until a newer run replaces them.\n"
        "# Input of the feature overview (specifications/generated/features.*). Do not edit by hand.\n"
        + f"schema_version: 1\nas_of: {repr(as_of) if as_of else 'null'}\ntests:\n"
        + "".join(
            f"  {json.dumps(path)}: {{result: {d['result']}, date: '{d['date']}', commit: '{d['commit']}', job: '{d['job']}'"
            + (f", failed: {json.dumps(d['failed'], ensure_ascii=False)}" if d.get("failed") else "") + "}\n"
            for path, d in sorted(tests.items())
        )
    )
    (root / SNAPSHOT).write_text(text, encoding="utf-8")
    counts = {name: 0 for name in RESULTS}
    for data in tests.values():
        counts[data["result"]] = counts.get(data["result"], 0) + 1
    return counts
