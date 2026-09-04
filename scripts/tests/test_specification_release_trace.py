#!/usr/bin/env python3
"""Specification-aware commit trailer and release aggregation tests.

Architecture: docs/plans/contract-driven-development/plan.yml
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "scripts" / "specifications.py"
    spec = importlib.util.spec_from_file_location("openmates_specification_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_summary_aggregates_specification_trailers():
    module = load_module()
    messages = [
        "Implement search\n\nSpecifications: feature.web-search@1\nAssertions: web-search.request.validated\nPlan: web-search\nSpecification-Impact: implementation-only\nSpecification-Exceptions: EXC-1\n",
        "Render search\n\nSpecifications: feature.web-search@1\nAssertions: web-search.surface-parity\nPlan: web-search\nSpecification-Impact: implementation-only\n",
    ]

    summary = module.build_release_summary(messages)

    assert summary["specifications"] == ["feature.web-search@1"]
    assert summary["assertions"] == ["web-search.request.validated", "web-search.surface-parity"]
    assert summary["plans"] == ["web-search"]
    assert summary["impacts"] == ["implementation-only"]
    assert summary["approved_exceptions"] == ["EXC-1"]


def test_specification_governed_commit_rejects_missing_required_metadata():
    module = load_module()

    errors = module.validate_commit_trace("Implement search", specification_governed=True)

    assert any("Specifications" in error for error in errors)
    assert any("Assertions" in error for error in errors)
    assert any("Plan" in error for error in errors)
    assert any("Specification-Impact" in error for error in errors)
