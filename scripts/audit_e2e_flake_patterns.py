#!/usr/bin/env python3
"""
Audit repeated Playwright stabilization patterns before they become whack-a-mole.

This script is intentionally static and deterministic: it scans spec/helper
source plus recent commit subjects for wait/retry/timeout churn and prints a
small report that agents can route to the stabilize-e2e-pattern skill.

Architecture: docs/contributing/guides/testing.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN_ROOT = REPO_ROOT / "frontend" / "apps" / "web_app" / "tests"
STABILITY_SUBJECT_RE = re.compile(r"\b(stabiliz|wait|timeout|retry|race|readiness|hydrate|poll|flake)\w*\b", re.I)

SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("raw-wait", re.compile(r"\bwaitForTimeout\s*\("), "Replace raw sleeps with a deterministic helper or state assertion."),
    ("network-idle", re.compile(r"waitForLoadState\s*\(\s*['\"]networkidle['\"]"), "Avoid networkidle in app flows; wait for a product signal instead."),
    ("css-selector", re.compile(r"\.locator\(\s*['\"]\.[A-Za-z0-9_-]+"), "Use data-testid or role selectors instead of CSS classes."),
    ("ad-hoc-retry", re.compile(r"\b(retry|poll|eventually)\b", re.I), "Check whether this retry belongs in a shared E2E helper."),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    message: str
    text: str


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def scan_source(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern, message in SOURCE_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(_display(path), line_number, kind, message, line.strip()))
    return findings


def collect_paths(paths: list[Path]) -> list[Path]:
    collected: list[Path] = []
    roots = paths or [DEFAULT_SCAN_ROOT]
    for root in roots:
        path = root if root.is_absolute() else REPO_ROOT / root
        if path.is_file():
            collected.append(path)
            continue
        if path.is_dir():
            collected.extend(sorted(path.rglob("*.spec.ts")))
            collected.extend(sorted(path.rglob("*.ts")))
    return sorted(set(collected))


def recent_stability_subjects(since: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--pretty=format:%s"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if STABILITY_SUBJECT_RE.search(line)]


def build_report(paths: list[Path], since: str, threshold: int) -> dict:
    findings = [finding for path in collect_paths(paths) for finding in scan_source(path)]
    subjects = recent_stability_subjects(since)
    should_route = len(subjects) >= threshold or any(finding.kind == "raw-wait" for finding in findings)
    return {
        "ok": not should_route,
        "route_to": "stabilize-e2e-pattern" if should_route else "",
        "recent_stability_commits": len(subjects),
        "recent_stability_subjects": subjects[:20],
        "findings": [asdict(finding) for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit repeated E2E stabilization patterns")
    parser.add_argument("paths", nargs="*", type=Path, help="Spec/helper files or directories to scan")
    parser.add_argument("--since", default="7 days ago")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-route", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.paths, args.since, args.threshold)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Recent stability commits: {report['recent_stability_commits']}")
        print(f"Static findings: {len(report['findings'])}")
        if report["route_to"]:
            print(f"Recommended route: {report['route_to']}")
        for finding in report["findings"][:30]:
            print(f"{finding['path']}:{finding['line']} [{finding['kind']}] {finding['message']}")
    return 1 if args.fail_on_route and report["route_to"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
