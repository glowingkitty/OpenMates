#!/usr/bin/env python3
"""Generated Specification reference and curated documentation impact tests.

Architecture: docs/plans/contract-driven-development/plan.yml
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def doc_assert(_claim_id: str) -> None:
    """Marker consumed by docs_claims_verify.py."""


def load_module():
    path = ROOT / "scripts" / "specifications.py"
    spec = importlib.util.spec_from_file_location("openmates_specification_docs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_documentation_impact_rejects_unresolved_required_updates():
    doc_assert("semantic-layer-contract-workflow")
    doc_assert("semantic-web-search-contract-boundary")
    module = load_module()
    impact = {
        "generated_reference": {"status": "regenerate"},
        "user_docs": {"status": "update_required", "documents": []},
        "semantic_layer": {"status": "unchanged", "reason": "Architecture is unchanged."},
    }

    errors = module.check_documentation_impact(impact, generated_current=False)

    assert any("generated reference" in error for error in errors)
    assert any("user_docs" in error for error in errors)


def test_unchanged_curated_docs_require_reason():
    module = load_module()
    impact = {
        "generated_reference": {"status": "unchanged", "reason": "No Specification change."},
        "user_docs": {"status": "unchanged", "reason": "No user-visible change."},
        "semantic_layer": {"status": "unchanged"},
    }

    assert any("semantic_layer" in error for error in module.check_documentation_impact(impact, generated_current=True))
