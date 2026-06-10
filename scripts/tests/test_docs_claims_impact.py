#!/usr/bin/env python3
"""
Regression tests for documentation claim impact analysis.

These tests cover the hook-facing analyzer directly so changes to docs or linked
assertion files keep reporting connected docs, tests, and claim IDs.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_claims_impact.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_claims_impact", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_changed_assertion_file_reports_linked_doc_and_claim(tmp_path):
    docs = tmp_path / "docs"
    repo_root = tmp_path
    doc = docs / "architecture" / "contract.md"
    test_file = repo_root / "tests" / "test_contract.py"
    doc.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    test_file.write_text('def test_contract(doc_assert):\n    doc_assert("contract-claim")\n', encoding="utf-8")
    doc.write_text(
        "---\n"
        "status: active\n"
        "doc_type: explanation\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-10\n"
        "claims:\n"
        "  - id: contract-claim\n"
        "    type: backend\n"
        "    file: tests/test_contract.py\n"
        "    assertion: contract-claim\n"
        "---\n"
        "# Contract\n",
        encoding="utf-8",
    )
    module = load_module()

    result = module.analyze_paths(["tests/test_contract.py"], docs_root=docs, repo_root=repo_root)

    assert result["affected_docs"] == ["docs/architecture/contract.md"]
    assert result["affected_tests"] == ["tests/test_contract.py"]
    assert result["claim_ids"] == ["contract-claim"]
