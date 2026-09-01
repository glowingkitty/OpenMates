#!/usr/bin/env python3
"""Specification post-edit hook behavior and approval instruction tests.

Temporary git repositories prove warning behavior without mutating OpenMates
Specification state. Architecture: docs/plans/contract-driven-development/plan.yml
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "specification-test-impact.sh"


def run_hook(tmp_path: Path, relative_path: str, content: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    env = {**os.environ, "OPENMATES_PROJECT_ROOT": str(tmp_path), "OPENMATES_SESSION_ID": "test-session"}
    payload = json.dumps({"tool_input": {"file_path": str(path)}})
    return subprocess.run([str(HOOK)], input=payload, text=True, capture_output=True, env=env, check=False)


# contract-test: tooling
def test_hook_ignores_non_test_non_contract_file(tmp_path):
    result = run_hook(tmp_path, "src/example.py", "value = 1\n")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# contract-test: tooling
def test_hook_warns_for_unmapped_changed_test(tmp_path):
    result = run_hook(tmp_path, "tests/example.spec.ts", "test('behavior', () => {});\n")

    assert result.returncode == 0
    assert "specifications.py check-test" in result.stderr
    assert "search existing Specifications" in result.stderr
    assert "define-specification" in result.stderr


# contract-test: tooling
def test_hook_checks_each_test_even_when_file_contains_a_marker(tmp_path):
    result = run_hook(
        tmp_path,
        "tests/example.spec.tsx",
        "// contract-test: tooling\ntest('mapped tooling', () => {});\ntest('still unmapped', () => {});\n",
    )

    assert result.returncode == 0
    assert "still unmapped" in result.stderr


# contract-test: tooling
def test_hook_requires_full_new_contract_confirmation(tmp_path):
    result = run_hook(tmp_path, "specifications/features/example/specification.yml", "id: feature.example\n")

    assert result.returncode == 0
    assert "quote the complete specification.yml" in result.stderr
    assert "explicit user confirmation" in result.stderr
    assert "exact bundle hash" in result.stderr


# contract-test: tooling
def test_hook_treats_examples_as_approval_bound(tmp_path):
    result = run_hook(tmp_path, "specifications/features/example/examples.yml", "valid_inputs: []\n")

    assert result.returncode == 0
    assert "specification.yml or examples.yml" in result.stderr
    assert "Any later bundle edit invalidates approval" in result.stderr
