#!/usr/bin/env python3
# contract-test-file: tooling
"""Tests for the complete YAML Specification approval fallback."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import specification_approval_yaml as approval_yaml
from scripts import specifications


def _bundle(tmp_path: Path) -> specifications.SpecificationBundle:
    tmp_path.mkdir(parents=True, exist_ok=True)
    specification_text = (
        "schema_version: 1\n"
        "id: feature.example\n"
        "version: 1\n"
        "status: draft\n"
        "title: Example\n"
        "summary: Exact source text.\n"
        "scope:\n  includes: [Review]\n  excludes: [Implementation]\n"
        "assertions:\n  - id: example.visible\n    type: behavior\n    must: The result is visible.\n"
        "applies_to:\n  audiences: [Approver]\n"
        "examples:\n  file: examples.yml\n  required_groups: [cases]\n"
    )
    examples_text = (
        "schema_version: 1\n"
        "specification: feature.example@1\n"
        "cases:\n"
        "  - id: visible-result\n"
        "    assertion_ids: [example.visible]\n"
        "    given: A completed action.\n"
        "    then: The result is visible.\n"
    )
    (tmp_path / "specification.yml").write_text(specification_text, encoding="utf-8")
    (tmp_path / "examples.yml").write_text(examples_text, encoding="utf-8")
    return specifications.validate_bundle(tmp_path)


def _empty_git_baseline(repo: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Specification Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "specification@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "baseline"], cwd=repo, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_yaml_fallback_contains_both_exact_source_documents_and_fingerprint(tmp_path: Path, monkeypatch) -> None:
    baseline_commit = _empty_git_baseline(tmp_path)
    bundle = _bundle(tmp_path / "specifications" / "example")
    monkeypatch.setattr(specifications, "REPO_ROOT", tmp_path)
    artifact = approval_yaml.build_review_artifact(
        bundle,
        baseline_ref="HEAD",
        baseline_commit=baseline_commit,
    )
    artifact_path = tmp_path / "review.approval.yml"
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")

    markdown = approval_yaml.render_markdown(artifact, artifact_path)

    assert bundle.fingerprint in markdown
    assert (bundle.path / "specification.yml").read_text(encoding="utf-8") in markdown
    assert (bundle.path / "examples.yml").read_text(encoding="utf-8") in markdown
    validated = specifications.validate_review_artifact(artifact_path, bundle)
    assert validated["review_format"] == "yaml_chat"
    assert validated["fingerprint"] == bundle.fingerprint


def test_yaml_fallback_rejects_handcrafted_arbitrary_baseline(tmp_path: Path, monkeypatch) -> None:
    _empty_git_baseline(tmp_path)
    bundle = _bundle(tmp_path / "specifications" / "example")
    monkeypatch.setattr(specifications, "REPO_ROOT", tmp_path)
    artifact = approval_yaml.build_review_artifact(
        bundle,
        baseline_ref="HEAD",
        baseline_commit="b" * 40,
    )
    artifact_path = tmp_path / "review.approval.yml"
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")

    with pytest.raises(specifications.SpecificationError, match="baseline commit does not match"):
        specifications.validate_review_artifact(artifact_path, bundle)

    artifact["baseline_ref"] = "refs/heads/not-a-real-baseline"
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")
    with pytest.raises(specifications.SpecificationError, match="baseline ref does not resolve"):
        specifications.validate_review_artifact(artifact_path, bundle)


def test_yaml_fallback_rejects_handcrafted_ineligible_examples(tmp_path: Path, monkeypatch) -> None:
    baseline_commit = _empty_git_baseline(tmp_path)
    bundle_path = tmp_path / "specifications" / "example"
    _bundle(bundle_path)
    examples_path = bundle_path / "examples.yml"
    examples = yaml.safe_load(examples_path.read_text(encoding="utf-8"))
    examples["cases"][0]["given"] = {"internal_flag": True}
    examples["cases"][0]["then"] = {"fixture_result": True}
    examples_path.write_text(yaml.safe_dump(examples, sort_keys=False), encoding="utf-8")
    bundle = specifications.validate_bundle(bundle_path)
    monkeypatch.setattr(specifications, "REPO_ROOT", tmp_path)
    artifact = approval_yaml.build_review_artifact(
        bundle,
        baseline_ref="HEAD",
        baseline_commit=baseline_commit,
    )
    artifact_path = tmp_path / "review.approval.yml"
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")

    with pytest.raises(specifications.SpecificationError, match="needs 1–2 concrete mapped examples"):
        specifications.validate_review_artifact(artifact_path, bundle)


def test_yaml_fallback_rejects_content_that_no_longer_matches_bundle(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    artifact = approval_yaml.build_review_artifact(
        bundle,
        baseline_ref="HEAD",
        baseline_commit="b" * 40,
    )
    artifact_path = tmp_path / "review.approval.yml"
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")
    (tmp_path / "examples.yml").write_text(
        (tmp_path / "examples.yml").read_text(encoding="utf-8") + "# changed after presentation\n",
        encoding="utf-8",
    )

    try:
        specifications.validate_review_artifact(artifact_path, bundle)
    except specifications.SpecificationError as exc:
        assert "does not match the current bundle" in str(exc)
    else:
        raise AssertionError("stale YAML review artifact was accepted")


def test_documented_yaml_fallback_entry_point_loads_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/specification_approval_yaml.py", "--help"],
        cwd=approval_yaml.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "complete YAML Specification approval fallback" in result.stdout
