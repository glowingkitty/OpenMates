#!/usr/bin/env python3
"""Validate executable OpenMates spec.yml files.

Full specs are product contracts stored as YAML under docs/specs/<slug>/spec.yml.
This validator keeps the contract deterministic enough for agents, hooks, and
deploy gates to reason about before source code changes begin. It intentionally
checks structure, ID references, and test metadata without trying to interpret
product intent.
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
VALID_SCHEMA_VERSIONS = {1, 2}
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
SCENARIO_ID = re.compile(r"^S-\d+$")
AC_ID = re.compile(r"^AC-\d+$")
TEST_ID = re.compile(r"^T-[A-Z0-9-]+$")
VERIFICATION_ID = re.compile(r"^V-[A-Z0-9-]+$")
ASSUMPTION_ID = re.compile(r"^A-\d+$")
TASK_ID = re.compile(r"^TASK-\d+[A-Z]?$|^T-\d+[A-Z]?$", re.IGNORECASE)
BROAD_AC_PATTERNS = (
    re.compile(r"^\s*all tests (pass|run successfully)\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*no regressions\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*everything works\s*\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*fully verified\s*\.?\s*$", re.IGNORECASE),
)


class SpecError(ValueError):
    """Raised when a spec.yml file fails validation."""


def _schema_version(data: dict[str, Any]) -> int:
    value = data.get("schema_version", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value not in VALID_SCHEMA_VERSIONS:
        raise SpecError(f"schema_version must be one of {', '.join(str(version) for version in sorted(VALID_SCHEMA_VERSIONS))}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"YAML parse error: {exc}") from exc

    if not isinstance(data, dict):
        raise SpecError("spec.yml must contain a YAML mapping at the top level")
    return data


def _as_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise SpecError(f"{field} must be a non-empty list")
    return value


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{field} must be a mapping")
    return value


def _require_string(data: dict[str, Any], field: str) -> str:
    key = field.rsplit(".", 1)[-1]
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_scope(data: dict[str, Any]) -> None:
    scope = _as_mapping(data.get("scope"), "scope")
    _as_list(scope.get("in"), "scope.in")
    _as_list(scope.get("out"), "scope.out")


def _validate_scenarios(data: dict[str, Any]) -> set[str]:
    scenario_ids: set[str] = set()
    for index, scenario in enumerate(_as_list(data.get("scenarios"), "scenarios"), start=1):
        scenario = _as_mapping(scenario, f"scenarios[{index}]")
        scenario_id = _require_string(scenario, f"scenarios[{index}].id")
        if not SCENARIO_ID.match(scenario_id):
            raise SpecError(f"scenario id {scenario_id!r} must match S-<number>")
        if scenario_id in scenario_ids:
            raise SpecError(f"duplicate scenario id {scenario_id}")
        scenario_ids.add(scenario_id)
        _require_string(scenario, f"scenarios[{index}].title")
        for key in ("given", "when", "then"):
            _as_list(scenario.get(key), f"scenarios[{index}].{key}")
    return scenario_ids


def _optional_string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    items = _as_list(value, field)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise SpecError(f"{field} must contain non-empty strings")
    return [item.strip() for item in items]


def _string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise SpecError(f"{field} must be {'a list' if allow_empty else 'a non-empty list'}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise SpecError(f"{field} must contain non-empty strings")
    return [item.strip() for item in value]


def _validate_acceptance_criteria(
    data: dict[str, Any],
    scenario_ids: set[str],
    schema_version: int,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    ac_ids: set[str] = set()
    ac_by_id: dict[str, dict[str, Any]] = {}
    for index, criterion in enumerate(_as_list(data.get("acceptance_criteria"), "acceptance_criteria"), start=1):
        criterion = _as_mapping(criterion, f"acceptance_criteria[{index}]")
        criterion_id = _require_string(criterion, f"acceptance_criteria[{index}].id")
        if not AC_ID.match(criterion_id):
            raise SpecError(f"acceptance criterion id {criterion_id!r} must match AC-<number>")
        if criterion_id in ac_ids:
            raise SpecError(f"duplicate acceptance criterion id {criterion_id}")
        ac_ids.add(criterion_id)
        scenario_id = _require_string(criterion, f"acceptance_criteria[{index}].scenario")
        if scenario_id not in scenario_ids:
            raise SpecError(f"{criterion_id} references unknown scenario {scenario_id}")
        text = _require_string(criterion, f"acceptance_criteria[{index}].text")

        if "status" in criterion and criterion["status"] not in VALID_AC_STATUSES:
            raise SpecError(f"{criterion_id}.status must be one of {', '.join(sorted(VALID_AC_STATUSES))}")
        if "coverage_status" in criterion and criterion["coverage_status"] not in VALID_COVERAGE_STATUSES:
            raise SpecError(f"{criterion_id}.coverage_status must be one of {', '.join(sorted(VALID_COVERAGE_STATUSES))}")
        if "verification_scope" in criterion and criterion["verification_scope"] not in VALID_VERIFICATION_SCOPES:
            raise SpecError(f"{criterion_id}.verification_scope must be one of {', '.join(sorted(VALID_VERIFICATION_SCOPES))}")

        verification_ids = _optional_string_list(criterion.get("verification_ids"), f"acceptance_criteria[{index}].verification_ids")
        if schema_version == 2:
            for field in ("required", "status", "coverage_status", "verification_scope"):
                if field not in criterion:
                    raise SpecError(f"{criterion_id} Schema V2 record requires {field}")
            if not isinstance(criterion["required"], bool):
                raise SpecError(f"{criterion_id}.required must be boolean")
            if criterion["required"] and criterion.get("coverage_status") == "covered" and not verification_ids:
                raise SpecError(f"{criterion_id} requires verification_ids when coverage_status is covered")
        if verification_ids and criterion.get("coverage_status") in {"uncovered", "ambiguous"}:
            raise SpecError(f"{criterion_id} has verification_ids but coverage_status is {criterion.get('coverage_status')}")
        if criterion.get("status") == "satisfied" and criterion.get("coverage_status") in {"uncovered", "ambiguous"}:
            raise SpecError(f"{criterion_id} cannot be satisfied while coverage_status is {criterion.get('coverage_status')}")
        if any(pattern.match(text) for pattern in BROAD_AC_PATTERNS) and criterion.get("coverage_status") != "ambiguous":
            raise SpecError(f"{criterion_id} is vague and must use coverage_status: ambiguous until scoped checks are defined")
        ac_by_id[criterion_id] = criterion
    return ac_ids, ac_by_id


def _validate_evidence(
    evidence: Any,
    *,
    record_id: str,
    phase: str,
    schema_version: int,
) -> None:
    if schema_version != 2:
        return
    _as_mapping(evidence, f"{record_id}.{phase}.evidence")


def _validate_tests(data: dict[str, Any], ac_ids: set[str], schema_version: int) -> tuple[set[str], set[str]]:
    covered: set[str] = set()
    test_ids: set[str] = set()
    for index, test in enumerate(_as_list(data.get("tests"), "tests"), start=1):
        test = _as_mapping(test, f"tests[{index}]")
        test_id = _require_string(test, f"tests[{index}].id")
        if not TEST_ID.match(test_id):
            raise SpecError(f"test id {test_id!r} must match T-<UPPERCASE-ID>")
        if test_id in test_ids:
            raise SpecError(f"duplicate test id {test_id}")
        test_ids.add(test_id)

        test_type = _require_string(test, f"tests[{index}].type")
        if test_type not in VALID_TEST_TYPES:
            raise SpecError(f"{test_id} has unsupported type {test_type!r}")
        if test_type != "manual":
            _require_string(test, f"tests[{index}].file")
            _require_string(test, f"tests[{index}].command")
        assertions = _as_list(test.get("assertions"), f"tests[{index}].assertions")
        if not all(isinstance(item, str) and item.strip() for item in assertions):
            raise SpecError(f"{test_id}.assertions must contain non-empty strings")

        covers = _as_list(test.get("covers"), f"tests[{index}].covers")
        for criterion_id in covers:
            if criterion_id not in ac_ids:
                raise SpecError(f"{test_id} covers unknown acceptance criterion {criterion_id}")
            covered.add(criterion_id)

        red_phase = _as_mapping(test.get("red_phase"), f"tests[{index}].red_phase")
        green_phase = _as_mapping(test.get("green_phase"), f"tests[{index}].green_phase")
        if "required" not in red_phase or "expected" not in red_phase:
            raise SpecError(f"{test_id}.red_phase must include required and expected")
        if "required" not in green_phase or "expected" not in green_phase:
            raise SpecError(f"{test_id}.green_phase must include required and expected")
        _validate_evidence(
            red_phase.get("evidence"),
            record_id=test_id,
            phase="red_phase",
            schema_version=schema_version,
        )
        _validate_evidence(
            green_phase.get("evidence"),
            record_id=test_id,
            phase="green_phase",
            schema_version=schema_version,
        )
        if test_type == "playwright":
            target = _require_string(test, f"tests[{index}].target")
            if target != "app.dev.openmates.org":
                raise SpecError(f"{test_id} Playwright target must be app.dev.openmates.org")
            if green_phase.get("expected") != "pass_after_deploy":
                raise SpecError(f"{test_id} Playwright green_phase.expected must be pass_after_deploy")
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
            raise SpecError(f"assumption id {assumption_id!r} must match A-<number>")
        if assumption_id in seen:
            raise SpecError(f"duplicate assumption id {assumption_id}")
        seen.add(assumption_id)
        _require_string(assumption, f"assumptions[{index}].text")
        status = assumption.get("status")
        if status not in VALID_ASSUMPTION_STATUSES:
            raise SpecError(f"{assumption_id}.status must be one of {', '.join(sorted(VALID_ASSUMPTION_STATUSES))}")
        required_before = assumption.get("required_before", "never")
        if required_before not in VALID_REQUIRED_BEFORE:
            raise SpecError(f"{assumption_id}.required_before must be one of {', '.join(sorted(VALID_REQUIRED_BEFORE))}")
        if schema_version == 2 and required_before != "never" and status in {"confirmed", "corrected"}:
            _as_list(assumption.get("evidence"), f"{assumption_id}.evidence")


def _validate_verifications(data: dict[str, Any], ac_ids: set[str], schema_version: int) -> tuple[set[str], set[str]]:
    verifications = data.get("verifications")
    if verifications is None:
        return set(), set()
    seen: set[str] = set()
    covered: set[str] = set()
    for index, verification in enumerate(_as_list(verifications, "verifications"), start=1):
        verification = _as_mapping(verification, f"verifications[{index}]")
        verification_id = _require_string(verification, f"verifications[{index}].id")
        if not VERIFICATION_ID.match(verification_id):
            raise SpecError(f"verification id {verification_id!r} must match V-<UPPERCASE-ID>")
        if verification_id in seen:
            raise SpecError(f"duplicate verification id {verification_id}")
        seen.add(verification_id)
        kind = _require_string(verification, f"verifications[{index}].kind")
        if kind not in VALID_VERIFICATION_KINDS:
            raise SpecError(f"{verification_id}.kind must be one of {', '.join(sorted(VALID_VERIFICATION_KINDS))}")
        phase = verification.get("phase", "final")
        if phase not in VALID_VERIFICATION_PHASES:
            raise SpecError(f"{verification_id}.phase must be one of {', '.join(sorted(VALID_VERIFICATION_PHASES))}")
        status = verification.get("status", "pending")
        if status not in VALID_VERIFICATION_STATUSES:
            raise SpecError(f"{verification_id}.status must be one of {', '.join(sorted(VALID_VERIFICATION_STATUSES))}")
        for criterion_id in _optional_string_list(verification.get("covers"), f"verifications[{index}].covers"):
            if criterion_id not in ac_ids:
                raise SpecError(f"{verification_id} covers unknown acceptance criterion {criterion_id}")
            covered.add(criterion_id)
        if verification.get("required_for_done") is True and phase in {"green", "final"} and status in {"failed", "pending"}:
            # Pending required checks are allowed while drafting/implementing; spec_verify enforces evidence before completion.
            pass
        _validate_evidence(
            verification.get("evidence"),
            record_id=verification_id,
            phase=phase,
            schema_version=schema_version,
        )
    return seen, covered


def _validate_task_refs(refs: dict[str, Any], field: str, scenario_ids: set[str], ac_ids: set[str]) -> None:
    for scenario_id in _optional_string_list(refs.get("scenarios"), f"{field}.scenarios"):
        if scenario_id not in scenario_ids:
            raise SpecError(f"{field} references unknown scenario {scenario_id}")
    for criterion_id in _optional_string_list(refs.get("acceptance_criteria"), f"{field}.acceptance_criteria"):
        if criterion_id not in ac_ids:
            raise SpecError(f"{field} references unknown acceptance criterion {criterion_id}")


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
    valid_verification_refs = test_ids | verification_ids
    for index, task in enumerate(_as_list(tasks, "tasks"), start=1):
        task = _as_mapping(task, f"tasks[{index}]")
        task_id = _require_string(task, f"tasks[{index}].id")
        if not TASK_ID.match(task_id):
            raise SpecError(f"task id {task_id!r} must match TASK-<number> or T-<number>")
        if task_id in seen:
            raise SpecError(f"duplicate task id {task_id}")
        seen.add(task_id)
        _require_string(task, f"tasks[{index}].title")
        if "status" in task and task["status"] not in VALID_TASK_STATUSES:
            raise SpecError(f"{task_id}.status must be one of {', '.join(sorted(VALID_TASK_STATUSES))}")
        if "phase" in task and task["phase"] not in VALID_TASK_PHASES:
            raise SpecError(f"{task_id}.phase must be one of {', '.join(sorted(VALID_TASK_PHASES))}")
        covers = task.get("covers")
        if covers is not None:
            _validate_task_refs(_as_mapping(covers, f"tasks[{index}].covers"), f"{task_id}.covers", scenario_ids, ac_ids)
        refs = _optional_string_list(task.get("verification", task.get("verification_ids")), f"tasks[{index}].verification")
        for ref in refs:
            if (ref.startswith("T-") or ref.startswith("V-")) and valid_verification_refs and ref not in valid_verification_refs:
                raise SpecError(f"{task_id} references unknown verification/test {ref}")
        if schema_version == 2:
            for field in ("status", "phase", "covers", "expected_files", "verification_ids", "dependencies", "blockers", "follow_up_tasks", "ownership"):
                if field not in task:
                    raise SpecError(f"{task_id} Schema V2 record requires {field}")
            _as_list(task.get("expected_files"), f"{task_id}.expected_files")
            _optional_string_list(task.get("verification_ids"), f"{task_id}.verification_ids")
            ownership = _as_mapping(task.get("ownership"), f"{task_id}.ownership")
            _as_list(ownership.get("files"), f"{task_id}.ownership.files")
            if not isinstance(ownership.get("shared_files"), list):
                raise SpecError(f"{task_id}.ownership.shared_files must be a list")
    if schema_version == 2:
        for index, task in enumerate(_as_list(tasks, "tasks"), start=1):
            task_id = _require_string(_as_mapping(task, f"tasks[{index}]"), f"tasks[{index}].id")
            for dependency in _string_list(task.get("dependencies"), f"{task_id}.dependencies", allow_empty=True):
                if dependency not in seen:
                    raise SpecError(f"{task_id} depends on unknown task {dependency}")
    return seen


def _validate_schema_v2(data: dict[str, Any], task_ids: set[str]) -> None:
    implementation_state = _as_mapping(data.get("implementation_state"), "implementation_state")
    _require_string(implementation_state, "implementation_state.subject_commit")

    approvals = _as_mapping(data.get("approvals"), "approvals")
    for approval_name in ("product_contract", "implementation_plan"):
        approval = _as_mapping(approvals.get(approval_name), f"approvals.{approval_name}")
        status = _require_string(approval, f"approvals.{approval_name}.status")
        if status not in VALID_APPROVAL_STATUSES:
            raise SpecError(f"approvals.{approval_name}.status must be one of {', '.join(sorted(VALID_APPROVAL_STATUSES))}")
        if status == "approved":
            _require_string(approval, f"approvals.{approval_name}.approved_at")
        if status in {"not_required", "waived", "blocked"}:
            _require_string(approval, f"approvals.{approval_name}.reason")

    for index, decision in enumerate(_as_list(data.get("decisions"), "decisions"), start=1):
        decision = _as_mapping(decision, f"decisions[{index}]")
        _require_string(decision, f"decisions[{index}].id")
        status = _require_string(decision, f"decisions[{index}].status")
        if status not in VALID_DECISION_STATUSES:
            raise SpecError(f"decisions[{index}].status must be one of {', '.join(sorted(VALID_DECISION_STATUSES))}")
        for field in ("decision", "reason", "decided_at"):
            _require_string(decision, f"decisions[{index}].{field}")

    for index, attempt in enumerate(_as_list(data.get("attempts"), "attempts"), start=1):
        attempt = _as_mapping(attempt, f"attempts[{index}]")
        _require_string(attempt, f"attempts[{index}].id")
        task_id = _require_string(attempt, f"attempts[{index}].task_id")
        if task_id not in task_ids:
            raise SpecError(f"attempts[{index}].task_id references unknown task {task_id}")
        outcome = _require_string(attempt, f"attempts[{index}].outcome")
        if outcome not in VALID_ATTEMPT_OUTCOMES:
            raise SpecError(f"attempts[{index}].outcome must be one of {', '.join(sorted(VALID_ATTEMPT_OUTCOMES))}")
        for field in ("approach", "recorded_at"):
            _require_string(attempt, f"attempts[{index}].{field}")

    handoff = _as_mapping(data.get("handoff"), "handoff")
    current_task_id = _require_string(handoff, "handoff.current_task_id")
    if current_task_id not in task_ids:
        raise SpecError(f"handoff.current_task_id references unknown task {current_task_id}")
    for field in ("next_action", "command", "expected_outcome", "last_verified_commit"):
        _require_string(handoff, f"handoff.{field}")
    blocker = handoff.get("blocker")
    if blocker is not None and not isinstance(blocker, dict):
        raise SpecError("handoff.blocker must be null or a mapping")

    plan = _as_mapping(data.get("implementation_plan"), "implementation_plan")
    for field in ("spec_path", "architecture"):
        _require_string(plan, f"implementation_plan.{field}")
    for field in ("existing_patterns", "data_flow", "affected_files", "verification_strategy", "verification_order"):
        _as_list(plan.get(field), f"implementation_plan.{field}")
    for index, affected_file in enumerate(_as_list(plan.get("affected_files"), "implementation_plan.affected_files"), start=1):
        affected_file = _as_mapping(affected_file, f"implementation_plan.affected_files[{index}]")
        _require_string(affected_file, f"implementation_plan.affected_files[{index}].path")
        _require_string(affected_file, f"implementation_plan.affected_files[{index}].reason")


def validate_spec(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    schema_version = _schema_version(data)
    _require_string(data, "id")
    _require_string(data, "title")
    status = _require_string(data, "status")
    if status not in VALID_STATUSES:
        raise SpecError(f"status must be one of {', '.join(sorted(VALID_STATUSES))}")
    _require_string(data, "goal")
    _validate_scope(data)
    scenario_ids = _validate_scenarios(data)
    ac_ids, ac_by_id = _validate_acceptance_criteria(data, scenario_ids, schema_version)
    covered_ac_ids, test_ids = _validate_tests(data, ac_ids, schema_version)
    _validate_assumptions(data, schema_version)
    verification_ids, verification_covered_ac_ids = _validate_verifications(data, ac_ids, schema_version)
    all_verification_refs = test_ids | verification_ids
    covered_ac_ids |= verification_covered_ac_ids
    for criterion_id, criterion in ac_by_id.items():
        for verification_id in _optional_string_list(criterion.get("verification_ids"), f"{criterion_id}.verification_ids"):
            if all_verification_refs and verification_id not in all_verification_refs:
                raise SpecError(f"{criterion_id} references unknown verification/test {verification_id}")
            covered_ac_ids.add(criterion_id)
        if criterion.get("coverage_status") in {"blocked", "waived"}:
            covered_ac_ids.add(criterion_id)
    task_ids = _validate_tasks(data, scenario_ids, ac_ids, test_ids, verification_ids, schema_version)
    missing_coverage = sorted(ac_ids - covered_ac_ids)
    if missing_coverage:
        raise SpecError(f"acceptance criteria without test coverage: {', '.join(missing_coverage)}")
    if schema_version == 2:
        _validate_schema_v2(data, task_ids)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OpenMates executable spec.yml file")
    parser.add_argument("spec", type=Path, help="Path to docs/specs/<slug>/spec.yml")
    args = parser.parse_args()

    path = args.spec if args.spec.is_absolute() else REPO_ROOT / args.spec
    if not path.exists():
        print(f"Spec not found: {path}", file=sys.stderr)
        return 1

    try:
        data = validate_spec(path)
    except SpecError as exc:
        print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
        return 1

    print(f"PASS {path.relative_to(REPO_ROOT)}: {data['id']} ({data['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
