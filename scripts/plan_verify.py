#!/usr/bin/env python3
"""Verify executable plan.yml test evidence before completion or deploy.

This script layers evidence checks on top of structural validation. It does not
run tests itself; it verifies that red and green phase evidence has been recorded
in plan.yml by the workflow after approved test commands were run. Playwright
green evidence is intentionally required after dev deployment because tests run
against app.dev.openmates.org.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from plan_validate import REPO_ROOT, PlanError, validate_plan


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
ACCEPTED_PROOF_PRIVACY_STATUSES = {"passed", "not_applicable"}
UI_VISUAL_SMOKE_IDS = {"V-UI-VISUAL-SMOKE", "V-FIRECRAWL-VISUAL-SMOKE"}
UI_VISUAL_SMOKE_REQUIRED_VIEWPORTS = {"laptop", "mobile"}
VISUAL_SMOKE_REVIEW_RE = re.compile(r"\bscreenshot\w*\b.*\breview\w*\b|\breview\w*\b.*\bscreenshot\w*\b", re.IGNORECASE | re.DOTALL)
VISUAL_SMOKE_DEFECTS_RE = re.compile(r"\b(defects?|issues?|findings?)\s*:", re.IGNORECASE)
VISUAL_SMOKE_ACCEPTED_DIFF_RE = re.compile(r"\baccepted differences?\s*:", re.IGNORECASE)


def _normalise_viewports(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip().lower()} if value.strip() else set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def _visual_smoke_summary_has_review(summary: str) -> bool:
    return bool(
        VISUAL_SMOKE_REVIEW_RE.search(summary)
        and VISUAL_SMOKE_DEFECTS_RE.search(summary)
        and VISUAL_SMOKE_ACCEPTED_DIFF_RE.search(summary)
    )


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
    if data.get("schema_version", 1) < 2 or not evidence:
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
        if record_id in UI_VISUAL_SMOKE_IDS and status in PASS_STATUSES:
            for field in ("command", "run_id", "subject_commit"):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    failures.append(f"{record_id}: {phase} evidence missing {field}")
            if not any(
                isinstance(evidence.get(field), str) and evidence[field].strip()
                or isinstance(evidence.get(field), list) and evidence[field]
                for field in ("target", "url", "urls", "reviewed_urls")
            ):
                failures.append(f"{record_id}: {phase} evidence missing reviewed URL or target")
            viewports = _normalise_viewports(evidence.get("viewports") or evidence.get("viewport"))
            if not UI_VISUAL_SMOKE_REQUIRED_VIEWPORTS.issubset(viewports):
                failures.append(f"{record_id}: {phase} evidence missing laptop and mobile viewports")
            summary = evidence.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                failures.append(f"{record_id}: {phase} evidence missing visual-smoke summary")
            elif not _visual_smoke_summary_has_review(summary):
                failures.append(f"{record_id}: {phase} evidence summary missing screenshot review, defects, or accepted differences")
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
        and not _evidence_commit_covers_implementation(
            evidence.get("subject_commit"),
            current_commit,
        )
    ):
        failures.append(f"{record_id}: {phase} evidence is stale for subject_commit {current_commit}")
    return failures


def _evidence_commit_covers_implementation(evidence_commit: Any, current_commit: str) -> bool:
    """Accept evidence from the implementation commit or one of its ancestors."""
    if not isinstance(evidence_commit, str) or not evidence_commit.strip():
        return False
    candidate = _normalise_commit(evidence_commit)
    normalized_current = _normalise_commit(current_commit)
    if candidate == normalized_current:
        return True
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", candidate, normalized_current],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _normalise_commit(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.rsplit("@", 1)[-1].strip()


def _manifest_evidence_hash(manifest: dict[str, Any]) -> str:
    immutable = {key: value for key, value in manifest.items() if key != "publication"}
    encoded = json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _demonstration_failures(data: dict[str, Any]) -> list[str]:
    demonstration = data.get("demonstration")
    if not isinstance(demonstration, dict):
        if "schema_version" not in data and data.get("profile") != "strict":
            return []
        return ["demonstration: every implemented executable spec requires embedded proof-video evidence"]
    eligibility = demonstration.get("eligibility")
    if isinstance(eligibility, dict) and eligibility.get("status") == "not_applicable":
        if not isinstance(eligibility.get("reason"), str) or not eligibility["reason"].strip():
            return ["demonstration: not_applicable eligibility requires a reason"]
        if eligibility.get("surface") != "non_visual":
            return ["demonstration: not_applicable eligibility requires non_visual surface"]
        return []
    if not isinstance(eligibility, dict) or eligibility.get("status") != "required":
        return ["demonstration: implemented executable specs cannot complete without required proof-video evidence"]
    evidence = demonstration.get("evidence")
    if not isinstance(evidence, dict):
        return ["demonstration: missing required passing evidence"]

    failures: list[str] = []
    if evidence.get("status") == "waived":
        return ["demonstration: implemented executable specs cannot waive embedded proof-video evidence"]

    if evidence.get("status") != "passed":
        failures.append("demonstration: missing required passing evidence")
    if evidence.get("privacy_status") not in ACCEPTED_PROOF_PRIVACY_STATUSES:
        failures.append("demonstration: proof privacy state is not finalized")
    if evidence.get("audio_status") not in {"passed", "not_required"}:
        failures.append("demonstration: narration audio is neither passed nor intentionally disabled")
    if evidence.get("review_status") != "passed":
        failures.append("demonstration: frame-and-caption review has not passed")
    if evidence.get("publication_status") != "delivered":
        failures.append("demonstration: OpenCode response-media proof embed has not completed")

    review_attempts = evidence.get("review_attempts")
    if evidence.get("review_status") == "passed" and (not isinstance(review_attempts, int) or review_attempts < 1):
        failures.append("demonstration: passing review evidence requires at least one review attempt")
    if isinstance(review_attempts, int) and review_attempts >= 4 and evidence.get("review_status") != "passed":
        handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
        if not _requires_user_input(handoff.get("blocker"), handoff.get("current_task_id")):
            failures.append("demonstration: fourth unresolved review result requires a structured user blocker")

    if evidence.get("status") == "passed":
        for field in ("subject_commit", "manifest_path", "manifest_hash", "review_run_id", "timestamp"):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                failures.append(f"demonstration: passing evidence missing {field}")
        current_commit = data.get("implementation_state", {}).get("subject_commit")
        if _normalise_commit(current_commit) and _normalise_commit(evidence.get("subject_commit")) != _normalise_commit(current_commit):
            failures.append(f"demonstration: evidence is stale for subject_commit {current_commit}")
        manifest_value = evidence.get("manifest_path")
        manifest_path = Path(manifest_value) if isinstance(manifest_value, str) else Path()
        if manifest_value and not manifest_path.is_absolute():
            manifest_path = REPO_ROOT / manifest_path
        if not manifest_value or not manifest_path.is_file():
            failures.append("demonstration: evidence manifest does not exist")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failures.append("demonstration: evidence manifest is not valid JSON")
            else:
                if evidence.get("manifest_hash") != _manifest_evidence_hash(manifest):
                    failures.append("demonstration: manifest hash does not match the recorded artifact")
                privacy = manifest.get("privacy") if isinstance(manifest.get("privacy"), dict) else {}
                review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
                audio = manifest.get("narration_audio") if isinstance(manifest.get("narration_audio"), dict) else {}
                publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
                if not any(
                    isinstance(publication.get(field), str) and publication[field].strip()
                    for field in ("snippet_html", "snippet_markdown")
                ):
                    failures.append("demonstration: publication manifest is missing an embeddable response-media snippet")
                if audio.get("status") == "passed":
                    if audio.get("provider") != "elevenlabs" or audio.get("model") != "eleven_flash_v2_5":
                        failures.append("demonstration: narration audio must use ElevenLabs eleven_flash_v2_5")
                    if manifest.get("video_metadata", {}).get("has_audio") is not True:
                        failures.append("demonstration: rendered video is missing requested narration audio")
                expected = {
                    "subject_commit": manifest.get("subject_commit"),
                    "privacy_status": privacy.get("status"),
                    "audio_status": audio.get("status"),
                    "review_status": review.get("status"),
                    "review_run_id": review.get("run_id"),
                    "review_attempts": review.get("attempt_count"),
                    "publication_status": publication.get("status"),
                }
                for field, value in expected.items():
                    if field == "subject_commit":
                        matches = _normalise_commit(evidence.get(field)) == _normalise_commit(value)
                    else:
                        matches = evidence.get(field) == value
                    if not matches:
                        failures.append(f"demonstration: {field} does not match the evidence manifest")
    return failures


def verify_plan(path: Path, *, require_red: bool, require_green: bool) -> list[str]:
    data = validate_plan(path)
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

    if require_green:
        failures.extend(_demonstration_failures(data))

    return failures


def _requires_user_input(blocker: Any, current_task_id: str | None) -> bool:
    """Return whether a blocker explicitly pauses the current task for the user."""
    if not isinstance(blocker, dict) or blocker.get("task_id") != current_task_id:
        return False
    if blocker.get("requires_user_input") is not True:
        return False
    return all(isinstance(blocker.get(field), str) and blocker[field].strip() for field in ("reason", "question", "next_action"))


def plan_status(data: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    """Return only the continuation fields an OpenCode plugin needs."""
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    current_task_id = handoff.get("current_task_id")
    requires_user_input = _requires_user_input(handoff.get("blocker"), current_task_id)

    return {
        "active": data.get("schema_version", 1) >= 2 and data.get("status") == "implementing",
        "blocked": requires_user_input,
        "requires_user_input": requires_user_input,
        "complete": not failures,
        "current_task_id": current_task_id,
        "failures": failures,
        "next_action": handoff.get("next_action"),
        "state_fingerprint": hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an OpenMates executable plan.yml file")
    parser.add_argument("plan", type=Path, help="Path to docs/plans/<slug>/plan.yml")
    parser.add_argument("--phase", choices=("red", "green", "complete"), default="complete")
    parser.add_argument("--json", action="store_true", help="Print machine-readable continuation status")
    args = parser.parse_args()

    path = args.plan if args.plan.is_absolute() else REPO_ROOT / args.plan
    if not path.exists():
        if args.json:
            print(json.dumps({"active": False, "blocked": False, "complete": False, "failures": ["Plan not found"]}))
        print(f"Plan not found: {path}", file=sys.stderr)
        return 1

    require_red = args.phase in {"red", "complete"}
    require_green = args.phase in {"green", "complete"}

    try:
        failures = verify_plan(path, require_red=require_red, require_green=require_green)
    except PlanError as exc:
        if args.json:
            print(json.dumps({"active": False, "blocked": False, "complete": False, "failures": [str(exc)]}))
        print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(plan_status(validate_plan(path), failures), sort_keys=True))

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
