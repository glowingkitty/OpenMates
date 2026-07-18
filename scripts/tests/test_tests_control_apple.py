#!/usr/bin/env python3
"""
Regression tests for Apple test normalization in the test control plane.

Apple verification runs happen outside the Linux process, but their results must
participate in the same Directus-backed state and claim model as web/backend tests.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_tests_control_apple", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
    return module


def test_apple_failure_uses_same_current_state_and_claim_flow(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "apple-001",
        "git_sha": "abc123",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "suites": {
            "apple": {
                "status": "failed",
                "tests": [{
                    "name": "ChatStreamingParity",
                    "file": "ChatStreamingParity",
                    "status": "failed",
                    "error": "XCTest assertion failed while waiting for streamed assistant text",
                    "verification_command": "python3 scripts/apple_remote.py test-ios --only ChatStreamingParity",
                }],
            }
        },
    })

    record = tests_control.load_state()["tests"]["apple::ChatStreamingParity"]
    assert record["suite"] == "apple"
    assert record["status"] == "failed"
    assert tests_control.get_store().test_catalog["apple::ChatStreamingParity"]["suite"] == "apple"

    claim = tests_control.claim_next(session_id="s-apple")
    assert claim is not None
    assert claim["entry"]["suite"] == "apple"
    assert claim["entry"]["verification_command"] == "python3 scripts/apple_remote.py test-ios --only ChatStreamingParity"
