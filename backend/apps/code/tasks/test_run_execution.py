# backend/apps/code/tasks/test_run_execution.py
# contract-test-file: infrastructure
#
# Worker-side glue for Code Run test runs: executes a TestRunSpec through the
# E2B test runner and attaches persisted artifact ids to the evidence list.
# Kept separate from run_code_task.py so that file does not grow.

from __future__ import annotations

from typing import Any

from backend.shared.providers.e2b_code_runner import (
    CancelCallback,
    CodeRunFile,
    CodeRunResult,
    OutputCallback,
)
from backend.shared.providers.e2b_cli_test_recorder import cli_recorder_wrapper
from backend.shared.providers.e2b_test_recorder import browser_recorder_wrapper
from backend.shared.providers.e2b_test_runner import TestRunOutcome, run_tests_in_e2b
from backend.shared.python_schemas.code_test_run import TestRunSpec


def execute_test_run(
    payload: dict[str, Any],
    on_output: OutputCallback,
    api_key: str,
    should_cancel: CancelCallback,
) -> tuple[CodeRunResult, TestRunOutcome]:
    spec = TestRunSpec.model_validate(payload["test_run"])
    files = [CodeRunFile(**item) for item in payload["files"]]
    recorder_wrapper = {"cli": cli_recorder_wrapper, "browser": browser_recorder_wrapper}.get(spec.kind)
    outcome = run_tests_in_e2b(files, spec, on_output, api_key, should_cancel, recorder_wrapper)
    exit_code = outcome.result.exit_code
    if exit_code in (None, 0) and outcome.result.status != "passed":
        exit_code = 1  # a failed or errored result never reports success to the generic run path
    return CodeRunResult(
        exit_code=exit_code,
        duration_seconds=outcome.duration_seconds,
        output_truncated=outcome.output_truncated,
        sandbox_id=outcome.sandbox_id,
        artifacts=outcome.artifacts,
        skipped_artifacts=outcome.skipped_artifacts,
    ), outcome


def final_test_result(outcome: TestRunOutcome, stored_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize the result with the asset id and file variant of each persisted
    evidence artifact (both are needed to mint a download link later)."""
    asset_by_path: dict[str, tuple[str, str | None]] = {}
    for artifact in stored_artifacts:
        asset_id = artifact.get("asset_id")
        path = artifact.get("normalized_path") or artifact.get("path")
        variant = artifact.get("variant")
        if isinstance(asset_id, str) and isinstance(path, str):
            asset_by_path[path] = (asset_id, variant if isinstance(variant, str) else None)
    result = outcome.result.model_copy(deep=True)
    for item in result.evidence:
        item.asset_id, item.variant = asset_by_path.get(item.path, (None, None))
    return result.model_dump(mode="json")
