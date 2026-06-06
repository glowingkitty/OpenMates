#!/usr/bin/env python3
"""Verify executable spec.yml test evidence before completion or deploy.

This script layers evidence checks on top of structural validation. It does not
run tests itself; it verifies that red and green phase evidence has been recorded
in spec.yml by the workflow after approved test commands were run. Playwright
green evidence is intentionally required after dev deployment because specs run
against app.dev.openmates.org.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from spec_validate import REPO_ROOT, SpecError, validate_spec


PASS_STATUSES = {"passed", "passed_after_deploy"}
FAIL_STATUSES = {"failed", "failed_as_expected"}


def _phase_evidence(test: dict[str, Any], phase: str) -> dict[str, Any] | None:
    phase_data = test.get(phase)
    if not isinstance(phase_data, dict):
        return None
    evidence = phase_data.get("evidence")
    return evidence if isinstance(evidence, dict) else None


def _evidence_status(evidence: dict[str, Any] | None) -> str | None:
    if not evidence:
        return None
    status = evidence.get("status")
    return status if isinstance(status, str) else None


def verify_spec(path: Path, *, require_red: bool, require_green: bool) -> list[str]:
    data = validate_spec(path)
    failures: list[str] = []

    for test in data.get("tests", []):
        test_id = test["id"]
        red_phase = test.get("red_phase", {})
        green_phase = test.get("green_phase", {})

        if require_red and red_phase.get("required"):
            red_status = _evidence_status(_phase_evidence(test, "red_phase"))
            if red_status not in FAIL_STATUSES:
                failures.append(f"{test_id}: missing red-phase failure evidence")

        if require_green and green_phase.get("required"):
            green_status = _evidence_status(_phase_evidence(test, "green_phase"))
            if green_status not in PASS_STATUSES:
                failures.append(f"{test_id}: missing green-phase passing evidence")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an OpenMates executable spec.yml file")
    parser.add_argument("spec", type=Path, help="Path to docs/specs/<slug>/spec.yml")
    parser.add_argument("--phase", choices=("red", "green", "complete"), default="complete")
    args = parser.parse_args()

    path = args.spec if args.spec.is_absolute() else REPO_ROOT / args.spec
    if not path.exists():
        print(f"Spec not found: {path}", file=sys.stderr)
        return 1

    require_red = args.phase in {"red", "complete"}
    require_green = args.phase in {"green", "complete"}

    try:
        failures = verify_spec(path, require_red=require_red, require_green=require_green)
    except SpecError as exc:
        print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
        return 1

    if failures:
        print(f"FAIL {path.relative_to(REPO_ROOT)}")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"PASS {path.relative_to(REPO_ROOT)}: evidence satisfies {args.phase} phase")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
