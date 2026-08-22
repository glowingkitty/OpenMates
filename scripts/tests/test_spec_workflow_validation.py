"""Tests for executable spec workflow validation.

Purpose: keep OpenMates spec.yml files close to the Plans V1 contract.
Architecture: import validator modules directly and write tiny temp specs.
Security: temp specs use placeholder values only and never touch product data.
Tests: python3 -m pytest scripts/tests/test_spec_workflow_validation.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spec.yml"
    path.write_text(body, encoding="utf-8")
    return path


def minimal_spec(extra_ac: str = "", extra_top_level: str = "") -> str:
    return f"""
id: example
title: Example
status: approved
goal: Prove validator behavior.
scope:
  in:
    - Example behavior
  out:
    - Production data
scenarios:
  - id: S-1
    title: User does the thing
    given:
      - Alice is logged in
    when:
      - Alice starts the flow
    then:
      - The flow succeeds
acceptance_criteria:
  - id: AC-1
    scenario: S-1
    text: The example flow succeeds.
    required: true
    status: pending
    coverage_status: covered
    verification_scope: related_backend
    verification_ids:
      - V-EXAMPLE
{extra_ac}
tests:
  - id: T-PYTEST-EXAMPLE
    type: pytest
    file: backend/tests/test_example.py
    command: python3 -m pytest backend/tests/test_example.py
    covers:
      - AC-1
    assertions:
      - example assertion
    red_phase:
      required: true
      expected: fail
      evidence:
        status: failed_as_expected
        run_id: local:red
        timestamp: "2026-07-02T00:00:00Z"
    green_phase:
      required: true
      expected: pass
      evidence:
        status: passed
        run_id: local:green
        timestamp: "2026-07-02T00:00:00Z"
verifications:
  - id: V-EXAMPLE
    kind: automated_test
    phase: final
    required_for_done: true
    covers:
      - AC-1
    status: passed
    evidence:
      status: passed
      run_id: local:green
      timestamp: "2026-07-02T00:00:00Z"
tasks:
  - id: TASK-1
    title: Implement example slice
    status: pending
    phase: working_tasks
    covers:
      scenarios:
        - S-1
      acceptance_criteria:
        - AC-1
    verification_ids:
      - V-EXAMPLE
    independently_deployable: true
{extra_top_level}
"""


def schema_v2_spec() -> str:
    return minimal_spec(
        extra_top_level="""
implementation_state:
  subject_commit: abc1234
approvals:
  product_contract:
    status: approved
    approved_at: "2026-07-10T00:00:00Z"
  implementation_plan:
    status: not_required
    reason: Existing architecture supports the approved contract.
decisions:
  - id: D-1
    status: active
    decision: Reuse the existing route pattern.
    reason: It already enforces authenticated access.
    decided_at: "2026-07-10T00:00:00Z"
attempts:
  - id: ATTEMPT-1
    task_id: TASK-1
    approach: Add a focused validator fixture.
    outcome: planned
    recorded_at: "2026-07-10T00:00:00Z"
handoff:
  current_task_id: TASK-1
  next_action: Run the validator fixture.
  command: python3 -m pytest scripts/tests/test_spec_workflow_validation.py
  expected_outcome: The fixture passes after validator implementation.
  blocker: null
  last_verified_commit: abc1234
implementation_plan:
  spec_path: docs/specs/example/spec.yml
  existing_patterns:
    - scripts/spec_validate.py
  architecture: Extend the validator with Schema V2 checks.
  data_flow:
    - Author creates a Schema V2 spec.
    - Validator checks the required records.
  affected_files:
    - path: scripts/spec_validate.py
      reason: Validate Schema V2.
  verification_strategy:
    - python3 -m pytest scripts/tests/test_spec_workflow_validation.py
  verification_order:
    - Validator fixtures first.
tasks:
  - id: TASK-1
    title: Implement example slice
    status: pending
    phase: working_tasks
    covers:
      scenarios:
        - S-1
      acceptance_criteria:
        - AC-1
    expected_files:
      - scripts/spec_validate.py
    ownership:
      files:
        - scripts/spec_validate.py
      shared_files: []
    verification_ids:
      - V-EXAMPLE
    dependencies: []
    blockers: []
    follow_up_tasks: []
    independently_deployable: true
""",
    ).replace(
        "id: example\n",
        "schema_version: 2\nid: example\n",
        1,
    ).replace(
        """        status: failed_as_expected
        run_id: local:red
        timestamp: "2026-07-02T00:00:00Z"
