# contract-test-file: tooling
"""Keep package workflow path filters aligned with scripts/ci_impact.py.

Purpose: prevent drift between declarative GitHub triggers and classifier rules.
Scope: parses local workflow YAML only; no remote CI operations are invoked.
Privacy: assertions inspect only public repository metadata.
Run: python3 -m pytest scripts/tests/test_ci_workflow_scope.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_impact():
    spec = importlib.util.spec_from_file_location("ci_impact_scope", ROOT / "scripts" / "ci_impact.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_impact_scope"] = module
    spec.loader.exec_module(module)
    return module


def workflow_triggers(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("on", data.get(True))


def test_package_workflows_match_canonical_impact_patterns() -> None:
    impact = load_impact()
    for workflow, target in (("publish-cli.yml", "cli"), ("publish-python-sdk.yml", "python")):
        triggers = workflow_triggers(ROOT / ".github" / "workflows" / workflow)
        expected = list(impact.workflow_path_patterns(target))
        assert triggers["push"]["paths"] == expected
        assert triggers["pull_request"]["paths"] == expected
        assert triggers["workflow_dispatch"] == {}


def test_package_workflows_exclude_apple_only_paths() -> None:
    impact = load_impact()
    apple_path = "apple/OpenMates/Sources/App/OpenMatesApp.swift"

    assert impact.classify_paths([apple_path]).cli_package is False
    assert impact.classify_paths([apple_path]).python_package is False


def test_isolated_workflow_reconstructs_verified_candidate_without_git_refs() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    for value in (
        "source_commit", "candidate_tree", "candidate_owner",
        "candidate_patch_sha256", "candidate_patch_url",
        "'git', 'apply', '--binary', '--index", "'git', 'commit-tree'",
        "Candidate commit identity mismatch", "symbolic-ref', '-q', 'HEAD'",
    ):
        assert value in workflow
    assert "refs/heads/codex/ci" not in workflow
    assert "git push" not in workflow
    assert "CANDIDATE_PATCH_URL: ${{ inputs.candidate_patch_url }}" not in workflow
    assert "event.get('inputs', {}).get('candidate_patch_url', '')" in workflow


def test_preparation_uses_exact_run_artifacts_and_preserves_component_bypass() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    assert "options: [prepare, component, e2e" in workflow
    assert "run-id: ${{ inputs.prepared_run_id }}" in workflow
    assert "name: ci-preparation-${{ inputs.preparation_key }}" in workflow
    assert "python3 ../tooling/scripts/ci_artifacts.py restore" in workflow
    assert '--manifest "${{ steps.artifacts.outputs.manifest }}"' in workflow
    assert "if: inputs.mode != 'prepare'" in workflow
    assert "inputs.mode == 'component' || inputs.mode == 'e2e'" in workflow


def test_preparation_fails_closed_for_unpublished_candidate_source() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    checkout = workflow.index("ref: ${{ inputs.checkout_ref }}")
    guard = workflow.index("- name: Reject unpublished preparation source")
    tooling = workflow.index("sparse-checkout: scripts")
    reconstruction = workflow.index("- name: Reconstruct and verify exact detached source")
    assert checkout < guard < tooling < reconstruction
    guard_section = workflow[guard:tooling]
    assert "if: inputs.mode == 'prepare'" in guard_section
    assert "candidate_patch_url" in guard_section
    assert "assert not any(candidate_metadata)" in guard_section
    assert "['git', 'rev-parse', 'HEAD']" in guard_section
    assert "actual == expected" in guard_section
    assert "source already published" in guard_section


def test_preparation_artifact_labels_do_not_claim_private_storage() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    preparation_steps = workflow[
        workflow.index("- name: Export cold runtime images") :
        workflow.index("- name: Start isolated backend")
    ]
    assert "private preparation" not in preparation_steps.lower()
    assert "Actions preparation bytes" in preparation_steps
    assert "Actions preparation artifact" in preparation_steps
    assert "repository-readable" in preparation_steps


def test_cli_build_is_capability_gated_and_broad_publisher_does_not_compete() -> None:
    isolated = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    publisher = (ROOT / ".github/workflows/publish-selfhost-images.yml").read_text()
    cli_step = isolated.split("- name: Build local CLI only when consumed", 1)[1].split(
        "- name: Export cold runtime images", 1
    )[0]
    assert "inputs.prepare_cli == 'true'" in cli_step
    assert "inputs.mode == 'e2e'" in cli_step
    assert "visual-smoke" not in cli_step
    assert "ci-preparation-" not in publisher


def test_schema_publisher_verifies_the_exact_local_carrier_before_push() -> None:
    workflow = (ROOT / ".github/workflows/publish-selfhost-images.yml").read_text()
    build = workflow.index("- name: Build candidate CI schema image locally")
    verify = workflow.index("- name: Verify candidate schema in two fresh consumers")
    publish = workflow.index("- name: Publish the exact verified CI schema image")
    assert build < verify < publish
    schema_section = workflow[build:publish]
    assert "load: true" in schema_section
    assert "tags: openmates-ci-database:local" in schema_section
    assert "ci_schema_bundle.py verify-image openmates-ci-database:local" in schema_section
