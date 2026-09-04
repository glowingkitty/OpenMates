#!/usr/bin/env python3
"""Validate goal-first and strict executable OpenMates plan.yml files.

Plans require only a user-authored goal in their lightweight form. Repository
implementation Plans use the strict profile and retain deterministic scenarios,
evidence, Tasks, approvals, and handoff for agents, hooks, and deploy gates.
Optional lightweight sections never become implicit completion requirements.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
VALID_STATUSES = {"draft", "clarifying", "approved", "implementing", "verified"}
VALID_SCHEMA_VERSIONS = {1, 2, 3}
VALID_TEST_TYPES = {"playwright", "pytest", "vitest", "unit", "lint", "build", "manual"}
VALID_AC_STATUSES = {"pending", "satisfied", "failed", "waived", "blocked"}
VALID_COVERAGE_STATUSES = {"uncovered", "covered", "ambiguous", "blocked", "waived"}
VALID_VERIFICATION_SCOPES = {
    "plan",
    "related_backend",
    "related_frontend",
    "cli",
    "npm_sdk",
    "pip_sdk",
    "playwright",
    "ui_visual_smoke",
    "firecrawl_visual_smoke",
    "apple",
    "full_ci",
    "manual",
    "user_confirmation",
    "custom",
    "unknown",
}
VALID_ASSUMPTION_STATUSES = {"unchecked", "checking", "confirmed", "corrected", "contradicted", "blocked", "waived"}
VALID_REQUIRED_BEFORE = {"implementation", "task_execution", "completion", "never"}
VALID_VERIFICATION_KINDS = {
    "automated_test",
    "deterministic_check",
    "manual_check",
    "ai_evaluation",
    "user_confirmation",
    "artifact_review",
}
VALID_VERIFICATION_PHASES = {"red", "green", "final", "not_applicable"}
VALID_VERIFICATION_STATUSES = {"pending", "passed", "failed", "passed_unexpectedly", "skipped", "waived", "blocked"}
VALID_TASK_STATUSES = {"pending", "in_progress", "done", "blocked", "needs_fix", "cancelled"}
VALID_TASK_PHASES = {"drafting", "checking_assumptions", "awaiting_approval", "working_tasks", "running_checks", "blocked", "complete"}
VALID_APPROVAL_STATUSES = {"pending", "approved", "not_required", "waived", "blocked"}
VALID_DECISION_STATUSES = {"active", "superseded"}
VALID_ATTEMPT_OUTCOMES = {"planned", "failed_as_expected", "rejected", "blocked", "succeeded"}
VALID_DEMONSTRATION_ELIGIBILITY = {"required", "not_applicable"}
VALID_DEMONSTRATION_SURFACES = {"visual", "cli", "native", "mixed", "non_visual"}
VALID_DEMONSTRATION_STATUSES = {"pending", "passed", "failed", "blocked", "waived"}
VALID_DEMONSTRATION_REVIEW_STATUSES = {"pending", "passed", "failed", "blocked", "waived"}
VALID_DEMONSTRATION_PRIVACY_STATUSES = {"pending", "passed", "failed", "blocked", "waived", "not_applicable"}
VALID_DEMONSTRATION_AUDIO_STATUSES = {"pending", "passed", "not_required", "failed", "blocked"}
VALID_DEMONSTRATION_PUBLICATION_STATUSES = {
    "pending",
    "not_configured",
    "delivered",
    "publication_pending",
    "expired_deleted",
}
SCENARIO_ID = re.compile(r"^S-\d+$")
AC_ID = re.compile(r"^AC-\d+$")
TEST_ID = re.compile(r"^T-[A-Z0-9-]+$")
VERIFICATION_ID = re.compile(r"^V-[A-Z0-9-]+$")
ASSUMPTION_ID = re.compile(r"^A-\d+$")
NARRATION_ID = re.compile(r"^NARR-\d+$")
TASK_ID = re.compile(r"^TASK-\d+[A-Z]?$|^T-\d+[A-Z]?$", re.IGNORECASE)
BROAD_AC_PATTERNS = (
    re.compile(r"^\s*all tests (pass|run successfully)\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*no regressions\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*everything works\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*fully verified\s*\.?\s*$", re.IGNORECASE),
)


class PlanError(ValueError):
    """Raised when a plan.yml file fails validation."""

    def __init__(self, errors: str | list[str], *, partial: Any = None) -> None:
        raw_errors = [errors] if isinstance(errors, str) else errors
        self.errors = list(dict.fromkeys(raw_errors))
        self.partial = partial
        if len(self.errors) == 1:
            message = self.errors[0]
        else:
            details = "\n".join(f"  {index}. {error}" for index, error in enumerate(self.errors, start=1))
            message = f"{len(self.errors)} validation errors:\n{details}"
        super().__init__(message)


def _capture(errors: list[str], function: Any, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    """Run one independent validation and retain every diagnostic it emits."""
    try:
        return function(*args, **kwargs)
    except PlanError as exc:
        errors.extend(exc.errors)
        return exc.partial if exc.partial is not None else default

def _schema_version(data: dict[str, Any]) -> int:
    value = data.get("schema_version", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value not in VALID_SCHEMA_VERSIONS:
        raise PlanError(f"schema_version must be one of {', '.join(str(version) for version in sorted(VALID_SCHEMA_VERSIONS))}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PlanError(f"YAML parse error: {exc}") from exc

    if not isinstance(data, dict):
        raise PlanError("plan.yml must contain a YAML mapping at the top level")
    return data


def _as_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{field} must be a non-empty list")
    return value


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{field} must be a mapping")
    return value


def _require_string(data: dict[str, Any], field: str) -> str:
    key = field.rsplit(".", 1)[-1]
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_scope(data: dict[str, Any]) -> None:
    scope = _as_mapping(data.get("scope"), "scope")
    _as_list(scope.get("in"), "scope.in")
    _as_list(scope.get("out"), "scope.out")


def _validate_scenarios(data: dict[str, Any]) -> set[str]:
    scenario_ids: set[str] = set()
    errors: list[str] = []
    for index, scenario in enumerate(_as_list(data.get("scenarios"), "scenarios"), start=1):
        scenario = _capture(errors, _as_mapping, scenario, f"scenarios[{index}]", default=None)
        if scenario is None:
            continue
        scenario_id = _capture(errors, _require_string, scenario, f"scenarios[{index}].id", default=None)
        if scenario_id is None:
            continue
        if not SCENARIO_ID.match(scenario_id):
            errors.append(f"scenario id {scenario_id!r} must match S-<number>")
        if scenario_id in scenario_ids:
            errors.append(f"duplicate scenario id {scenario_id}")
        scenario_ids.add(scenario_id)
        _capture(errors, _require_string, scenario, f"scenarios[{index}].title")
        for key in ("given", "when", "then"):
            _capture(errors, _as_list, scenario.get(key), f"scenarios[{index}].{key}")
    if errors:
        raise PlanError(errors, partial=scenario_ids)
    return scenario_ids


def _optional_string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    items = _as_list(value, field)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise PlanError(f"{field} must contain non-empty strings")
    return [item.strip() for item in items]


def _string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise PlanError(f"{field} must be {'a list' if allow_empty else 'a non-empty list'}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise PlanError(f"{field} must contain non-empty strings")
    return [item.strip() for item in value]


def _validate_acceptance_criteria(
    data: dict[str, Any],
    scenario_ids: set[str],
    schema_version: int,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    ac_ids: set[str] = set()
    ac_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for index, criterion in enumerate(_as_list(data.get("acceptance_criteria"), "acceptance_criteria"), start=1):
        criterion = _capture(errors, _as_mapping, criterion, f"acceptance_criteria[{index}]", default=None)
        if criterion is None:
            continue
        criterion_id = _capture(errors, _require_string, criterion, f"acceptance_criteria[{index}].id", default=None)
        if criterion_id is None:
            continue
        if not AC_ID.match(criterion_id):
            errors.append(f"acceptance criterion id {criterion_id!r} must match AC-<number>")
        if criterion_id in ac_ids:
            errors.append(f"duplicate acceptance criterion id {criterion_id}")
        ac_ids.add(criterion_id)
        scenario_id = _capture(errors, _require_string, criterion, f"acceptance_criteria[{index}].scenario", default=None)
        if scenario_id is not None and scenario_id not in scenario_ids:
            errors.append(f"{criterion_id} references unknown scenario {scenario_id}")
        text = _capture(errors, _require_string, criterion, f"acceptance_criteria[{index}].text", default="")

        if "status" in criterion and criterion["status"] not in VALID_AC_STATUSES:
            errors.append(f"{criterion_id}.status must be one of {', '.join(sorted(VALID_AC_STATUSES))}")
        if "coverage_status" in criterion and criterion["coverage_status"] not in VALID_COVERAGE_STATUSES:
            errors.append(f"{criterion_id}.coverage_status must be one of {', '.join(sorted(VALID_COVERAGE_STATUSES))}")
        if "verification_scope" in criterion and criterion["verification_scope"] not in VALID_VERIFICATION_SCOPES:
            errors.append(f"{criterion_id}.verification_scope must be one of {', '.join(sorted(VALID_VERIFICATION_SCOPES))}")

        verification_ids = _capture(
            errors,
            _optional_string_list,
            criterion.get("verification_ids"),
            f"acceptance_criteria[{index}].verification_ids",
            default=[],
        )
        if schema_version >= 2:
            for field in ("required", "status", "coverage_status", "verification_scope"):
                if field not in criterion:
                    errors.append(f"{criterion_id} Schema V2 record requires {field}")
            if "required" in criterion and not isinstance(criterion["required"], bool):
                errors.append(f"{criterion_id}.required must be boolean")
            if criterion.get("required") is True and criterion.get("coverage_status") == "covered" and not verification_ids:
                errors.append(f"{criterion_id} requires verification_ids when coverage_status is covered")
        if schema_version >= 3:
            specification_assertions = _capture(
                errors,
                _string_list,
                criterion.get("specification_assertions"),
                f"{criterion_id}.specification_assertions",
                default=[],
            )
            for assertion_id in specification_assertions:
                if not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+", assertion_id):
                    errors.append(f"{criterion_id}.specification_assertions contains invalid assertion id {assertion_id!r}")
        if verification_ids and criterion.get("coverage_status") in {"uncovered", "ambiguous"}:
            errors.append(f"{criterion_id} has verification_ids but coverage_status is {criterion.get('coverage_status')}")
        if criterion.get("status") == "satisfied" and criterion.get("coverage_status") in {"uncovered", "ambiguous"}:
            errors.append(f"{criterion_id} cannot be satisfied while coverage_status is {criterion.get('coverage_status')}")
        if any(pattern.match(text) for pattern in BROAD_AC_PATTERNS) and criterion.get("coverage_status") != "ambiguous":
            errors.append(f"{criterion_id} is vague and must use coverage_status: ambiguous until scoped checks are defined")
        ac_by_id[criterion_id] = criterion
    if errors:
        raise PlanError(errors, partial=(ac_ids, ac_by_id))
    return ac_ids, ac_by_id


def _validate_evidence(
    evidence: Any,
    *,
    record_id: str,
    phase: str,
    schema_version: int,
) -> None:
    if schema_version < 2:
        return
    _as_mapping(evidence, f"{record_id}.{phase}.evidence")


def _validate_tests(data: dict[str, Any], ac_ids: set[str], schema_version: int) -> tuple[set[str], set[str]]:
    covered: set[str] = set()
    test_ids: set[str] = set()
    errors: list[str] = []
    for index, test in enumerate(_as_list(data.get("tests"), "tests"), start=1):
        test = _capture(errors, _as_mapping, test, f"tests[{index}]", default=None)
        if test is None:
            continue
        test_id = _capture(errors, _require_string, test, f"tests[{index}].id", default=None)
        if test_id is None:
            continue
        if not TEST_ID.match(test_id):
            errors.append(f"test id {test_id!r} must match T-<UPPERCASE-ID>")
        if test_id in test_ids:
            errors.append(f"duplicate test id {test_id}")
        test_ids.add(test_id)

        test_type = _capture(errors, _require_string, test, f"tests[{index}].type", default=None)
        if test_type is not None and test_type not in VALID_TEST_TYPES:
            errors.append(f"{test_id} has unsupported type {test_type!r}")
        if test_type is not None and test_type != "manual":
            _capture(errors, _require_string, test, f"tests[{index}].file")
            _capture(errors, _require_string, test, f"tests[{index}].command")
        assertions = _capture(errors, _as_list, test.get("assertions"), f"tests[{index}].assertions", default=[])
        if assertions and not all(isinstance(item, str) and item.strip() for item in assertions):
            errors.append(f"{test_id}.assertions must contain non-empty strings")
        if schema_version >= 3:
            _capture(errors, _string_list, test.get("specification_assertions"), f"{test_id}.specification_assertions")

        covers = _capture(errors, _as_list, test.get("covers"), f"tests[{index}].covers", default=[])
        for criterion_id in covers:
            if criterion_id not in ac_ids:
                errors.append(f"{test_id} covers unknown acceptance criterion {criterion_id}")
            covered.add(criterion_id)

        red_phase = _capture(errors, _as_mapping, test.get("red_phase"), f"tests[{index}].red_phase", default=None)
        green_phase = _capture(errors, _as_mapping, test.get("green_phase"), f"tests[{index}].green_phase", default=None)
        if red_phase is not None:
            if "required" not in red_phase or "expected" not in red_phase:
                errors.append(f"{test_id}.red_phase must include required and expected")
            _capture(
                errors, _validate_evidence, red_phase.get("evidence"),
                record_id=test_id, phase="red_phase", schema_version=schema_version,
            )
        if green_phase is not None:
            if "required" not in green_phase or "expected" not in green_phase:
                errors.append(f"{test_id}.green_phase must include required and expected")
            _capture(
                errors, _validate_evidence, green_phase.get("evidence"),
                record_id=test_id, phase="green_phase", schema_version=schema_version,
            )
        if test_type == "playwright":
            target = _capture(errors, _require_string, test, f"tests[{index}].target", default=None)
            if target is not None and target != "app.dev.openmates.org":
                errors.append(f"{test_id} Playwright target must be app.dev.openmates.org")
            if green_phase is not None and green_phase.get("expected") != "pass_after_deploy":
                errors.append(f"{test_id} Playwright green_phase.expected must be pass_after_deploy")
    if errors:
        raise PlanError(errors, partial=(covered, test_ids))
    return covered, test_ids


def _validate_assumptions(data: dict[str, Any], schema_version: int) -> None:
    assumptions = data.get("assumptions")
    if assumptions is None:
        return
    seen: set[str] = set()
    for index, assumption in enumerate(_as_list(assumptions, "assumptions"), start=1):
        assumption = _as_mapping(assumption, f"assumptions[{index}]")
        assumption_id = _require_string(assumption, f"assumptions[{index}].id")
        if not ASSUMPTION_ID.match(assumption_id):
            raise PlanError(f"assumption id {assumption_id!r} must match A-<number>")
        if assumption_id in seen:
            raise PlanError(f"duplicate assumption id {assumption_id}")
        seen.add(assumption_id)
        _require_string(assumption, f"assumptions[{index}].text")
        status = assumption.get("status")
        if status not in VALID_ASSUMPTION_STATUSES:
            raise PlanError(f"{assumption_id}.status must be one of {', '.join(sorted(VALID_ASSUMPTION_STATUSES))}")
        required_before = assumption.get("required_before", "never")
        if required_before not in VALID_REQUIRED_BEFORE:
            raise PlanError(f"{assumption_id}.required_before must be one of {', '.join(sorted(VALID_REQUIRED_BEFORE))}")
        if schema_version >= 2 and required_before != "never" and status in {"confirmed", "corrected"}:
            _as_list(assumption.get("evidence"), f"{assumption_id}.evidence")


def _validate_verifications(data: dict[str, Any], ac_ids: set[str], schema_version: int) -> tuple[set[str], set[str]]:
    verifications = data.get("verifications")
    if verifications is None:
        return set(), set()
    seen: set[str] = set()
    covered: set[str] = set()
    errors: list[str] = []
    for index, verification in enumerate(_as_list(verifications, "verifications"), start=1):
        verification = _capture(errors, _as_mapping, verification, f"verifications[{index}]", default=None)
        if verification is None:
            continue
        verification_id = _capture(errors, _require_string, verification, f"verifications[{index}].id", default=None)
        if verification_id is None:
            continue
        if not VERIFICATION_ID.match(verification_id):
            errors.append(f"verification id {verification_id!r} must match V-<UPPERCASE-ID>")
        if verification_id in seen:
            errors.append(f"duplicate verification id {verification_id}")
        seen.add(verification_id)
        kind = _capture(errors, _require_string, verification, f"verifications[{index}].kind", default=None)
        if kind is not None and kind not in VALID_VERIFICATION_KINDS:
            errors.append(f"{verification_id}.kind must be one of {', '.join(sorted(VALID_VERIFICATION_KINDS))}")
        phase = verification.get("phase", "final")
        if phase not in VALID_VERIFICATION_PHASES:
            errors.append(f"{verification_id}.phase must be one of {', '.join(sorted(VALID_VERIFICATION_PHASES))}")
        status = verification.get("status", "pending")
        if status not in VALID_VERIFICATION_STATUSES:
            errors.append(f"{verification_id}.status must be one of {', '.join(sorted(VALID_VERIFICATION_STATUSES))}")
        refs = _capture(
            errors, _optional_string_list, verification.get("covers"),
            f"verifications[{index}].covers", default=[],
        )
        for criterion_id in refs:
            if criterion_id not in ac_ids:
                errors.append(f"{verification_id} covers unknown acceptance criterion {criterion_id}")
            covered.add(criterion_id)
        if verification.get("required_for_done") is True and phase in {"green", "final"} and status in {"failed", "pending"}:
            # Pending required checks are allowed while drafting/implementing; spec_verify enforces evidence before completion.
            pass
        _capture(
            errors,
            _validate_evidence,
            verification.get("evidence"),
            record_id=verification_id,
            phase=phase,
            schema_version=schema_version,
        )
    if errors:
        raise PlanError(errors, partial=(seen, covered))
    return seen, covered


def _validate_demonstration(
    data: dict[str, Any],
    *,
    scenario_ids: set[str],
    ac_ids: set[str],
    verification_ids: set[str],
) -> None:
    value = data.get("demonstration")
    if value is None:
        return
    demonstration = _as_mapping(value, "demonstration")
    eligibility = _as_mapping(demonstration.get("eligibility"), "demonstration.eligibility")
    status = _require_string(eligibility, "demonstration.eligibility.status")
    if status not in VALID_DEMONSTRATION_ELIGIBILITY:
        raise PlanError(
            "demonstration.eligibility.status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_ELIGIBILITY))
        )
    surface = _require_string(eligibility, "demonstration.eligibility.surface")
    if surface not in VALID_DEMONSTRATION_SURFACES:
        raise PlanError(
            "demonstration.eligibility.surface must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_SURFACES))
        )
    _require_string(eligibility, "demonstration.eligibility.reason")
    _require_string(eligibility, "demonstration.eligibility.classified_at")

    if status == "not_applicable":
        if surface != "non_visual":
            raise PlanError("demonstration not_applicable requires surface: non_visual")
        refs = _string_list(
            eligibility.get("verification_ids"),
            "demonstration.eligibility.verification_ids",
        )
        known_ids = verification_ids
        for ref in refs:
            if ref not in known_ids:
                raise PlanError(f"demonstration.eligibility references unknown verification/test {ref}")
        return

    seen_narration_ids: set[str] = set()
    for index, narration in enumerate(
        _as_list(demonstration.get("narration_outline"), "demonstration.narration_outline"),
        start=1,
    ):
        narration = _as_mapping(narration, f"demonstration.narration_outline[{index}]")
        narration_id = _require_string(narration, f"demonstration.narration_outline[{index}].id")
        if not NARRATION_ID.match(narration_id):
            raise PlanError(f"narration id {narration_id!r} must match NARR-<number>")
        if narration_id in seen_narration_ids:
            raise PlanError(f"duplicate narration id {narration_id}")
        seen_narration_ids.add(narration_id)
        _require_string(narration, f"demonstration.narration_outline[{index}].purpose")
        _require_string(narration, f"demonstration.narration_outline[{index}].expected_proof")
        for scenario_id in _string_list(
            narration.get("scenario_ids"),
            f"demonstration.narration_outline[{index}].scenario_ids",
        ):
            if scenario_id not in scenario_ids:
                raise PlanError(f"{narration_id} references unknown scenario {scenario_id}")
        for criterion_id in _string_list(
            narration.get("acceptance_criteria"),
            f"demonstration.narration_outline[{index}].acceptance_criteria",
        ):
            if criterion_id not in ac_ids:
                raise PlanError(f"{narration_id} references unknown acceptance criterion {criterion_id}")

    evidence = _as_mapping(demonstration.get("evidence"), "demonstration.evidence")
    evidence_status = _require_string(evidence, "demonstration.evidence.status")
    if evidence_status not in VALID_DEMONSTRATION_STATUSES:
        raise PlanError(
            "demonstration.evidence.status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_STATUSES))
        )
    privacy_status = _require_string(evidence, "demonstration.evidence.privacy_status")
    if privacy_status not in VALID_DEMONSTRATION_PRIVACY_STATUSES:
        raise PlanError(
            "demonstration.evidence.privacy_status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_PRIVACY_STATUSES))
        )
    audio_status = evidence.get("audio_status", "pending")
    if not isinstance(audio_status, str) or not audio_status.strip():
        raise PlanError("demonstration.evidence.audio_status must be a string")
    if audio_status not in VALID_DEMONSTRATION_AUDIO_STATUSES:
        raise PlanError(
            "demonstration.evidence.audio_status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_AUDIO_STATUSES))
        )
    review_status = _require_string(evidence, "demonstration.evidence.review_status")
    if review_status not in VALID_DEMONSTRATION_REVIEW_STATUSES:
        raise PlanError(
            "demonstration.evidence.review_status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_REVIEW_STATUSES))
        )
    publication_status = _require_string(evidence, "demonstration.evidence.publication_status")
    if publication_status not in VALID_DEMONSTRATION_PUBLICATION_STATUSES:
        raise PlanError(
            "demonstration.evidence.publication_status must be one of "
            + ", ".join(sorted(VALID_DEMONSTRATION_PUBLICATION_STATUSES))
        )
    review_attempts = evidence.get("review_attempts")
    if isinstance(review_attempts, bool) or not isinstance(review_attempts, int) or review_attempts < 0 or review_attempts > 4:
        raise PlanError("demonstration.evidence.review_attempts must be an integer from 0 to 4")
    for field in ("subject_commit", "manifest_path", "manifest_hash", "review_run_id", "timestamp"):
        if field not in evidence or not isinstance(evidence[field], str):
            raise PlanError(f"demonstration.evidence.{field} must be a string")


def _validate_task_refs(refs: dict[str, Any], field: str, scenario_ids: set[str], ac_ids: set[str]) -> None:
    for scenario_id in _optional_string_list(refs.get("scenarios"), f"{field}.scenarios"):
        if scenario_id not in scenario_ids:
            raise PlanError(f"{field} references unknown scenario {scenario_id}")
    for criterion_id in _optional_string_list(refs.get("acceptance_criteria"), f"{field}.acceptance_criteria"):
        if criterion_id not in ac_ids:
            raise PlanError(f"{field} references unknown acceptance criterion {criterion_id}")


def _validate_tasks(
    data: dict[str, Any],
    scenario_ids: set[str],
    ac_ids: set[str],
    test_ids: set[str],
    verification_ids: set[str],
    schema_version: int,
) -> set[str]:
    tasks = data.get("tasks")
    if tasks is None:
        return set()
    seen: set[str] = set()
    errors: list[str] = []
    valid_verification_refs = test_ids | verification_ids
    for index, task in enumerate(_as_list(tasks, "tasks"), start=1):
        task = _as_mapping(task, f"tasks[{index}]")
        task_id = _require_string(task, f"tasks[{index}].id")
        if not TASK_ID.match(task_id):
            errors.append(f"task id {task_id!r} must match TASK-<number> or T-<number>")
        if task_id in seen:
            errors.append(f"duplicate task id {task_id}")
        seen.add(task_id)
        try:
            _require_string(task, f"tasks[{index}].title")
        except PlanError as exc:
            errors.extend(exc.errors)
        if "status" in task and task["status"] not in VALID_TASK_STATUSES:
            errors.append(f"{task_id}.status must be one of {', '.join(sorted(VALID_TASK_STATUSES))}")
        if "phase" in task and task["phase"] not in VALID_TASK_PHASES:
            errors.append(f"{task_id}.phase must be one of {', '.join(sorted(VALID_TASK_PHASES))}")
        covers = task.get("covers")
        if covers is not None:
            try:
                _validate_task_refs(_as_mapping(covers, f"tasks[{index}].covers"), f"{task_id}.covers", scenario_ids, ac_ids)
            except PlanError as exc:
                errors.extend(exc.errors)
        verification_key = "verification" if "verification" in task else "verification_ids"
        try:
            refs = _optional_string_list(task.get(verification_key), f"tasks[{index}].{verification_key}")
        except PlanError as exc:
            errors.extend(exc.errors)
            refs = []
        for ref in refs:
            if (ref.startswith("T-") or ref.startswith("V-")) and valid_verification_refs and ref not in valid_verification_refs:
                errors.append(f"{task_id} references unknown verification/test {ref}")
        if schema_version >= 2:
            for field in ("status", "phase", "covers", "expected_files", "verification_ids", "dependencies", "blockers", "follow_up_tasks", "ownership"):
                if field not in task:
                    errors.append(f"{task_id} Schema V2 record requires {field}")
            for key, validator in (("expected_files", _as_list),):
                if key not in task:
                    continue
                try:
                    validator(task[key], f"{task_id}.{key}")
                except PlanError as exc:
                    errors.extend(exc.errors)
            if verification_key != "verification_ids" and "verification_ids" in task:
                try:
                    _optional_string_list(task["verification_ids"], f"{task_id}.verification_ids")
                except PlanError as exc:
                    errors.extend(exc.errors)
            if "ownership" in task:
                try:
                    ownership = _as_mapping(task["ownership"], f"{task_id}.ownership")
                except PlanError as exc:
                    errors.extend(exc.errors)
                    ownership = None
                if ownership is not None:
                    try:
                        _as_list(ownership.get("files"), f"{task_id}.ownership.files")
                    except PlanError as exc:
                        errors.extend(exc.errors)
                    if not isinstance(ownership.get("shared_files"), list):
                        errors.append(f"{task_id}.ownership.shared_files must be a list")
    if schema_version >= 2:
        for index, task in enumerate(_as_list(tasks, "tasks"), start=1):
            task_id = _require_string(_as_mapping(task, f"tasks[{index}]"), f"tasks[{index}].id")
            dependencies = []
            if "dependencies" in task:
                try:
                    dependencies = _string_list(task["dependencies"], f"{task_id}.dependencies", allow_empty=True)
                except PlanError as exc:
                    errors.extend(exc.errors)
            for dependency in dependencies:
                if dependency not in seen:
                    errors.append(f"{task_id} depends on unknown task {dependency}")
    if errors:
        raise PlanError(errors, partial=seen)
    return seen


def _validate_schema_v2(data: dict[str, Any], task_ids: set[str], path: Path) -> None:
    errors: list[str] = []
    implementation_state = _capture(errors, _as_mapping, data.get("implementation_state"), "implementation_state", default=None)
    if implementation_state is not None:
        _capture(errors, _require_string, implementation_state, "implementation_state.subject_commit")

    approvals = _capture(errors, _as_mapping, data.get("approvals"), "approvals", default=None)
    if approvals is not None:
        for approval_name in ("specification", "plan"):
            approval = _capture(errors, _as_mapping, approvals.get(approval_name), f"approvals.{approval_name}", default=None)
            if approval is None:
                continue
            status = _capture(errors, _require_string, approval, f"approvals.{approval_name}.status", default=None)
            if status is not None and status not in VALID_APPROVAL_STATUSES:
                errors.append(f"approvals.{approval_name}.status must be one of {', '.join(sorted(VALID_APPROVAL_STATUSES))}")
            if status == "approved":
                _capture(errors, _require_string, approval, f"approvals.{approval_name}.approved_at")
            if status in {"not_required", "waived", "blocked"}:
                _capture(errors, _require_string, approval, f"approvals.{approval_name}.reason")

    decisions = _capture(errors, _as_list, data.get("decisions"), "decisions", default=[])
    for index, decision in enumerate(decisions, start=1):
        decision = _capture(errors, _as_mapping, decision, f"decisions[{index}]", default=None)
        if decision is None:
            continue
        _capture(errors, _require_string, decision, f"decisions[{index}].id")
        status = _capture(errors, _require_string, decision, f"decisions[{index}].status", default=None)
        if status is not None and status not in VALID_DECISION_STATUSES:
            errors.append(f"decisions[{index}].status must be one of {', '.join(sorted(VALID_DECISION_STATUSES))}")
        for field in ("decision", "reason", "decided_at"):
            _capture(errors, _require_string, decision, f"decisions[{index}].{field}")

    attempts = _capture(errors, _as_list, data.get("attempts"), "attempts", default=[])
    for index, attempt in enumerate(attempts, start=1):
        attempt = _capture(errors, _as_mapping, attempt, f"attempts[{index}]", default=None)
        if attempt is None:
            continue
        _capture(errors, _require_string, attempt, f"attempts[{index}].id")
        task_id = _capture(errors, _require_string, attempt, f"attempts[{index}].task_id", default=None)
        if task_id is not None and task_id not in task_ids:
            errors.append(f"attempts[{index}].task_id references unknown task {task_id}")
        outcome = _capture(errors, _require_string, attempt, f"attempts[{index}].outcome", default=None)
        if outcome is not None and outcome not in VALID_ATTEMPT_OUTCOMES:
            errors.append(f"attempts[{index}].outcome must be one of {', '.join(sorted(VALID_ATTEMPT_OUTCOMES))}")
        for field in ("approach", "recorded_at"):
            _capture(errors, _require_string, attempt, f"attempts[{index}].{field}")

    handoff = _capture(errors, _as_mapping, data.get("handoff"), "handoff", default=None)
    if handoff is not None:
        current_task_id = _capture(errors, _require_string, handoff, "handoff.current_task_id", default=None)
        if current_task_id is not None and current_task_id not in task_ids:
            errors.append(f"handoff.current_task_id references unknown task {current_task_id}")
        for field in ("next_action", "command", "expected_outcome", "last_verified_commit"):
            _capture(errors, _require_string, handoff, f"handoff.{field}")
        blocker = handoff.get("blocker")
        if blocker is not None and not isinstance(blocker, dict):
            errors.append("handoff.blocker must be null or a mapping")

    if "implementation_notes" in data:
        plan = _capture(errors, _as_mapping, data["implementation_notes"], "implementation_notes", default=None)
        if plan is None:
            if errors:
                raise PlanError(errors)
            return
        for field in ("plan_path", "architecture"):
            _capture(errors, _require_string, plan, f"implementation_notes.{field}")
        try:
            relative_plan_path = path.resolve().relative_to((REPO_ROOT / "docs" / "plans").resolve())
            expected_plan_path = f"docs/plans/{relative_plan_path.as_posix()}"
        except ValueError:
            expected_plan_path = f"docs/plans/{data['id']}/plan.yml"
        if isinstance(plan.get("plan_path"), str) and plan["plan_path"] != expected_plan_path:
            errors.append(f"implementation_notes.plan_path must be {expected_plan_path}")
        for field in ("existing_patterns", "data_flow", "affected_files", "verification_strategy", "verification_order"):
            _capture(errors, _as_list, plan.get(field), f"implementation_notes.{field}")
        affected_files = _capture(errors, _as_list, plan.get("affected_files"), "implementation_notes.affected_files", default=[])
        for index, affected_file in enumerate(affected_files, start=1):
            affected_file = _capture(errors, _as_mapping, affected_file, f"implementation_notes.affected_files[{index}]", default=None)
            if affected_file is not None:
                _capture(errors, _require_string, affected_file, f"implementation_notes.affected_files[{index}].path")
                _capture(errors, _require_string, affected_file, f"implementation_notes.affected_files[{index}].reason")
    if errors:
        raise PlanError(errors)


def _validate_schema_v3(data: dict[str, Any]) -> None:
    refs = _as_list(data.get("specification_refs"), "specification_refs")
    seen: set[str] = set()
    primary_count = 0
    for index, ref in enumerate(refs, start=1):
        ref = _as_mapping(ref, f"specification_refs[{index}]")
        specification_id = _require_string(ref, f"specification_refs[{index}].id")
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+", specification_id):
            raise PlanError(f"specification_refs[{index}].id is invalid: {specification_id!r}")
        if specification_id in seen:
            raise PlanError(f"duplicate specification_refs id {specification_id}")
        seen.add(specification_id)
        version = ref.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PlanError(f"specification_refs[{index}].version must be a positive integer")
        role = _require_string(ref, f"specification_refs[{index}].role")
        if role not in {"primary", "inherited"}:
            raise PlanError(f"specification_refs[{index}].role must be primary or inherited")
        primary_count += role == "primary"
    if primary_count != 1:
        raise PlanError("specification_refs must contain exactly one primary Specification")

    impact = _as_mapping(data.get("specification_impact"), "specification_impact")
    classification = _require_string(impact, "specification_impact.classification")
    if classification not in {"new_specification", "semantic_change", "implementation_only"}:
        raise PlanError("specification_impact.classification must be new_specification, semantic_change, or implementation_only")
    update_required = impact.get("specification_update_required")
    if not isinstance(update_required, bool):
        raise PlanError("specification_impact.specification_update_required must be boolean")
    if (classification in {"new_specification", "semantic_change"}) != update_required:
        raise PlanError("specification_impact.specification_update_required contradicts classification")
    _string_list(impact.get("affected_assertions"), "specification_impact.affected_assertions")
    _require_string(impact, "specification_impact.reason")

    docs = _as_mapping(data.get("documentation_impact"), "documentation_impact")
    valid_statuses = {"unchanged", "update_required", "regenerate", "not_applicable"}
    for area in ("generated_reference", "user_docs", "semantic_layer"):
        record = _as_mapping(docs.get(area), f"documentation_impact.{area}")
        status = _require_string(record, f"documentation_impact.{area}.status")
        if status not in valid_statuses:
            raise PlanError(f"documentation_impact.{area}.status must be one of {', '.join(sorted(valid_statuses))}")
        if status in {"unchanged", "not_applicable"}:
            _require_string(record, f"documentation_impact.{area}.reason")


def validate_plan(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    errors: list[str] = []
    _capture(errors, _require_string, data, "id")
    _capture(errors, _require_string, data, "title")
    status = _capture(errors, _require_string, data, "status", default=None)
    if status is not None and status not in VALID_STATUSES:
        errors.append(f"status must be one of {', '.join(sorted(VALID_STATUSES))}")
    _capture(errors, _require_string, data, "goal")

    strict = data.get("profile") == "strict" or "schema_version" in data
    if not strict:
        _capture(errors, _validate_assumptions, data, schema_version=1)
        if errors:
            raise PlanError(errors)
        return data

    schema_version = _capture(errors, _schema_version, data, default=1)
    _capture(errors, _validate_scope, data)
    scenario_ids = _capture(errors, _validate_scenarios, data, default=set())
    ac_ids, ac_by_id = _capture(
        errors, _validate_acceptance_criteria, data, scenario_ids, schema_version,
        default=(set(), {}),
    )
    covered_ac_ids, test_ids = _capture(
        errors, _validate_tests, data, ac_ids, schema_version, default=(set(), set()),
    )
    _capture(errors, _validate_assumptions, data, schema_version)
    verification_ids, verification_covered_ac_ids = _capture(
        errors, _validate_verifications, data, ac_ids, schema_version, default=(set(), set()),
    )
    _capture(
        errors,
        _validate_demonstration,
        data,
        scenario_ids=scenario_ids,
        ac_ids=ac_ids,
        verification_ids=test_ids | verification_ids,
    )
    all_verification_refs = test_ids | verification_ids
    covered_ac_ids |= verification_covered_ac_ids
    for criterion_id, criterion in ac_by_id.items():
        refs = _capture(
            errors, _optional_string_list, criterion.get("verification_ids"),
            f"{criterion_id}.verification_ids", default=[],
        )
        for verification_id in refs:
            if all_verification_refs and verification_id not in all_verification_refs:
                errors.append(f"{criterion_id} references unknown verification/test {verification_id}")
            covered_ac_ids.add(criterion_id)
        if criterion.get("coverage_status") in {"blocked", "waived"}:
            covered_ac_ids.add(criterion_id)
    task_ids = _capture(
        errors, _validate_tasks, data, scenario_ids, ac_ids, test_ids, verification_ids,
        schema_version, default=set(),
    )
    missing_coverage = sorted(ac_ids - covered_ac_ids)
    if missing_coverage:
        errors.append(f"acceptance criteria without test coverage: {', '.join(missing_coverage)}")
    if schema_version >= 2:
        _capture(errors, _validate_schema_v2, data, task_ids, path)
    if schema_version >= 3:
        _capture(errors, _validate_schema_v3, data)
    if errors:
        raise PlanError(errors)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OpenMates executable plan.yml file")
    parser.add_argument("plan", type=Path, help="Path to docs/plans/<slug>/plan.yml")
    args = parser.parse_args()

    path = args.plan if args.plan.is_absolute() else REPO_ROOT / args.plan
    if not path.exists():
        print(f"Plan not found: {path}", file=sys.stderr)
        return 1

    try:
        data = validate_plan(path)
    except PlanError as exc:
        print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
        return 1

    print(f"PASS {path.relative_to(REPO_ROOT)}: {data['id']} ({data['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
