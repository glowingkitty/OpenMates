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
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from spec_validate import REPO_ROOT, SpecError, validate_spec


PASS_STATUSES = {"passed", "passed_after_deploy"}
RED_EVIDENCE_STATUSES = {
    "failed",
    "failed_as_expected",
    "passed_unexpectedly",
    "missing_test",
    "skipped_with_reason",
    "not_applicable",
}
FINAL_ACCEPTED_STATUSES = {"passed", "passed_after_deploy", "user_confirmed", "waived", "blocked"}
EVIDENCE_REASON_STATUSES = {"missing_test", "skipped_with_reason", "waived", "blocked"}


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


def _record_status(record: dict[str, Any]) -> str | None:
    evidence = record.get("evidence")
    if isinstance(evidence, dict):
        status = _evidence_status(evidence)
        if status:
            return status
    status = record.get("status")
    return status if isinstance(status, str) else None


def _evidence_contract_failures(
    data: dict[str, Any],
    *,
    record_id: str,
    phase: str,
    evidence: dict[str, Any] | None,
    automated: bool,
    playwright: bool = False,
) -> list[str]:
    if data.get("schema_version", 1) != 2 or not evidence:
        return []
    status = _evidence_status(evidence)
    if not status or status == "pending":
        return []

    failures: list[str] = []
    for field in ("timestamp",):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            failures.append(f"{record_id}: {phase} evidence missing {field}")
    if status in EVIDENCE_REASON_STATUSES:
        if not isinstance(evidence.get("reason"), str) or not evidence["reason"].strip():
            failures.append(f"{record_id}: {phase} evidence missing reason")
        if status in {"waived", "blocked"}:
            if not isinstance(evidence.get("actor"), str) or not evidence["actor"].strip():
                failures.append(f"{record_id}: {phase} evidence missing actor")
        if status == "blocked" and not any(
            isinstance(evidence.get(field), str) and evidence[field].strip()
            for field in ("next_action", "recheck_condition")
        ):
            failures.append(f"{record_id}: {phase} blocked evidence missing next_action or recheck_condition")
        return failures
    if not automated:
        if not isinstance(evidence.get("reason"), str) or not evidence["reason"].strip():
            failures.append(f"{record_id}: {phase} manual evidence missing reason")
        return failures

    for field in ("command", "run_id", "subject_commit"):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            failures.append(f"{record_id}: {phase} evidence missing {field}")

    if playwright and phase == "green_phase" and status in PASS_STATUSES:
        for field in ("target", "deployment_reference"):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                failures.append(f"{record_id}: {phase} evidence missing {field}")

    current_commit = data.get("implementation_state", {}).get("subject_commit")
    if (
        phase in {"green_phase", "green", "final"}
        and status in PASS_STATUSES
        and isinstance(current_commit, str)
        and current_commit.strip()
        and evidence.get("subject_commit") != current_commit
    ):
        failures.append(f"{record_id}: {phase} evidence is stale for subject_commit {current_commit}")
    return failures