""",
        """        status: failed_as_expected
        command: python3 -m pytest backend/tests/test_example.py
        run_id: local:red
        subject_commit: abc1234
        timestamp: "2026-07-02T00:00:00Z"
""",
        1,
    ).replace(
        """        status: passed
        run_id: local:green
        timestamp: "2026-07-02T00:00:00Z"
""",
        """        status: passed
        command: python3 -m pytest backend/tests/test_example.py
        run_id: local:green
        subject_commit: abc1234
        timestamp: "2026-07-02T00:00:00Z"
""",
        1,
    ).replace(
        """      status: passed
      run_id: local:green
      timestamp: "2026-07-02T00:00:00Z"
""",
        """      status: passed
      command: python3 -m pytest backend/tests/test_example.py
      run_id: local:green
      subject_commit: abc1234
      timestamp: "2026-07-02T00:00:00Z"
""",
        1,
    )


def schema_v3_spec() -> str:
    return schema_v2_spec().replace("schema_version: 2", "schema_version: 3", 1).replace(
        "implementation_state:\n",
        """contract_refs:
  - id: feature.example
    version: 1
    role: primary
contract_impact:
  classification: implementation_only
  contract_update_required: false
  affected_assertions:
    - example.flow.succeeds
  reason: Approved behavior is unchanged.
documentation_impact:
  generated_reference:
    status: unchanged
    reason: Models and examples are unchanged.
  user_docs:
    status: unchanged
    reason: User-visible behavior is unchanged.
  semantic_layer:
    status: unchanged
    reason: Architecture boundaries are unchanged.
implementation_state:
""",
        1,
    ).replace(
        "    verification_ids:\n      - V-EXAMPLE\n",
        "    verification_ids:\n      - V-EXAMPLE\n    contract_assertions:\n      - example.flow.succeeds\n",
        1,
    ).replace(
        "    assertions:\n      - example assertion\n",
        "    assertions:\n      - example assertion\n    contract_assertions:\n      - example.flow.succeeds\n",
        1,
    )


def test_validator_accepts_plan_like_spec(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(tmp_path, minimal_spec())

    data = spec_validate.validate_spec(path)

    assert data["id"] == "example"


# contract-test: tooling
def test_validator_accepts_schema_v3_contract_traceability(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(tmp_path, schema_v3_spec())

    data = spec_validate.validate_spec(path)

    assert data["schema_version"] == 3
    assert data["contract_refs"][0]["id"] == "feature.example"


# contract-test: tooling
def test_validator_rejects_schema_v3_without_contract_assertions(tmp_path):
    spec_validate = load_module("spec_validate")
    body = schema_v3_spec().replace(
        "    contract_assertions:\n      - example.flow.succeeds\n",
        "",
        1,
    )

    with pytest.raises(spec_validate.SpecError, match="contract_assertions"):
        spec_validate.validate_spec(write_spec(tmp_path, body))


def test_validator_rejects_vague_acceptance_criteria_without_ambiguous_coverage(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(
        tmp_path,
        minimal_spec(
            extra_ac="""
  - id: AC-2
    scenario: S-1
    text: All tests pass.
    required: true
    status: pending
    coverage_status: covered
    verification_scope: full_ci
""",
        ),
    )

    try:
        spec_validate.validate_spec(path)
    except spec_validate.SpecError as exc:
        assert "vague" in str(exc)
    else:
        raise AssertionError("vague acceptance criterion should fail validation")


def test_validator_allows_unchecked_required_assumption_before_verify_gate(tmp_path):
    spec_validate = load_module("spec_validate")
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        minimal_spec(
            extra_top_level="""
assumptions:
  - id: A-1
    text: Existing API supports the new route.
    required_before: implementation
    status: unchecked
""",
        ),
    )

    assert spec_validate.validate_spec(path)["id"] == "example"
    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("unresolved required assumption" in failure for failure in failures)


def test_validator_counts_top_level_verification_as_coverage(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(
        tmp_path,
        minimal_spec(
            extra_ac="""
  - id: AC-2
    scenario: S-1
    text: Alice confirms the physical setup is ready.
    required: true
    status: pending
    coverage_status: covered
    verification_scope: user_confirmation
    verification_ids:
      - V-MANUAL
""",
            extra_top_level="""
  - id: TASK-2
    title: Confirm physical setup
    status: pending
    phase: working_tasks
    covers:
      scenarios:
        - S-1
      acceptance_criteria:
        - AC-2
    verification_ids:
      - V-MANUAL
    independently_deployable: true
