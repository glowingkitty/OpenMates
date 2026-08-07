#!/usr/bin/env python3
"""Contract-aware commit trailer and release aggregation tests.

Architecture: docs/specs/contract-driven-development/spec.yml
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "scripts" / "contracts.py"
    spec = importlib.util.spec_from_file_location("openmates_contract_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_summary_aggregates_contract_trailers():
    module = load_module()
    messages = [
        "Implement search\n\nContracts: feature.web-search@1\nAssertions: web-search.request.validated\nSpec: web-search\nContract-Impact: implementation-only\n",
        "Render search\n\nContracts: feature.web-search@1\nAssertions: web-search.surface-parity\nSpec: web-search\nContract-Impact: implementation-only\n",
    ]

    summary = module.build_release_summary(messages)

    assert summary["contracts"] == ["feature.web-search@1"]
    assert summary["assertions"] == ["web-search.request.validated", "web-search.surface-parity"]
    assert summary["specs"] == ["web-search"]


def test_commit_trace_rejects_missing_required_metadata():
    module = load_module()

    errors = module.validate_commit_trace("Implement search", contract_governed=True)

    assert any("Contracts" in error for error in errors)
    assert any("Assertions" in error for error in errors)