def verify_spec(path: Path, *, require_red: bool, require_green: bool) -> list[str]:
    data = validate_spec(path)
    failures: list[str] = []

    if require_green:
        for criterion in data.get("acceptance_criteria", []) or []:
            if criterion.get("required") is False:
                continue
            coverage_status = criterion.get("coverage_status")
            if coverage_status in {"uncovered", "ambiguous"}:
                failures.append(f"{criterion['id']}: coverage_status is {coverage_status}")

        for assumption in data.get("assumptions", []) or []:
            if assumption.get("required_before", "never") == "never":
                continue
            status = assumption.get("status")
            if status in {"unchecked", "checking", "contradicted"}:
                failures.append(f"{assumption['id']}: unresolved required assumption ({status})")

    for test in data.get("tests", []):
        test_id = test["id"]
        red_phase = test.get("red_phase", {})
        green_phase = test.get("green_phase", {})

        if require_red and red_phase.get("required"):
            red_evidence = _phase_evidence(test, "red_phase")
            red_status = _evidence_status(red_evidence)
            if red_status not in RED_EVIDENCE_STATUSES:
                failures.append(f"{test_id}: missing red-phase evidence")
            failures.extend(
                _evidence_contract_failures(
                    data,
                    record_id=test_id,
                    phase="red_phase",
                    evidence=red_evidence,
                    automated=test.get("type") != "manual",
                    playwright=test.get("type") == "playwright",
                )
            )

        if require_green and green_phase.get("required"):
            green_evidence = _phase_evidence(test, "green_phase")
            green_status = _evidence_status(green_evidence)
            if green_status not in PASS_STATUSES:
                failures.append(f"{test_id}: missing green-phase passing evidence")
            failures.extend(
                _evidence_contract_failures(
                    data,
                    record_id=test_id,
                    phase="green_phase",
                    evidence=green_evidence,
                    automated=test.get("type") != "manual",
                    playwright=test.get("type") == "playwright",
                )
            )

    for verification in data.get("verifications", []) or []:
        verification_id = verification["id"]
        if not verification.get("required_for_done"):
            continue
        phase = verification.get("phase", "final")
        status = _record_status(verification)
        if require_red and phase == "red" and status not in RED_EVIDENCE_STATUSES:
            failures.append(f"{verification_id}: missing red-phase evidence")
        if require_green and phase in {"green", "final"} and status not in FINAL_ACCEPTED_STATUSES:
            failures.append(f"{verification_id}: missing required final evidence")
        if (require_red and phase == "red") or (require_green and phase in {"green", "final"}):
            failures.extend(
                _evidence_contract_failures(
                    data,
                    record_id=verification_id,
                    phase=phase,
                    evidence=verification.get("evidence") if isinstance(verification.get("evidence"), dict) else None,
                    automated=verification.get("kind") in {"automated_test", "deterministic_check"},
                )
            )

    return failures


def _requires_user_input(blocker: Any, current_task_id: str | None) -> bool:
    """Return whether a blocker explicitly pauses the current task for the user."""
    if not isinstance(blocker, dict) or blocker.get("task_id") != current_task_id:
        return False
    if blocker.get("requires_user_input") is not True:
        return False
    return all(isinstance(blocker.get(field), str) and blocker[field].strip() for field in ("reason", "question", "next_action"))


def spec_status(data: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    """Return only the continuation fields an OpenCode plugin needs."""
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    current_task_id = handoff.get("current_task_id")
    requires_user_input = _requires_user_input(handoff.get("blocker"), current_task_id)

    return {
        "active": data.get("schema_version") == 2 and data.get("status") == "implementing",
        "blocked": requires_user_input,
        "requires_user_input": requires_user_input,
        "complete": not failures,
        "current_task_id": current_task_id,
        "failures": failures,
        "next_action": handoff.get("next_action"),
        "state_fingerprint": hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an OpenMates executable spec.yml file")
    parser.add_argument("spec", type=Path, help="Path to docs/specs/<slug>/spec.yml")
    parser.add_argument("--phase", choices=("red", "green", "complete"), default="complete")
    parser.add_argument("--json", action="store_true", help="Print machine-readable continuation status")
    args = parser.parse_args()

    path = args.spec if args.spec.is_absolute() else REPO_ROOT / args.spec
    if not path.exists():
        if args.json:
            print(json.dumps({"active": False, "blocked": False, "complete": False, "failures": ["Spec not found"]}))
        print(f"Spec not found: {path}", file=sys.stderr)
        return 1

    require_red = args.phase in {"red", "complete"}
    require_green = args.phase in {"green", "complete"}

    try:
        failures = verify_spec(path, require_red=require_red, require_green=require_green)
    except SpecError as exc:
        if args.json:
            print(json.dumps({"active": False, "blocked": False, "complete": False, "failures": [str(exc)]}))
        print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(spec_status(validate_spec(path), failures), sort_keys=True))

    if failures:
        if not args.json:
            print(f"FAIL {path.relative_to(REPO_ROOT)}")
            for failure in failures:
                print(f"- {failure}")
        return 1

    if not args.json:
        print(f"PASS {path.relative_to(REPO_ROOT)}: evidence satisfies {args.phase} phase")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