""",
        ).replace(
            """  - id: V-EXAMPLE
    kind: automated_test
    phase: final
    required_for_done: true
    covers:
      - AC-1
    status: passed
    evidence:
      status: passed
      run_id: local:green
      timestamp: "2026-07-02T00:00:00Z"
""",
            """  - id: V-EXAMPLE
    kind: automated_test
    phase: final
    required_for_done: true
    covers:
      - AC-1
    status: passed
    evidence:
      status: passed
      run_id: local:green
      timestamp: "2026-07-02T00:00:00Z"
  - id: V-MANUAL
    kind: user_confirmation
    phase: final
    required_for_done: true
    covers:
      - AC-2
    status: pending
    evidence:
      status: pending
      timestamp: ""
""",
        ),
    )

    assert spec_validate.validate_spec(path)["id"] == "example"


def test_spec_verify_allows_flexible_red_evidence(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(tmp_path, minimal_spec().replace("status: failed_as_expected", "status: passed_unexpectedly", 1))

    assert spec_verify.verify_spec(path, require_red=True, require_green=False) == []


def test_spec_verify_rejects_pending_required_final_verification(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        minimal_spec().replace(
            """    status: passed
    evidence:
      status: passed
      run_id: local:green
""",
            """    status: pending
    evidence:
      status: pending
      run_id: local:green
""",
            1,
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("V-EXAMPLE" in failure for failure in failures)


def test_validator_rejects_schema_v2_without_handoff(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(
        tmp_path,
        schema_v2_spec().replace(
            """handoff:
  current_task_id: TASK-1
  next_action: Run the validator fixture.
  command: python3 -m pytest scripts/tests/test_spec_workflow_validation.py
  expected_outcome: The fixture passes after validator implementation.
  blocker: null
  last_verified_commit: abc1234
""",
            "",
        ),
    )

    try:
        spec_validate.validate_spec(path)
    except spec_validate.SpecError as exc:
        assert "handoff" in str(exc)
    else:
        raise AssertionError("Schema V2 specs without handoff should fail validation")


def test_validator_accepts_complete_schema_v2_spec(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(tmp_path, schema_v2_spec())

    assert spec_validate.validate_spec(path)["schema_version"] == 2


def test_validator_rejects_schema_v2_task_without_expected_files(tmp_path):
    spec_validate = load_module("spec_validate")
    path = write_spec(tmp_path, schema_v2_spec().replace("""    expected_files:
      - scripts/spec_validate.py
""", ""))

    try:
        spec_validate.validate_spec(path)
    except spec_validate.SpecError as exc:
        assert "expected_files" in str(exc)
    else:
        raise AssertionError("Schema V2 tasks without expected_files should fail validation")


def test_validator_reports_all_independent_schema_errors(tmp_path):
    spec_validate = load_module("spec_validate")
    body = schema_v2_spec().replace(
        "    phase: working_tasks\n",
        "    phase: unsupported\n",
    ).replace(
        """    covers:
      scenarios:
        - S-1
      acceptance_criteria:
        - AC-1
""",
        """    covers:
      - AC-1
""",
    ).replace(
        """    expected_files:
      - scripts/spec_validate.py
""",
        "",
        1,
    )

    with pytest.raises(spec_validate.SpecError) as raised:
        spec_validate.validate_spec(write_spec(tmp_path, body))

    assert len(raised.value.errors) == 3
    message = str(raised.value)
    assert "TASK-1.phase" in message
    assert "tasks[1].covers must be a mapping" in message
    assert "TASK-1 Schema V2 record requires expected_files" in message


def test_validator_reports_malformed_task_verification_ids_once(tmp_path):
    spec_validate = load_module("spec_validate")
    body = schema_v2_spec().replace(
        """    verification_ids:
      - V-EXAMPLE
    dependencies: []
""",
        """    verification_ids: V-EXAMPLE
    dependencies: []
""",
    )

    with pytest.raises(spec_validate.SpecError) as raised:
        spec_validate.validate_spec(write_spec(tmp_path, body))

    assert raised.value.errors == ["tasks[1].verification_ids must be a non-empty list"]


def test_spec_verify_rejects_schema_v2_green_evidence_without_subject_commit(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        schema_v2_spec().replace("""        subject_commit: abc1234
        timestamp: "2026-07-02T00:00:00Z"
""", """        timestamp: "2026-07-02T00:00:00Z"
""", 2),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("subject_commit" in failure for failure in failures)


def test_spec_verify_rejects_schema_v2_stale_green_evidence(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        schema_v2_spec().replace(
            """implementation_state:
  subject_commit: abc1234
""",
            """implementation_state:
  subject_commit: def5678
