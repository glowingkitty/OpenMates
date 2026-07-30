#!/usr/bin/env python3
"""Regression tests for example-chat usage coverage audit helpers.

Purpose: keep generated public example chats able to expose static Usage tabs
whenever source usage rows have been backfilled into response_credits.
Scope: validates the deterministic coverage scan without requiring API access.
Run: python3 -m pytest scripts/tests/test_example_chat_usage_coverage.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_example_audit():
    spec = importlib.util.spec_from_file_location(
        "openmates_audit_example_chats_usage",
        ROOT / "scripts/audit_example_chats.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_usage_coverage_detects_source_backed_examples_and_known_credits() -> None:
    audit = load_example_audit()

    coverage = audit.example_usage_coverage()

    assert coverage.source_backed_count > 0
    assert coverage.with_response_credits_count > 0
    assert coverage.with_response_credits_count <= coverage.source_backed_count
    assert "berlin-morning-bike-forecast.ts" not in coverage.missing_response_credits


def test_source_chat_id_and_response_credits_detection() -> None:
    audit = load_example_audit()
    source = """// Example chat: Priced
// Extracted from shared chat 11111111-2222-3333-4444-555555555555
messages: [{ response_credits: 42 }]
"""

    assert audit.source_chat_id_from_header(source) == "11111111-2222-3333-4444-555555555555"
    assert audit.has_response_credits(source) is True
