#!/usr/bin/env python3
"""
Regression tests for documentation claim verification entry points.

These tests give the session coverage gate a direct filename match for
scripts/docs_claims_verify.py while keeping the detailed policy fixtures in
test_docs_claims_enforcement.py.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_claims_verify.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_claims_verify", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_active_doc_without_claims_is_warning_unless_enforced(tmp_path):
    docs = tmp_path / "docs"
    doc = docs / "architecture" / "example.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "---\nstatus: active\ndoc_type: explanation\naudience:\n  - contributors\nlast_verified: 2026-06-10\n---\n# Example\n",
        encoding="utf-8",
    )
    module = load_module()

    rollout_result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=False)
    strict_result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=True)

    assert rollout_result.errors == []
    assert any("active doc is missing claims" in warning for warning in rollout_result.warnings)
    assert any("active doc is missing claims" in error for error in strict_result.errors)