""",
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("stale" in failure for failure in failures)


def test_spec_verify_accepts_ancestor_green_evidence(monkeypatch):
    spec_verify = load_module("spec_verify")
    monkeypatch.setattr(
        spec_verify.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
    )

    assert spec_verify._evidence_commit_covers_implementation("abc1234", "def5678")


def test_spec_verify_rejects_schema_v2_playwright_evidence_without_deployment_reference(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        schema_v2_spec()
        .replace("type: pytest", "type: playwright", 1)
        .replace("""    green_phase:
      required: true
      expected: pass
""", """    green_phase:
      required: true
      expected: pass_after_deploy
""", 1)
        .replace(
            """    command: python3 -m pytest backend/tests/test_example.py
    covers:
""",
            """    command: python3 scripts/tests.py run --spec example.spec.ts
    target: app.dev.openmates.org
    covers:
""",
            1,
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("deployment_reference" in failure for failure in failures)


def test_spec_verify_rejects_schema_v2_manual_evidence_without_reason(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(tmp_path, schema_v2_spec().replace("kind: automated_test", "kind: manual_check", 1))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("reason" in failure for failure in failures)


def ui_visual_smoke_spec(summary: str, viewports: str = "[laptop, mobile]") -> str:
    return (
        schema_v2_spec()
        .replace("verification_scope: related_backend", "verification_scope: ui_visual_smoke", 1)
        .replace("V-EXAMPLE", "V-UI-VISUAL-SMOKE")
        .replace("kind: automated_test", "kind: manual_check", 1)
        .replace(
            "      command: python3 -m pytest backend/tests/test_example.py\n"
            "      run_id: local:green\n"
            "      subject_commit: abc1234\n"
            "      timestamp: \"2026-07-02T00:00:00Z\"",
            "      run_id: test-results/visual-smoke/run/summary.json\n"
            "      command: node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/example --session abcd\n"
            "      subject_commit: abc123\n"
            "      reviewed_urls:\n"
            "        - https://app.dev.openmates.org/example\n"
            f"      viewports: {viewports}\n"
            f"      summary: \"{summary}\"\n"
            "      reason: Manual screenshot review.\n"
            "      timestamp: \"2026-07-02T00:00:00Z\"",
            1,
        )
    )


def test_spec_verify_rejects_ui_visual_smoke_without_screenshot_review_summary(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(tmp_path, ui_visual_smoke_spec("Checked route returned HTTP 200."))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("screenshot review" in failure for failure in failures)


def test_spec_verify_accepts_ui_visual_smoke_evidence(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        ui_visual_smoke_spec("Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert failures == []


def test_spec_verify_rejects_ui_visual_smoke_without_mobile_viewport(tmp_path):
    spec_verify = load_module("spec_verify")
    path = write_spec(
        tmp_path,
        ui_visual_smoke_spec(
            "Reviewed laptop screenshots. Defects: none. Accepted differences: none.",
            viewports="[laptop]",
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("laptop and mobile" in failure for failure in failures)


def test_spec_verify_json_reports_active_handoff_blockers(tmp_path):
    path = write_spec(
        tmp_path,
        schema_v2_spec()
        .replace("status: approved", "status: implementing", 1)
        .replace("        status: passed", "        status: pending", 1)
        .replace(
            "blocker: null",
            "blocker:\n    task_id: TASK-1\n    requires_user_input: true\n    reason: Needs a product decision.\n    question: Which architecture should be used?\n    next_action: Apply the selected architecture.",
        ),
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spec_verify.py"), str(path), "--json"],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["active"] is True
    assert payload["complete"] is False
    assert payload["blocked"] is True
    assert payload["requires_user_input"] is True
    assert payload["current_task_id"] == "TASK-1"
    assert len(payload["state_fingerprint"]) == 64


def test_spec_verify_json_keeps_current_task_active_for_unstructured_or_downstream_blockers(tmp_path):
    path = write_spec(
        tmp_path,
        schema_v2_spec()
        .replace("status: approved", "status: implementing", 1)
        .replace("        status: passed", "        status: pending", 1)
        .replace("blocker: null", "blocker:\n    reason: A later web task needs deployment approval."),
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spec_verify.py"), str(path), "--json"],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["active"] is True
    assert payload["blocked"] is False
    assert payload["requires_user_input"] is False


def test_spec_verify_json_does_not_activate_invalid_specs(tmp_path):
    path = write_spec(tmp_path, "schema_version: 2\nstatus: implementing\n")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spec_verify.py"), str(path), "--json"],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["active"] is False
    assert payload["complete"] is False
