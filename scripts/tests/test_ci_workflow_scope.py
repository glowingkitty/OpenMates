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


def test_preparation_uses_private_transport_and_preserves_component_bypass() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    assert "options: [prepare, component, e2e" in workflow
    assert "preparation_transport:" in workflow
    assert "ci_preparation_transport.py download" in workflow
    assert "--directory test-results/ci-preparation-download" in workflow
    assert "ci_preparation_transport.py upload" in workflow
    assert "--directory test-results/ci-preparation" in workflow
    assert "actions/download-artifact@v4" not in workflow
    assert "python3 ../tooling/scripts/ci_artifacts.py restore" in workflow
    assert '--manifest "${{ steps.artifacts.outputs.manifest }}"' in workflow
    assert "if: inputs.mode != 'prepare'" in workflow
    assert "inputs.mode == 'component' || inputs.mode == 'e2e'" in workflow


def test_preparation_requires_private_ticket_before_build() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    tooling = workflow.index("sparse-checkout: scripts")
    guard = workflow.index("- name: Require private preparation transport ticket")
    reconstruction = workflow.index("- name: Reconstruct and verify exact detached source")
    install = workflow.index("- name: Install workspace dependencies")
    assert tooling < guard < reconstruction < install
    guard_section = workflow[guard:reconstruction]
    assert "inputs.mode == 'prepare'" in guard_section
    assert "inputs.mode == 'e2e'" in guard_section
    assert "inputs.mode == 'visual-smoke'" in guard_section
    assert "inputs.preparation_key != ''" in guard_section
    assert "ci_preparation_transport.py validate" in guard_section
    assert "GITHUB_EVENT_PATH" not in guard_section
    assert "Reject unpublished preparation source" not in workflow
    assert "source already published" not in workflow


def test_legacy_unkeyed_cold_consumers_do_not_require_transport_ticket() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    )
    guard = next(
        step
        for step in workflow["jobs"]["test"]["steps"]
        if step.get("name") == "Require private preparation transport ticket"
    )
    assert " ".join(guard["if"].split()) == (
        "inputs.mode == 'prepare' || "
        "((inputs.mode == 'e2e' || inputs.mode == 'visual-smoke') && "
        "inputs.preparation_key != '')"
    )


def test_preparation_never_uses_public_actions_artifact_transport() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    preparation_steps = workflow[
        workflow.index("- name: Export cold runtime images") :
        workflow.index("- name: Start isolated backend")
    ]
    assert "private preparation bundle" in preparation_steps.lower()
    assert "actions/upload-artifact" not in preparation_steps
    assert "actions/download-artifact" not in workflow
    assert "ci-preparation-${{ inputs.preparation_key }}" not in workflow


def test_result_artifact_upload_excludes_private_transport_and_build_data() -> None:
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    results = workflow[
        workflow.index("- uses: actions/upload-artifact@v4\n        if: always()") :
        workflow.index("- name: Retain original documentation screenshot output")
    ]
    for forbidden in (
        "ci-preparation",
        "ci-preparation-download",
        "ci-private",
        "preparation_transport",
        "GITHUB_EVENT_PATH",
        "frontend/apps/web_app/build",
        "frontend/packages/openmates-cli/dist",
    ):
        assert forbidden not in results


def test_candidate_docker_builds_never_export_records_or_shared_cache() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    )
    job = workflow["jobs"]["test"]
    assert job["env"]["DOCKER_BUILD_RECORD_UPLOAD"] == "false"
    builds = [
        step
        for step in job["steps"]
        if step.get("uses") == "docker/build-push-action@v6"
    ]
    assert len(builds) == 5
    for step in builds:
        assert step["with"]["cache-from"].startswith("type=gha,scope=")
        cache_to = step["with"]["cache-to"]
        assert "inputs.candidate_patch_sha256 == ''" in cache_to
        assert "type=gha,scope=" in cache_to
        assert "|| ''" in cache_to


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
