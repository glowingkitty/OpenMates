#!/usr/bin/env python3
"""One failure report for a set of finished isolated CI jobs, plus a rerun of only the failed targets.

Every job runs its whole selection (no fail-fast); this module reads the downloaded
results of each job and lists ALL failures together: test name, the first lines of
its trace, and the local screenshot, video and trace files. It ends with the
`ci_coordinator.py submit` arguments that rerun only what failed:

- e2e/component/artifact/visual-smoke: the failed spec files (one spec per job);
- pytest: the exact failed node IDs (`--test-target`);
- vitest: the failed test files;
- every other mode: the job's own target.

Used by `ci_coordinator.py failures <id> [<id> ...]`. Reads only local files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TRACE_LINES = 12
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SPEC_MODES = ("e2e", "component", "artifact", "visual-smoke")
MEDIA = ("screenshot", "video", "trace")


def _trace(text: str) -> list[str]:
    lines = [line.rstrip() for line in ANSI.sub("", text or "").splitlines() if line.strip()]
    return lines[:TRACE_LINES]


def _local(directory: Path, runner_path: str) -> str:
    """Map a runner-absolute attachment path to the downloaded copy under `directory`."""
    parts = Path(runner_path).parts
    if "test-results" in parts:
        tail = Path(*parts[len(parts) - parts[::-1].index("test-results"):])
        for found in directory.rglob(str(tail)):
            return str(found)
    return runner_path


def _results_dir(directory: Path) -> Path:
    return directory / "subject" / "test-results"


def playwright_failures(directory: Path) -> list[dict]:
    failures = []

    def walk(suite: dict, titles: list[str]) -> None:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                if test.get("status") not in ("unexpected", "flaky"):
                    continue
                last = (test.get("results") or [{}])[-1]
                error = (last.get("error") or {}).get("message") or "\n".join(
                    (item.get("message") or "") for item in last.get("errors", [])
                )
                failures.append({
                    "test": " > ".join([*titles, spec.get("title", "")]).strip(" >"),
                    "file": spec.get("file", ""),
                    "status": "flaky" if test.get("status") == "flaky" else last.get("status", "failed"),
                    "trace": _trace(error),
                    "media": [_local(directory, item["path"]) for item in last.get("attachments", [])
                              if item.get("name") in MEDIA and item.get("path")],
                })
        for child in suite.get("suites", []):
            walk(child, [*titles, child.get("title", "")] if child.get("title") else titles)

    for report in sorted(_results_dir(directory).glob("ci-spec-*.json")):
        data = json.loads(report.read_text())
        for suite in data.get("suites", []):
            walk(suite, [])
        for error in data.get("errors", []):
            failures.append({"test": "(spec could not run)", "file": "", "status": "error",
                             "trace": _trace(error.get("message", "")), "media": []})
    return failures


def pytest_failures(directory: Path) -> list[dict]:
    report = _results_dir(directory) / "ci-pytest.json"
    if not report.is_file():
        return []
    data = json.loads(report.read_text())
    failures = []
    for section in ("collectors", "tests"):
        for item in data.get(section, []):
            if item.get("outcome") not in ("failed", "error") or not item.get("nodeid"):
                continue
            phase = next((item[key] for key in ("call", "setup", "teardown")
                          if isinstance(item.get(key), dict) and item[key].get("outcome") == "failed"), {})
            text = phase.get("longrepr") or item.get("longrepr") or ""
            failures.append({"test": item["nodeid"], "file": item["nodeid"].split("::")[0],
                             "status": "failed", "trace": _trace(str(text))[-TRACE_LINES:], "media": []})
    return failures


def vitest_failures(directory: Path) -> list[dict]:
    failures = []
    for report in sorted(_results_dir(directory).glob("ci-unit-*.json")):
        data = json.loads(report.read_text())
        for result in data.get("testResults", []):
            if result.get("status") != "failed":
                continue
            name = result.get("name", "")
            relative = name[name.index("frontend/"):] if "frontend/" in name else name
            failed = [item for item in result.get("assertionResults", []) if item.get("status") == "failed"]
            for item in failed or [{"fullName": "(file could not run)", "failureMessages": [result.get("message", "")]}]:
                failures.append({"test": f"{relative} > {item.get('fullName', '')}", "file": relative,
                                 "status": "failed", "trace": _trace("\n".join(item.get("failureMessages", []))),
                                 "media": []})
    return failures


def summary_failures(directory: Path) -> list[dict]:
    """Rust, Apple and other modes: the per-step failure lines of ci-results.json."""
    report = _results_dir(directory) / "ci-results.json"
    if not report.is_file():
        return []
    failures = []
    for row in json.loads(report.read_text()).get("results", []):
        if row.get("exit_code", 0) != 0:
            failures.append({"test": row.get("suite") or row.get("spec") or "check", "file": "",
                             "status": "failed", "trace": [str(line) for line in row.get("failures", [])][:40],
                             "media": []})
    return failures


def collect(receipt: dict) -> dict:
    """Failures of one job receipt (from `ci_coordinator.py result`)."""
    mode = receipt.get("mode", "")
    specs = list(receipt.get("selected_specs") or [])
    directory = Path(receipt.get("directory") or "")
    state = receipt.get("state", "")
    if not directory.is_dir():
        failures = []
    elif mode in SPEC_MODES:
        failures = playwright_failures(directory)
    elif mode == "pytest":
        failures = pytest_failures(directory)
    elif mode == "vitest":
        failures = vitest_failures(directory)
    else:
        failures = summary_failures(directory)
    report_error = (receipt.get("report") or {}).get("error") or receipt.get("error")
    if state != "success" and not [item for item in failures if item["status"] != "flaky"]:
        failures.append({"test": "(job failed outside the tests)", "file": "", "status": state or "failed",
                         "trace": _trace(str(report_error or "no test result; see the GitHub run log")),
                         "media": []})
    if state == "success" or not failures:
        rerun: list[str] = []
    elif mode == "pytest" and all(item["test"].count("::") or item["test"].endswith(".py")
                                  for item in failures if item["status"] == "failed"):
        rerun = list(dict.fromkeys(item["test"] for item in failures if item["status"] == "failed")) or specs
    elif mode == "vitest" and any(item["file"] for item in failures):
        rerun = list(dict.fromkeys(item["file"] for item in failures if item["file"]))
    else:
        rerun = specs
    return {"id": receipt.get("id", ""), "mode": mode, "state": state, "specs": specs,
            "run_id": receipt.get("run_id", ""), "directory": str(directory), "failures": failures,
            "rerun": rerun}


def render(reports: list[dict]) -> str:
    failed = [report for report in reports if report["state"] != "success"]
    total = sum(len([item for item in report["failures"] if item["status"] != "flaky"]) for report in reports)
    lines = [f"{len(reports)} jobs, {len(failed)} failed, {total} failing tests"]
    for report in reports:
        lines.append(f"\n## {report['id'][:12]} {report['mode']} {', '.join(report['specs']) or '-'}: "
                     f"{report['state']} (run {report['run_id'] or '-'})")
        for item in report["failures"]:
            lines.append(f"- [{item['status']}] {item['test']}")
            lines += [f"    {line}" for line in item["trace"]]
            lines += [f"    media: {path}" for path in item["media"]]
    by_mode: dict[str, list[str]] = {}
    for report in reports:
        by_mode.setdefault(report["mode"], []).extend(report["rerun"])
    reruns = [(mode, list(dict.fromkeys(targets))) for mode, targets in by_mode.items() if targets]
    if reruns:
        lines.append("\nRerun only the failed targets (after the fix, with a fresh --source):")
        for mode, targets in reruns:
            lines.append("  python3 scripts/ci_coordinator.py submit --session <id> --source <ref> --mode "
                         + mode + "".join(f" --spec '{target}'" for target in targets))
    return "\n".join(lines)
