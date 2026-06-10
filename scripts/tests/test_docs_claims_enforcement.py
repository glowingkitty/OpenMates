#!/usr/bin/env python3
"""
Regression tests for unified documentation claim enforcement.

The claim verifier is the canonical wiring check between kept documentation and
real assertions. These tests cover repo policy using temporary fixtures so the
rules can be tightened without depending on legacy docs cleanup state.

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


def write_doc(path: Path, frontmatter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n# Doc\n", encoding="utf-8")


def test_active_docs_require_metadata_and_claims(tmp_path):
    docs = tmp_path / "docs"
    write_doc(
        docs / "architecture" / "missing.md",
        "status: active\nlast_verified: 2026-06-10\n",
    )
    module = load_module()

    result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=True)

    assert any("missing doc_type" in error for error in result.errors)
    assert any("missing audience" in error for error in result.errors)
    assert any("missing claims" in error for error in result.errors)


def test_invalid_statuses_are_rejected_outside_specs(tmp_path):
    docs = tmp_path / "docs"
    write_doc(
        docs / "architecture" / "future.md",
        "status: planned\ndoc_type: explanation\naudience:\n  - contributors\nlast_verified: 2026-06-10\n",
    )
    write_doc(
        docs / "specs" / "future" / "spec.md",
        "status: planned\ndoc_type: reference\naudience:\n  - contributors\nlast_verified: 2026-06-10\n",
    )
    module = load_module()

    result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=True)

    assert any("invalid status outside docs/specs" in error for error in result.errors)
    assert not any("docs/specs/future/spec.md" in error for error in result.errors)


def test_claims_require_existing_assertion_markers(tmp_path):
    docs = tmp_path / "docs"
    test_file = tmp_path / "tests" / "test_contract.py"
    test_file.parent.mkdir()
    test_file.write_text('def test_contract(doc_assert):\n    doc_assert("real-claim")\n', encoding="utf-8")
    write_doc(
        docs / "architecture" / "contract.md",
        "status: active\n"
        "doc_type: explanation\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-10\n"
        "claims:\n"
        "  - id: real-claim\n"
        "    type: backend\n"
        "    file: tests/test_contract.py\n"
        "    assertion: real-claim\n"
        "  - id: missing-claim\n"
        "    type: backend\n"
        "    file: tests/test_contract.py\n"
        "    assertion: missing-claim\n",
    )
    module = load_module()

    result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=True)

    assert any("missing-claim" in error and "assertion marker not found" in error for error in result.errors)
    assert not any("real-claim" in error for error in result.errors)


def test_manual_claims_require_reasons(tmp_path):
    docs = tmp_path / "docs"
    write_doc(
        docs / "architecture" / "manual.md",
        "status: active\n"
        "doc_type: explanation\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-10\n"
        "claims:\n"
        "  - id: provider-live-behavior\n"
        "    type: manual\n",
    )
    module = load_module()

    result = module.validate_docs_tree(docs, repo_root=tmp_path, enforce_active=True)

    assert any("manual but has no reason" in error for error in result.errors)
