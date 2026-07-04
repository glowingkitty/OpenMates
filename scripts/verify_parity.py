#!/usr/bin/env python3
"""Verify cross-client parity evidence in the required order.

Purpose: keep CLI, SDK, web, and Apple verification from happening out of order.
Architecture: orchestrates existing repo-approved test/control-plane scripts only.
Safety: never runs local Playwright or Vitest directly; use scripts/tests.py.
Evidence: writes JSON summaries under test-results/parity for deploy summaries.
Docs: docs/contributing/guides/testing.md and AGENTS.md describe when to run it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "test-results" / "parity"
LATEST_SUMMARY = EVIDENCE_DIR / "latest-summary.json"
MAX_OUTPUT_CHARS = 20000
DEFAULT_MAX_AGE_HOURS = 24
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_with_reason"


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    status: str
    command: list[str]
    started_at: str
    completed_at: str
    exit_code: int | None = None
    reason: str = ""
    stdout: str = ""
    stderr: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "command": self.command,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "stdout": truncate_output(self.stdout),
            "stderr": truncate_output(self.stderr),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def truncate_output(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[-MAX_OUTPUT_CHARS:]


def run_phase(phase: str, command: list[str]) -> PhaseResult:
    started_at = utc_now()
    print(f"parity: running {phase}: {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    completed_at = utc_now()
    status = STATUS_PASSED if result.returncode == 0 else STATUS_FAILED
    return PhaseResult(
        phase=phase,
        status=status,
        command=command,
        started_at=started_at,
        completed_at=completed_at,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def skipped_phase(phase: str, reason: str) -> PhaseResult:
    timestamp = utc_now()
    return PhaseResult(
        phase=phase,
        status=STATUS_SKIPPED,
        command=[],
        started_at=timestamp,
        completed_at=timestamp,
        reason=reason,
    )


def write_summary(results: list[PhaseResult]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now()
    overall_status = STATUS_PASSED if all(result.status != STATUS_FAILED for result in results) else STATUS_FAILED
    summary = {
        "schema_version": 1,
        "created_at": timestamp,
        "overall_status": overall_status,
        "required_order": ["sdk-cli-static", "cli", "web", "apple"],
        "phases": [result.as_dict() for result in results],
    }
    summary_path = EVIDENCE_DIR / f"summary-{timestamp.replace(':', '-')}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LATEST_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_path


def build_run_plan(args: argparse.Namespace) -> list[tuple[str, list[str] | None, str]]:
    plan: list[tuple[str, list[str] | None, str]] = [
        ("sdk-cli-static", [sys.executable, "scripts/audit_sdk_cli_parity.py"], ""),
        ("cli", [sys.executable, "scripts/tests.py", "run", "--suite", "cli"], ""),
    ]

    if args.web_spec:
        for spec in args.web_spec:
            plan.append((f"web:{spec}", [sys.executable, "scripts/tests.py", "run", "--spec", spec], ""))
    elif args.skip_web:
        plan.append(("web", None, args.skip_web))
    else:
        plan.append(("web", None, "No web spec requested. Pass --web-spec <name>.spec.ts or --skip-web REASON."))

    if args.apple == "skip":
        plan.append(("apple", None, args.skip_apple or "Apple verification explicitly skipped."))
    elif args.apple == "build":
        plan.append(("apple", [sys.executable, "scripts/apple_remote.py", "build-ios", "--simulator", args.simulator], ""))
    else:
        command = [sys.executable, "scripts/apple_remote.py", "test-ios", "--simulator", args.simulator]
        if args.only_testing:
            command.extend(["--only-testing", args.only_testing])
        plan.append(("apple", command, ""))

    return plan


def run_verification(args: argparse.Namespace) -> int:
    results: list[PhaseResult] = []
    for phase, command, skip_reason in build_run_plan(args):
        if command is None:
            result = skipped_phase(phase, skip_reason)
        else:
            result = run_phase(phase, command)
        results.append(result)
        if result.status == STATUS_FAILED:
            print(f"parity: {phase} failed; stopping before later phases", file=sys.stderr)
            break

    summary_path = write_summary(results)
    failed = [result for result in results if result.status == STATUS_FAILED]
    print(f"parity: summary {summary_path}")
    if failed:
        return 1
    skipped = [result for result in results if result.status == STATUS_SKIPPED]
    if skipped:
        print("parity: completed with explicit skip reason(s)")
    else:
        print("parity: passed")
    return 0


def load_latest_summary() -> dict[str, Any]:
    if not LATEST_SUMMARY.is_file():
        raise FileNotFoundError(f"No parity summary found at {LATEST_SUMMARY}")
    return json.loads(LATEST_SUMMARY.read_text(encoding="utf-8"))


def check_latest_summary(args: argparse.Namespace) -> int:
    try:
        summary = load_latest_summary()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"parity: {exc}", file=sys.stderr)
        return 1

    created_at = parse_utc(str(summary.get("created_at") or ""))
    if created_at is None:
        print("parity: latest summary has invalid created_at", file=sys.stderr)
        return 1

    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
    if age_hours > args.max_age_hours:
        print(f"parity: latest summary is stale ({age_hours:.1f}h old)", file=sys.stderr)
        return 1

    if summary.get("overall_status") != STATUS_PASSED:
        print("parity: latest summary did not pass", file=sys.stderr)
        return 1

    skipped = [phase for phase in summary.get("phases", []) if phase.get("status") == STATUS_SKIPPED]
    if skipped and args.no_skips:
        names = ", ".join(str(phase.get("phase")) for phase in skipped)
        print(f"parity: latest summary has skipped phases: {names}", file=sys.stderr)
        return 1

    print(f"parity: latest summary passed ({age_hours:.1f}h old)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify CLI, SDK, web, and Apple parity evidence")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Run parity phases in order and write evidence")
    mode.add_argument("--check", action="store_true", help="Check the latest parity summary without running tests")
    parser.add_argument("--web-spec", action="append", help="Playwright spec to dispatch through scripts/tests.py; repeatable")
    parser.add_argument("--skip-web", help="Explicit reason for not running web Playwright verification")
    parser.add_argument("--apple", choices=["build", "test", "skip"], default="build")
    parser.add_argument("--skip-apple", help="Explicit reason when --apple skip is used")
    parser.add_argument("--simulator", default="iPhone 17")
    parser.add_argument("--only-testing", help="Xcode only-testing selector for --apple test")
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--no-skips", action="store_true", help="Fail --check when latest evidence contains explicit skips")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.run and args.web_spec and args.skip_web:
        parser.error("Use --web-spec or --skip-web, not both")
    if args.run and not args.web_spec and not args.skip_web:
        parser.error("--run requires --web-spec <name>.spec.ts or --skip-web REASON")
    if args.apple == "skip" and not args.skip_apple:
        parser.error("--apple skip requires --skip-apple REASON")
    if args.run:
        return run_verification(args)
    return check_latest_summary(args)


if __name__ == "__main__":
    raise SystemExit(main())
