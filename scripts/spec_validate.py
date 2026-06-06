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
VALID_TEST_TYPES = {"playwright", "pytest", "vitest", "unit", "lint", "build", "manual"}
SCENARIO_ID = re.compile(r"^S-\d+$")
AC_ID = re.compile(r"^AC-\d+$")
TEST_ID = re.compile(r"^T-[A-Z0-9-]+$")


class SpecError(ValueError):
    """Raised when a spec.yml file fails validation."""


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


def _validate_acceptance_criteria(data: dict[str, Any], scenario_ids: set[str]) -> set[str]:
    ac_ids: set[str] = set()
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
        _require_string(criterion, f"acceptance_criteria[{index}].text")
    return ac_ids


def _validate_tests(data: dict[str, Any], ac_ids: set[str]) -> set[str]:
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
        if test_type == "playwright":
            target = _require_string(test, f"tests[{index}].target")
            if target != "app.dev.openmates.org":
                raise SpecError(f"{test_id} Playwright target must be app.dev.openmates.org")
            if green_phase.get("expected") != "pass_after_deploy":
                raise SpecError(f"{test_id} Playwright green_phase.expected must be pass_after_deploy")
    return covered


def validate_spec(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    _require_string(data, "id")
    _require_string(data, "title")
    status = _require_string(data, "status")
    if status not in VALID_STATUSES:
        raise SpecError(f"status must be one of {', '.join(sorted(VALID_STATUSES))}")
    _require_string(data, "goal")
    _validate_scope(data)
    scenario_ids = _validate_scenarios(data)
    ac_ids = _validate_acceptance_criteria(data, scenario_ids)
    covered_ac_ids = _validate_tests(data, ac_ids)
    missing_coverage = sorted(ac_ids - covered_ac_ids)
    if missing_coverage:
        raise SpecError(f"acceptance criteria without test coverage: {', '.join(missing_coverage)}")
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
